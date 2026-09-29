import io
import json
import urllib.error

import pytest

from strtg_asist import telegram_worker
from strtg_asist.telegram_worker import TelegramError, _describe_http_error, _scrub, _with_retries


def test_scrub_masks_configured_bot_token(monkeypatch):
    token = "123456789:abcdefghijklmnopQRSTUV"
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", token)

    assert token not in _scrub(f"https://api.telegram.org/bot{token}/sendPhoto")
    assert "bot***" in _scrub(f"https://api.telegram.org/bot{token}/sendPhoto")


def test_scrub_masks_unknown_token_shape(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)

    scrubbed = _scrub("https://api.telegram.org/bot987654:ZZZZZZZZZZZZZZZZZZZZ/getFile")

    assert "ZZZZZZZZZZZZZZZZZZZZ" not in scrubbed
    assert "bot987654:***" in scrubbed


def _http_error(status: int, payload: dict) -> urllib.error.HTTPError:
    body = io.BytesIO(json.dumps(payload).encode("utf-8"))
    return urllib.error.HTTPError("https://api.telegram.org", status, "err", {}, body)


def test_http_error_surfaces_telegram_description():
    """Gövde okunmazsa geriye sadece 'HTTP Error 400: Bad Request' kalıyordu."""
    error = _describe_http_error(_http_error(400, {"description": "caption is too long"}))

    assert "caption is too long" in str(error)
    assert error.retryable is False


def test_rate_limit_is_marked_retryable_with_retry_after():
    error = _describe_http_error(
        _http_error(429, {"description": "Too Many Requests", "parameters": {"retry_after": 7}})
    )

    assert error.retryable is True
    assert error.retry_after == 7


def test_retry_after_is_capped():
    error = _describe_http_error(
        _http_error(429, {"description": "flood", "parameters": {"retry_after": 99999}})
    )

    assert error.retry_after == telegram_worker.MAX_RETRY_AFTER_SECONDS


def test_with_retries_recovers_from_transient_failure(monkeypatch):
    monkeypatch.setattr(telegram_worker.time, "sleep", lambda _s: None)
    attempts = {"n": 0}

    def flaky():
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise TelegramError("geçici", retryable=True)
        return "ok"

    assert _with_retries("test", flaky) == "ok"
    assert attempts["n"] == 3


def test_with_retries_does_not_repeat_permanent_failure(monkeypatch):
    monkeypatch.setattr(telegram_worker.time, "sleep", lambda _s: None)
    attempts = {"n": 0}

    def permanent():
        attempts["n"] += 1
        raise TelegramError("kalıcı", retryable=False)

    with pytest.raises(RuntimeError):
        _with_retries("test", permanent)
    assert attempts["n"] == 1
