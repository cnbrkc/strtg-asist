from telegram.telegram_story_worker import _scrub


def test_scrub_masks_configured_bot_token(monkeypatch):
    token = "123456789:abcdefghijklmnopQRSTUV"
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", token)

    assert token not in _scrub(f"https://api.telegram.org/bot{token}/sendPhoto")
    assert "bot***" in _scrub(f"https://api.telegram.org/bot{token}/sendPhoto")
