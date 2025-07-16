import os
import io
import json
import pdfplumber
import tiktoken
import pandas as pd
import streamlit as st
import openai

# ——— Streamlit UI ——————————————————————————————————————————————
st.set_page_config("PDF→Excel with GPT", "📄")
st.title("PDF → Structured Excel via OpenAI GPT")

# 1) API key
openai.api_key = os.getenv("OPENAI_API_KEY") or st.text_input(
    "OpenAI API key", type="password", help="Set env var OPENAI_API_KEY or paste here"
)

# 2) PDF uploader
pdf_file = st.file_uploader("Upload product PDF", type="pdf")
cenik_file = st.file_uploader("Upload ceník.txt", type="txt")

if st.button("Generate Excel"):

    if not openai.api_key:
        st.error("Missing OpenAI API key"); st.stop()
    if not pdf_file or not cenik_file:
        st.error("Please upload both PDF and ceník.txt"); st.stop()

    # ——— 1. Extract text from PDF ——————————————————————
    with pdfplumber.open(io.BytesIO(pdf_file.read())) as pdf:
        full_text = "\n\n".join(page.extract_text() or "" for page in pdf.pages)
    st.success("Extracted PDF text ({} chars)".format(len(full_text)))

    # ——— 2. Load and parse ceník.txt —————————————————————
    cenik = {}
    for line in cenik_file.getvalue().decode("utf-8").splitlines():
        parts = [p.strip() for p in line.split("€")]
        if len(parts)==2:
            key, price = parts
            cenik[key] = float(price)
    st.write("Parsed ceník entries:", len(cenik))

    # ——— 3. Chunking helper ——————————————————————————
    def chunk_text(text, max_tokens=1500):
        enc = tiktoken.encoding_for_model("gpt-4")
        tokens = enc.encode(text)
        for i in range(0, len(tokens), max_tokens):
            yield enc.decode(tokens[i : i + max_tokens])

    # ——— 4. Prompt template ——————————————————————————
    base_prompt = """
You are an expert at extracting structured data from product catalogs.
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
%s
Now parse the following PDF text and output only valid JSON:
%s
```"""  # will be formatted per chunk

    # ——— 5. Call GPT per chunk ————————————————————————
    products = []
    for chunk in chunk_text(full_text):
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
            st.error(f"JSON parse error: {e}\n{text}")
            st.stop()

    st.success(f"Extracted {len(products)} products")

    # ——— 6. Build DataFrame & fill missing prices ——————————
    df = pd.DataFrame(products)
    # fill price from ceník if missing
    df["P"] = df.apply(lambda row: row["P"] or cenik.get(row["C"], None), axis=1)

    # ——— 7. Download Excel ——————————————————————————
    bio = io.BytesIO()
    df.to_excel(bio, index=False, sheet_name="Products")
    st.download_button(
        "📥 Download Excel",
        bio.getvalue(),
        file_name="products.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
