import os
import io
import json
import pdfplumber
import tiktoken
import pandas as pd
import streamlit as st
import openai

st.set_page_config("PDF→Excel with GPT", "📄")
st.title("PDF → Structured Excel via OpenAI GPT")

# 1) API key
openai.api_key = os.getenv("OPENAI_API_KEY") or st.text_input(
    "OpenAI API key", type="password", help="Set env var OPENAI_API_KEY or paste here"
)

# 2) Universal file uploader
st.markdown("### 1️⃣ Nahrajte vstupní soubory (PDF, ceník, nebo jiné)")
uploaded_files = st.file_uploader(
    "Vyberte všechny soubory najednou",
    type=None,  # žádné omezení typů
    accept_multiple_files=True
)

if st.button("Generovat Excel"):

    if not openai.api_key:
        st.error("Chybí API klíč OpenAI"); st.stop()

    if not uploaded_files:
        st.error("Nenahráli jste žádné soubory"); st.stop()

    # 3) Roztřídění souborů podle přípony
    pdfs = [f for f in uploaded_files if f.name.lower().endswith(".pdf")]
    txts = [f for f in uploaded_files if f.name.lower().endswith(".txt")]

    if not pdfs:
        st.error("Chybí PDF soubor(y) s katalogem"); st.stop()
    if not txts:
        st.error("Chybí textový ceník (.txt)"); st.stop()

    pdf_file = pdfs[0]        # vezmeme první PDF
    cenik_file = txts[0]      # a první .txt jako ceník

    # … pokračuje zbytek kódu beze změny …
