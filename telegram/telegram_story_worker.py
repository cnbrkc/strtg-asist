"""GitHub Actions içinde çalışan Telegram story kartı üreticisi.

Cloudflare Worker yalnızca Telegram güncellemesini alır ve workflow'u tetikler.
Bu dosya görseli Telegram'dan indirir, ortak story motorunu çalıştırır ve
sonucu aynı sohbete gönderir.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image

# ``python -m telegram.telegram_story_worker`` repo kökünden çalışır; doğrudan
# çalıştırma ve yerel test için kökü de sys.path'e ekle.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.story_card import create_social_card  # noqa: E402


TOKEN_PATTERN = re.compile(r"bot(\d+):[A-Za-z0-9_-]{15,}")


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


def _api(method: str, params: dict | None = None) -> dict:
    encoded = urllib.parse.urlencode(params or {}).encode("utf-8")
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{_token()}/{method}",
        data=encoded,
        headers={"User-Agent": "strtg-asist-story-worker"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            result = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise RuntimeError(f"Telegram {method} isteği başarısız: {_scrub(exc)}") from exc
    if not result.get("ok"):
        raise RuntimeError(f"Telegram {method} başarısız: {_scrub(result.get('description'))}")
    return result


def _send_message(text: str) -> None:
    _api("sendMessage", {"chat_id": _chat_id(), "text": text[:4096]})


def _download_file(file_id: str, destination: Path) -> None:
    result = _api("getFile", {"file_id": file_id})
    file_path = result.get("result", {}).get("file_path")
    if not file_path:
        raise RuntimeError("Telegram görsel yolu döndürmedi.")

    # file_path Telegram'dan geldiği için URL içinde ayrıca encode edilir.
    url = f"https://api.telegram.org/file/bot{_token()}/{urllib.parse.quote(file_path, safe='/')}"
    request = urllib.request.Request(url, headers={"User-Agent": "strtg-asist-story-worker"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response, destination.open("wb") as output:
            shutil.copyfileobj(response, output, length=1024 * 1024)
    except Exception as exc:
        raise RuntimeError(f"Görsel indirilemedi: {_scrub(exc)}") from exc


def _send_photo(path: Path, caption: str) -> None:
    """requests kullanmadan Telegram sendPhoto multipart isteği gönderir."""
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

    request = urllib.request.Request(
        f"https://api.telegram.org/bot{_token()}/sendPhoto",
        data=bytes(body),
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "User-Agent": "strtg-asist-story-worker",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            result = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise RuntimeError(f"Story kartı Telegram'a gönderilemedi: {_scrub(exc)}") from exc
    if not result.get("ok"):
        raise RuntimeError(f"Story kartı gönderilemedi: {_scrub(result.get('description'))}")


def _validate_image(path: Path) -> None:
    # PIL dosyanın gerçekten görsel olduğunu ve bozuk olmadığını doğrular.
    with Image.open(path) as image:
        image.verify()


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

        result = create_social_card(caption, str(source), str(output))
        if result != str(output) or not output.is_file() or output.stat().st_size <= 0:
            raise RuntimeError("Story kartı üretilemedi.")

        _send_photo(
            output,
            "✅ Story kartın hazır!\n\n"
            "Görsele basılı tutup Fotoğraflara Kaydet diyebilirsin.",
        )
        print(f"Story card sent successfully ({output.stat().st_size} bytes).", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        safe_error = _scrub(exc)
        print(f"Story worker error: {safe_error}", file=sys.stderr, flush=True)
        try:
            _send_message(
                "❌ Story kartı hazırlanırken hata oluştu.\n\n"
                f"{safe_error[:1200]}\n\n"
                "Görseli ve açıklama biçimini kontrol edip tekrar deneyebilirsin."
            )
        except Exception as notify_exc:
            print(f"Could not notify Telegram: {_scrub(notify_exc)}", file=sys.stderr)
        raise
