"""Yerel Streamlit arayüzü.

Telegram üretimi için kullanılan saf motor ``core.story_card`` içindedir. Bu
sayfa, eski str-asist kullanımını korumak isteyenler için isteğe bağlıdır.
"""
import base64
import os
import tempfile

import streamlit as st

from core.story_card import create_social_card


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
    else:
        with st.spinner("Şablon hazırlanıyor..."):
            temp_dir = tempfile.mkdtemp(prefix="strtg-")
            input_path = os.path.join(temp_dir, "input_img.png")
            output_path = os.path.join(temp_dir, "story_card.png")
            with open(input_path, "wb") as output:
                output.write(uploaded_file.getbuffer())

            result_path = create_social_card(
                f"{title_text}\n{body_text}", input_path, output_path
            )
            if result_path == output_path and os.path.exists(result_path):
                st.success("Şablon başarıyla oluşturuldu!")
                with open(result_path, "rb") as output:
                    b64 = base64.b64encode(output.read()).decode()
                st.markdown(
                    f'<img src="data:image/png;base64,{b64}" '
                    'style="width:100%; border-radius:15px; '
                    'box-shadow:0 4px 15px rgba(0,0,0,0.5);" alt="Story Kart">',
                    unsafe_allow_html=True,
                )
                with open(result_path, "rb") as output:
                    st.download_button(
                        "⬇️ Story kartını indir",
                        data=output,
                        file_name="story_card.png",
                        mime="image/png",
                    )
            else:
                st.error("Şablon oluşturulamadı. Konsoldaki log'a bak.")
