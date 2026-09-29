from pathlib import Path

from PIL import Image

from core.story_card import _prepare_text, create_social_card


def test_prepare_text_uses_turkish_uppercase_rules():
    title, body = _prepare_text("dayanıklılığın adı: toyota\nFiyat: 1.250.000 TL")

    assert title == "DAYANIKLILIĞIN ADI: TOYOTA"
    assert body == "Fiyat: 1.250.000 TL"


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
