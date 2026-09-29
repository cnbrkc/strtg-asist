"""STRtg Asist — 1080x1920 Telegram/Streamlit story kartı üretim paketi.

Paket adı bilerek ``telegram`` değildir: üst seviyede ``telegram`` adlı bir paket,
PyPI'daki ``python-telegram-bot`` kütüphanesinin ``telegram`` modülünü gölgeler ve
ileride eklenecek bir bağımlılıkta import hatasına yol açar.

Modüller:
    ``strtg_asist.story_card``      — Streamlit'ten bağımsız saf üretim motoru.
    ``strtg_asist.telegram_worker`` — GitHub Actions içinde çalışan Telegram köprüsü.
"""

from strtg_asist.story_card import StoryCardError, create_social_card

__all__ = ["StoryCardError", "create_social_card"]
