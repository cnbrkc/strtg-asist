"""Yerel Streamlit arayüzü.

Telegram üretimi için kullanılan saf motor ``strtg_asist.story_card`` içindedir.
Bu sayfa, eski str-asist kullanımını korumak isteyenler için isteğe bağlıdır.
"""
from __future__ import annotations

import base64
import tempfile
from pathlib import Path

import streamlit as st

from strtg_asist.story_card import StoryCardError, create_social_card

st.set_page_config(page_title="Story Asistanım", page_icon="📸", layout="centered")
st.title("📸 Story Asistanım")
st.markdown("Fotoğrafı yükle, metinleri yaz, saniyeler içinde story kartını indir!")

col1, col2 = st.columns(2)
with col1:
    title_text = st.text_input(
        "📝 Başlık (Marka / Model / Konu)",
        value="",
        placeholder="Örn: DAYANIKLILIĞIN ADI: TOYOTA COROLLA!",
    )
with col2:
    body_text = st.text_area(
        "📄 Alt Metin (Fiyat / Detay)",
        value="",
        placeholder="Örn: Sadece bu hafta geçerlidir! Fiyat: 1.250.000 TL",
        height=150,
    )

uploaded_file = st.file_uploader(
    "⬆️ Araç/Haber Görselini Yükle",
    type=["jpg", "jpeg", "png", "webp"],
)

if st.button("🎨 Şablonu Oluştur", type="primary", use_container_width=True):
    if uploaded_file is None:
        st.warning("Lütfen bir görsel yükleyin!")
    elif not title_text.strip():
        # Başlık boşsa motor alt metnin ilk satırını başlık sayıp büyük harfe
        # çevirirdi; kullanıcı ne olduğunu anlamadan yanlış kart alıyordu.
        st.warning("Lütfen başlık alanını doldurun. İlk satır her zaman başlıktır.")
    else:
        with st.spinner("Şablon hazırlanıyor..."):
            # TemporaryDirectory: her üretimde /tmp altında dizin biriktirmeyi önler.
            with tempfile.TemporaryDirectory(prefix="strtg-") as temp_dir:
                input_path = Path(temp_dir) / "input_img.png"
                output_path = Path(temp_dir) / "story_card.png"
                input_path.write_bytes(uploaded_file.getbuffer())

                try:
                    create_social_card(
                        f"{title_text}\n{body_text}", str(input_path), str(output_path)
                    )
                    card_bytes = output_path.read_bytes()
                except (StoryCardError, OSError) as exc:
                    st.error(f"Şablon oluşturulamadı: {exc}")
                else:
                    st.success("Şablon başarıyla oluşturuldu!")
                    b64 = base64.b64encode(card_bytes).decode()
                    st.markdown(
                        f'<img src="data:image/png;base64,{b64}" '
                        'style="width:100%; border-radius:15px; '
                        'box-shadow:0 4px 15px rgba(0,0,0,0.5);" alt="Story Kart">',
                        unsafe_allow_html=True,
                    )
                    st.download_button(
                        "⬇️ Story kartını indir",
                        data=card_bytes,
                        file_name="story_card.png",
                        mime="image/png",
                    )
