from pathlib import Path

import pytest
from PIL import Image

from strtg_asist.story_card import (
    StoryCardError,
    _prepare_text,
    _wrap_text,
    create_social_card,
)


def test_prepare_text_uses_turkish_uppercase_rules():
    title, body = _prepare_text("dayanıklılığın adı: toyota\nFiyat: 1.250.000 TL")

    assert title == "DAYANIKLILIĞIN ADI: TOYOTA"
    assert body == "Fiyat: 1.250.000 TL"


def test_prepare_text_keeps_every_body_line():
    _, body = _prepare_text("BAŞLIK\nBirinci satır\nİkinci satır\n\nÜçüncü satır")

    assert body == "Birinci satır\nİkinci satır\nÜçüncü satır"


def test_wrap_text_preserves_author_line_breaks():
    from PIL import ImageDraw

    from strtg_asist.story_card import _get_font

    draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    lines = _wrap_text(draw, "Satır bir\nSatır iki\nSatır üç", _get_font(42), 960)

    assert lines == ["Satır bir", "Satır iki", "Satır üç"]


def test_create_social_card_matches_story_dimensions(tmp_path: Path):
    source = tmp_path / "source.jpg"
    output = tmp_path / "story_card.png"
    Image.new("RGB", (1600, 900), (36, 92, 150)).save(source)

    result = create_social_card(
        "DAYANIKLILIĞIN ADI: TOYOTA\nSadece bu hafta geçerlidir! Fiyat: 1.250.000 TL",
        str(source),
        str(output),
    )

    assert result == str(output)
    assert output.exists()
    with Image.open(output) as image:
        assert image.size == (1080, 1920)
        assert image.mode == "RGB"


def test_create_social_card_also_works_without_source_image(tmp_path: Path):
    output = tmp_path / "text_only.png"

    result = create_social_card("SADECE BAŞLIK", "", str(output))

    assert result == str(output)
    assert output.exists()
    with Image.open(output) as image:
        assert image.size == (1080, 1920)


def test_create_social_card_survives_oversized_caption(tmp_path: Path):
    """Telegram caption sınırının tamamı kullanıldığında kart hâlâ üretilebilmeli."""
    source = tmp_path / "source.jpg"
    output = tmp_path / "long.png"
    Image.new("RGB", (900, 1600), (10, 40, 90)).save(source)

    caption = "ÇOK UZUN BAŞLIK " * 6 + "\n" + ("Uzun alt metin detayı. " * 40)
    result = create_social_card(caption[:1024], str(source), str(output))

    assert result == str(output)
    with Image.open(output) as image:
        assert image.size == (1080, 1920)


def test_create_social_card_raises_instead_of_returning_input_path(tmp_path: Path):
    """Hata durumunda girdi yolunu sessizce döndürmek teşhisi imkânsızlaştırıyordu."""
    unwritable = tmp_path / "missing-dir" / "card.png"

    with pytest.raises(StoryCardError):
        create_social_card("BAŞLIK\nAlt metin", "", str(unwritable))
