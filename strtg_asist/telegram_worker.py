"""GitHub Actions içinde çalışan Telegram story kartı üreticisi.

Cloudflare Worker yalnızca Telegram güncellemesini alır ve workflow'u tetikler.
Bu dosya görseli Telegram'dan indirir, ortak story motorunu çalıştırır ve
sonucu aynı sohbete gönderir. Tek dış bağımlılık Pillow'dur; HTTP çağrıları
standart kütüphaneyle yapılır.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image

# ``python -m strtg_asist.telegram_worker`` repo kökünden çalışır; doğrudan
# çalıştırma ve yerel test için kökü de sys.path'e ekle.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from strtg_asist.story_card import StoryCardError, create_social_card  # noqa: E402

TOKEN_PATTERN = re.compile(r"bot(\d+):[A-Za-z0-9_-]{15,}")
USER_AGENT = "strtg-asist-story-worker"

# Telegram/ağ kaynaklı geçici hatalarda kartı tamamen kaybetmemek için tekrar dene.
MAX_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 2.0
MAX_RETRY_AFTER_SECONDS = 30.0
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})

# Telegram sendPhoto sınırı 10 MB; büyük kartı foto olarak göndermeyi denemek yerine
# baştan anlamlı bir hata verelim.
TELEGRAM_PHOTO_LIMIT_BYTES = 10 * 1024 * 1024


class TelegramError(RuntimeError):
    """Telegram API'sinden dönen hata. ``retryable`` geçici hataları işaretler."""

    def __init__(self, message: str, *, retryable: bool = False, retry_after: float = 0.0):
        super().__init__(message)
        self.retryable = retryable
        self.retry_after = retry_after


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Eksik ortam değişkeni: {name}")
    return value


def _token() -> str:
    return _required("TELEGRAM_BOT_TOKEN")


def _chat_id() -> str:
    return _required("TELEGRAM_CHAT_ID")


def _scrub(value: object) -> str:
    """Token'ın hata mesajlarına ve Action loglarına sızmasını engeller."""
    text = str(value or "")
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if token:
        text = text.replace(token, "bot***")
    return TOKEN_PATTERN.sub(r"bot\1:***", text)


def _describe_http_error(exc: urllib.error.HTTPError) -> TelegramError:
    """Telegram'ın gövdedeki ``description`` alanını hata mesajına taşır.

    ``urlopen`` 4xx/5xx yanıtlarında HTTPError yükseltir ve gövdeyi okumazsak
    geriye yalnızca "HTTP Error 400: Bad Request" kalır; üretimde asıl sebebi
    ("caption is too long", "PHOTO_INVALID_DIMENSIONS" vb.) görmek imkânsızlaşır.
    """
    detail = ""
    retry_after = 0.0
    try:
        payload = json.loads(exc.read().decode("utf-8", "replace"))
        detail = str(payload.get("description") or "")
        retry_after = float(payload.get("parameters", {}).get("retry_after") or 0)
    except Exception:  # noqa: BLE001 - teşhis amaçlı, gövde okunamazsa sessiz geç
        detail = ""
    message = f"HTTP {exc.code}" + (f" — {detail}" if detail else "")
    return TelegramError(
        message,
        retryable=exc.code in RETRYABLE_STATUS,
        retry_after=min(retry_after, MAX_RETRY_AFTER_SECONDS),
    )


def _open(request: urllib.request.Request, timeout: int) -> bytes:
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        raise _describe_http_error(exc) from exc
    except urllib.error.URLError as exc:
        raise TelegramError(f"Ağ hatası: {_scrub(exc.reason)}", retryable=True) from exc
    except TimeoutError as exc:
        raise TelegramError("Telegram isteği zaman aşımına uğradı.", retryable=True) from exc


def _with_retries(label: str, call):
    """Geçici hatalarda ``call`` çağrısını sınırlı sayıda tekrarlar."""
    last: TelegramError | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return call()
        except TelegramError as exc:
            last = exc
            if not exc.retryable or attempt == MAX_ATTEMPTS:
                break
            delay = exc.retry_after or RETRY_BACKOFF_SECONDS * attempt
            print(
                f"[WARN] {label} başarısız ({_scrub(exc)}); {delay:.0f} sn sonra "
                f"{attempt + 1}/{MAX_ATTEMPTS}. deneme.",
                flush=True,
            )
            time.sleep(delay)
    raise RuntimeError(f"{label} başarısız: {_scrub(last)}")


def _api(method: str, params: dict | None = None) -> dict:
    def call() -> dict:
        request = urllib.request.Request(
            f"https://api.telegram.org/bot{_token()}/{method}",
            data=urllib.parse.urlencode(params or {}).encode("utf-8"),
            headers={"User-Agent": USER_AGENT},
        )
        result = json.loads(_open(request, timeout=60).decode("utf-8"))
        if not result.get("ok"):
            raise TelegramError(_scrub(result.get("description")))
        return result

    return _with_retries(f"Telegram {method} isteği", call)


def _send_message(text: str) -> None:
    _api("sendMessage", {"chat_id": _chat_id(), "text": text[:4096]})


def _download_file(file_id: str, destination: Path) -> None:
    result = _api("getFile", {"file_id": file_id})
    file_path = result.get("result", {}).get("file_path")
    if not file_path:
        raise RuntimeError("Telegram görsel yolu döndürmedi.")

    # file_path Telegram'dan geldiği için URL içinde ayrıca encode edilir.
    url = f"https://api.telegram.org/file/bot{_token()}/{urllib.parse.quote(file_path, safe='/')}"

    def call() -> None:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                with destination.open("wb") as output:
                    shutil.copyfileobj(response, output, length=1024 * 1024)
        except urllib.error.HTTPError as exc:
            raise _describe_http_error(exc) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise TelegramError(f"Ağ hatası: {_scrub(exc)}", retryable=True) from exc

    _with_retries("Görsel indirme", call)


def _send_photo(path: Path, caption: str) -> None:
    """requests kullanmadan Telegram sendPhoto multipart isteği gönderir."""
    size = path.stat().st_size
    if size > TELEGRAM_PHOTO_LIMIT_BYTES:
        raise RuntimeError(
            f"Story kartı {size / 1_048_576:.1f} MB; Telegram foto sınırı 10 MB. "
            "Daha küçük bir kaynak görselle tekrar dene."
        )

    boundary = "----strtgAsistBoundary7MA4YWxkTrZu0gW"
    body = bytearray()

    def field(name: str, value: str) -> None:
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        body.extend(value.encode("utf-8"))
        body.extend(b"\r\n")

    field("chat_id", _chat_id())
    field("caption", caption[:1024])
    body.extend(f"--{boundary}\r\n".encode())
    body.extend(b'Content-Disposition: form-data; name="photo"; filename="story_card.png"\r\n')
    body.extend(b"Content-Type: image/png\r\n\r\n")
    body.extend(path.read_bytes())
    body.extend(f"\r\n--{boundary}--\r\n".encode())
    payload = bytes(body)

    def call() -> None:
        request = urllib.request.Request(
            f"https://api.telegram.org/bot{_token()}/sendPhoto",
            data=payload,
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "User-Agent": USER_AGENT,
            },
        )
        result = json.loads(_open(request, timeout=120).decode("utf-8"))
        if not result.get("ok"):
            raise TelegramError(_scrub(result.get("description")))

    _with_retries("Story kartını gönderme", call)


def _validate_image(path: Path) -> None:
    """Dosyanın gerçekten açılabilir bir görsel olduğunu doğrular."""
    try:
        with Image.open(path) as image:
            image.verify()
    except Exception as exc:  # noqa: BLE001 - Pillow çok çeşitli hata tipi yükseltir
        raise RuntimeError(
            f"Gönderilen dosya geçerli bir görsel değil ({exc}). "
            "Telegram'da Fotoğraf olarak göndermeyi dene."
        ) from exc


def main() -> None:
    file_id = _required("TELEGRAM_FILE_ID")
    caption = os.environ.get("TELEGRAM_CAPTION", "").strip()
    if not caption:
        raise RuntimeError("Başlık ve alt metin içeren Telegram açıklaması boş.")

    with tempfile.TemporaryDirectory(prefix="strtg-story-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / "input_image"
        output = temp / "story_card.png"

        _send_message(
            "🎨 Story kartın hazırlanıyor...\n\n"
            "Görsel ve yazı yerleşimi düzenleniyor; bitince burada paylaşacağım."
        )
        _download_file(file_id, source)
        _validate_image(source)

        try:
            result = create_social_card(caption, str(source), str(output))
        except StoryCardError as exc:
            raise RuntimeError(str(exc)) from exc
        if result != str(output) or not output.is_file() or output.stat().st_size <= 0:
            raise RuntimeError("Story kartı üretilemedi.")

        _send_photo(
            output,
            "✅ Story kartın hazır!\n\nGörsele basılı tutup Fotoğraflara Kaydet diyebilirsin.",
        )
        print(f"Story card sent successfully ({output.stat().st_size} bytes).", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 - üst seviye hata kapanı
        safe_error = _scrub(exc)
        print(f"Story worker error: {safe_error}", file=sys.stderr, flush=True)
        try:
            _send_message(
                "❌ Story kartı hazırlanırken hata oluştu.\n\n"
                f"{safe_error[:1200]}\n\n"
                "Görseli ve açıklama biçimini kontrol edip tekrar deneyebilirsin."
            )
        except Exception as notify_exc:  # noqa: BLE001 - bildirim de başarısızsa log'a yaz
            print(f"Could not notify Telegram: {_scrub(notify_exc)}", file=sys.stderr)
        raise
