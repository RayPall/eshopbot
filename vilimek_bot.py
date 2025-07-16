import os
import io
import json
import re
import pdfplumber
import tiktoken
import pandas as pd
import streamlit as st
import openai

# ——— Streamlit UI ——————————————————————————————————————————————
st.set_page_config(page_title="PDF→Excel with GPT", layout="centered")
st.title("PDF → Structured Excel via OpenAI GPT")

# 1) API key
openai.api_key = (
    os.getenv("OPENAI_API_KEY")
    or st.text_input("OpenAI API key", type="password", help="Set env var OPENAI_API_KEY or paste here")
)

# 2) Universal file uploader
st.markdown("### 1️⃣ Nahrajte libovolné soubory (PDF katalogy, ceníky, obrázky…)")
uploaded_files = st.file_uploader(
    "Vyberte všechny relevantní soubory najednou",
    type=None,
    accept_multiple_files=True
)

# 3) Pokud jsou nahrané, požádejte o mapování rolí
catalog_file = None
price_file = None
if uploaded_files:
    names = [f.name for f in uploaded_files]
    st.markdown("### 2️⃣ Přiřaďte role souborům")
    catalog_choice = st.selectbox("Vyberte soubor s produktovým katalogem", options=["—"] + names)
    price_choice   = st.selectbox("Vyberte soubor s ceníkem",              options=["—"] + names)

    if catalog_choice != "—" and price_choice != "—":
        catalog_file = next(f for f in uploaded_files if f.name == catalog_choice)
        price_file   = next(f for f in uploaded_files if f.name == price_choice)

# 4) Spouštěcí tlačítko
if st.button("Generovat Excel"):

    # 4.1) Validace vstupů
    if not openai.api_key:
        st.error("Chybí API klíč OpenAI"); st.stop()
    if catalog_file is None:
        st.error("Musíte vybrat soubor s produktovým katalogem"); st.stop()
    if price_file   is None:
        st.error("Musíte vybrat soubor s ceníkem"); st.stop()

    # ——— 5) Extrakce textu z katalogu —————————————————————
    with st.spinner("Extrahuji text z katalogu…"):
        data = catalog_file.read()
        # předpokládejme PDF; pokud není PDF, raw text parse selže
        try:
            with pdfplumber.open(io.BytesIO(data)) as pdf:
                full_text = "\n\n".join(page.extract_text() or "" for page in pdf.pages)
        except Exception:
            # fallback: pokus o plain-text zbytek
            full_text = data.decode("utf-8", errors="ignore")

    # ——— 5.5) Izolace tabulkových řádků ————————————————————
    lines = full_text.splitlines()
    table_lines = [l for l in lines if re.match(r"^\d{2,3}x\d{2,3}", l) and "HLA" in l]
    header = next((l for l in lines if "Sizes" in l and "Pieces" in l), "")
    table_text = (header + "\n" + "\n".join(table_lines)) if header else "\n".join(table_lines)

    # ——— 6) Načtení ceníku ————————————————————————————
    with st.spinner("Načítám ceník…"):
        raw = price_file.getvalue().decode("utf-8", errors="ignore")
        cenik = {}
        for line in raw.splitlines():
            parts = [p.strip() for p in re.split(r"[;|\t|,]?", line) if "€" in line or line.count(" ")>1]
            # pokus najít klíč a cenu
            m = re.match(r"(.+?)\s+([\d.,]+)\s*€", line)
            if m:
                key, price = m.group(1).strip(), m.group(2).replace(",", ".")
                try:
                    cenik[key] = float(price)
                except:
                    pass

    if not cenik:
        st.warning("Ceník načten, ale neobsahuje žádné položky. Používám prázdné mapování.")
    else:
        st.write(f"Načteno {len(cenik)} položek z ceníku")

    cenik_json = json.dumps(cenik, ensure_ascii=False)

    # ——— 7) Helper pro chunking ——————————————————————————
    def chunk_text(text: str, max_tokens: int = 1500):
        enc = tiktoken.encoding_for_model("gpt-4")
        tokens = enc.encode(text)
        for i in range(0, len(tokens), max_tokens):
            yield enc.decode(tokens[i : i + max_tokens])

    # ——— 8) Prompt template ——————————————————————————
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
Now parse the following PDF text and output only valid JSON (no narrative, just the array):
{pdf_text_chunk}
```'''

    # ——— 9) Volání GPT a sběr výsledků —————————————————————
    products = []
    chunks = list(chunk_text(table_text))
    for idx, chunk in enumerate(chunks, start=1):
        with st.spinner(f"Volám GPT pro chunk {idx}/{len(chunks)}…"):
            prompt = base_prompt_template.format(
                cenik_json=cenik_json,
                pdf_text_chunk=chunk
            )
            resp = openai.chat.completions.create(
                model="gpt-4",
                messages=[{"role": "user", "content": prompt}],
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

    st.success(f"Extrahováno celkem {len(products)} produktů")

    # ——— 10) Sestavení DataFrame & export ————————————————————
    with st.spinner("Sestavuji Excel…"):
        df = pd.DataFrame(products)
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
