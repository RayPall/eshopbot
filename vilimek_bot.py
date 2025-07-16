import os
import io
import json
import pdfplumber
import tiktoken
import pandas as pd
import streamlit as st
import openai

# Streamlit config
st.set_page_config(page_title="PDF→Excel with GPT", layout="centered")
st.title("PDF → Structured Excel via OpenAI GPT")

# 1) API key input
openai.api_key = (
    os.getenv("OPENAI_API_KEY")
    or st.text_input("OpenAI API key", type="password", help="Set env var OPENAI_API_KEY or paste here")
)

# 2) Universal file uploader
st.markdown("### 1️⃣ Nahrajte vstupní soubory (PDF, ceník, nebo jiné)")
uploaded_files = st.file_uploader(
    "Vyberte všechny soubory najednou",
    type=None,
    accept_multiple_files=True
)

# 3) Start button
if st.button("Generovat Excel"):

    # Validate inputs
    if not openai.api_key:
        st.error("Chybí API klíč OpenAI"); st.stop()
    if not uploaded_files:
        st.error("Nenahráli jste žádné soubory"); st.stop()

    # Separate PDF and TXT
    pdfs = [f for f in uploaded_files if f.name.lower().endswith(".pdf")]
    txts = [f for f in uploaded_files if f.name.lower().endswith(".txt")]
    if not pdfs:
        st.error("Chybí PDF soubor(y)"); st.stop()
    if not txts:
        st.error("Chybí textový ceník (.txt)"); st.stop()

    pdf_file = pdfs[0]
    cenik_file = txts[0]
# 4) Extract full text from PDF
    with st.spinner("Extrahuji text z PDF…"):
        pdf_bytes = pdf_file.read()
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            full_text = "\n\n".join(page.extract_text() or "" for page in pdf.pages)

# 5) Load ceník
    with st.spinner("Načítám ceník…"):
        cenik = {}
        for line in cenik_file.getvalue().decode("utf-8").splitlines():
            parts = [p.strip() for p in line.split("€")]
            if len(parts) == 2:
                key, price_str = parts
                try:
                    cenik[key] = float(price_str)
                except ValueError:
                    pass
    st.write(f"Nahráno {len(cenik)} cenových záznamů")

# 6) Chunking helper
    def chunk_text(text, max_tokens=1500):
        enc = tiktoken.encoding_for_model("gpt-4")
        tokens = enc.encode(text)
        for i in range(0, len(tokens), max_tokens):
            yield enc.decode(tokens[i:i+max_tokens])

 # 7) Prompt template
    base_prompt_template = '''You are an expert at extracting structured data from product catalogs.
Generate a JSON array of all products with exactly these columns (A–U) in Czech:

A: Název Keramičky  
B: Název kolekce  
C: Produktový kód  
D: Název produktu  
E: Barva  
F: Materiál - Rektifikovaný (0/1)  
G: Povrch (Matný/Lesklý)  
H: Hlavní obrázek (valid URL)  
I: Váha (kg)  
J: Šířka  
K: Výška  
L: Tloušťka  
M: Specifikace (Protiskluz R9–R12)  
N: Tvar  
O: Estetický vzhled  
P: Cena (EUR, from ceník)  
Q: Materiál (typ střepu)  
R: Použití  
S: Hlavní kategorie  
T: Jednotka  
U: Velikost balení

Use the following ceník mapping (key→price):
```json
{cenik_json}
{pdf_text_chunk}
```'''
# 8) Call GPT per chunk
    products = []
    cenik_json = json.dumps(cenik, ensure_ascii=False)
    chunks = list(chunk_text(full_text))
    for idx, chunk in enumerate(chunks, 1):
        with st.spinner(f"Volám GPT pro chunk {idx}/{len(chunks)}…"):
            prompt = base_prompt_template.format(
                cenik_json=cenik_json,
                pdf_text_chunk=chunk
            )
            resp = openai.ChatCompletion.create(
                model="gpt-4",
                messages=[{"role":"user","content":prompt}],
                temperature=0,
                max_tokens=2000,
            )
        text = resp.choices[0].message.content.strip()
        try:
            data = json.loads(text)
            products.extend(data)
        except json.JSONDecodeError as e:
            st.error(f"Chyba JSON v chunku {idx}: {e}")
            st.code(text)
            st.stop()
    st.success(f"Extrahováno {len(products)} produktů")
# 9) Build DataFrame & Excel
    with st.spinner("Sestavuji Excel…"):
        df = pd.DataFrame(products)
        # fill missing prices
        df["P"] = df.apply(lambda r: r.get("P") or cenik.get(r.get("C")), axis=1)
        out = io.BytesIO()
        df.to_excel(out, index=False, sheet_name="Products")

    st.success("Hotovo! Excel je připraven.")
    st.download_button(
        "📥 Stáhnout Excel",
        out.getvalue(),
        file_name="products.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
