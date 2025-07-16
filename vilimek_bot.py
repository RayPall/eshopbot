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
    type=None,
    accept_multiple_files=True
)

# 3) Spouštěcí tlačítko
if st.button("Generovat Excel"):

    if not openai.api_key:
        st.error("Chybí API klíč OpenAI"); st.stop()

    if not uploaded_files:
        st.error("Nenahráli jste žádné soubory"); st.stop()

    # Rozdělení souborů
    pdfs = [f for f in uploaded_files if f.name.lower().endswith(".pdf")]
    txts = [f for f in uploaded_files if f.name.lower().endswith(".txt")]

    if not pdfs:
        st.error("Chybí PDF soubor(y) s katalogem"); st.stop()
    if not txts:
        st.error("Chybí textový ceník (.txt)"); st.stop()

    pdf_file = pdfs[0]
    cenik_file = txts[0]

    # 4) Vlastní zpracování pod spinnerem
    with st.spinner("Extrahuji text z PDF…"):
        with pdfplumber.open(io.BytesIO(pdf_file.read())) as pdf:
            full_text = "\n\n".join(page.extract_text() or "" for page in pdf.pages)

    with st.spinner("Načítám ceník…"):
        cenik = {}
        for line in cenik_file.getvalue().decode("utf-8").splitlines():
            parts = [p.strip() for p in line.split("€")]
            if len(parts) == 2:
                key, price = parts
                try:
                    cenik[key] = float(price)
                except:
                    pass

    # Chunking & GPT volání
    def chunk_text(text, max_tokens=1500):
        enc = tiktoken.encoding_for_model("gpt-4")
        tokens = enc.encode(text)
        for i in range(0, len(tokens), max_tokens):
            yield enc.decode(tokens[i : i + max_tokens])

    base_prompt = """… (váš prompt jako dříve) …"""

    products = []
    for chunk in chunk_text(full_text):
        with st.spinner("Volám GPT pro další část…"):
            prompt = base_prompt % (json.dumps(cenik, ensure_ascii=False), chunk)
            resp = openai.ChatCompletion.create(
                model="gpt-4",
                messages=[{"role":"user","content": prompt}],
                temperature=0,
                max_tokens=2000,
            )
        text = resp.choices[0].message.content.strip()
        try:
            data = json.loads(text)
            products.extend(data)
        except Exception as e:
            st.error(f"Chyba parsování JSON: {e}")
            st.stop()

    with st.spinner("Sestavuji Excel…"):
        df = pd.DataFrame(products)
        df["P"] = df.apply(lambda row: row["P"] or cenik.get(row["C"], None), axis=1)
        bio = io.BytesIO()
        df.to_excel(bio, index=False, sheet_name="Products")

    st.success(f"Hotovo! Vygenerováno {len(products)} produktů.")
    st.download_button(
        "📥 Stáhnout Excel",
        bio.getvalue(),
        file_name="products.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
