import os
import io
import re
import json
import PyPDF2               # pip install PyPDF2
import pdfplumber         # pip install pdfplumber
import pandas as pd       # pip install pandas
import streamlit as st    # pip install streamlit
import openai             # pip install openai
import xml.etree.ElementTree as ET
from xml.dom import minidom

st.set_page_config(page_title="Smart PDF→Heureka XML", layout="wide")
st.title("🤖 Smart PDF → Heureka XML Exporter")

# ——— 1) Read API key from environment —————————————————————
openai.api_key = os.getenv("OPENAI_API_KEY")
if not openai.api_key:
    st.error("Chybí OPENAI_API_KEY v prostředí. Přidejte jej do Streamlit Secrets.")
    st.stop()

# ——— 2) File uploader: include .xlsx —————————————————————
uploaded = st.file_uploader(
    "📁 Nahrajte PDF katalogy, ceníky (.txt/.csv/.xlsx) a XML šablonu",
    type=["pdf", "txt", "csv", "xlsx", "xml"],
    accept_multiple_files=True
)
if not uploaded:
    st.stop()

# Separate by extension
pdfs      = [f for f in uploaded if f.name.lower().endswith(".pdf")]
prices_txt = [f for f in uploaded if f.name.lower().endswith((".txt","csv"))]
prices_xlsx = [f for f in uploaded if f.name.lower().endswith(".xlsx")]
templates = [f for f in uploaded if f.name.lower().endswith(".xml")]

st.write(f"- 📑 PDF katalogů: {len(pdfs)}")
st.write(f"- 💲 Ceníků (.txt/.csv): {len(prices_txt)}")
st.write(f"- 💲 Ceníků (.xlsx): {len(prices_xlsx)}")
st.write(f"- 📄 XML šablon: {len(templates)}")

# Choose one XML template
template_file = None
if templates:
    choice = st.selectbox("Vyberte pevnou XML šablonu", ["–"] + [t.name for t in templates])
    if choice != "–":
        template_file = next(t for t in templates if t.name == choice)

if st.button("🚀 Generovat XML"):
    # Validation
    if not pdfs:
        st.error("Musíte nahrát alespoň jeden PDF katalog.")
        st.stop()
    if not (prices_txt or prices_xlsx):
        st.error("Musíte nahrát alespoň jeden ceník (.txt/.csv/.xlsx).")
        st.stop()
    if not template_file:
        st.error("Musíte vybrat jednu XML šablonu.")
        st.stop()

    # ——— 3) Build price_map from .txt/.csv —————————————————
    price_map = {}
    for pf in prices_txt:
        txt = pf.getvalue().decode("utf-8", errors="ignore")
        for line in txt.splitlines():
            m = re.match(r"(.+?)\s+([\d.,]+)\s*€", line)
            if m:
                price_map[m.group(1).strip()] = float(m.group(2).replace(",","."))
    # ——— 3b) Also parse .xlsx price-lists —————————————————
    for xf in prices_xlsx:
        try:
            df_price = pd.read_excel(xf)
            # assume columns "Key" and "Price" or adjust as needed:
            # you might need to examine the first two columns
            cols = df_price.columns.tolist()
            key_col, price_col = cols[0], cols[1]
            for _, row in df_price.iterrows():
                k = str(row[key_col]).strip()
                v = row[price_col]
                try:
                    price_map[k] = float(v)
                except:
                    pass
        except Exception as e:
            st.warning(f"Chyba při čtení {xf.name}: {e}")

    # Fallback to hard-coded map if none uploaded
    if not price_map:
        price_map = {
            "LAVAREDO | HLA \t120x120 - Rettificato\tMQ": 19.0,
            "60x120 - Rettificato\tMQ": 14.5,
            "60x120 -  Grip Rettificato\tMQ": 15.5,
            "60x120 - Framework Rettificato\tMQ": 23.0,
            "80x80 - Rettificato\tMQ": 15.0,
            "60x60 - Rettificato \tMQ": 12.25,
            "30x60 - Rettificato\tMQ": 11.5,
            "20x40 - Grip\tMQ": 11.25,
            "20x20 - Grip\tMQ": 11.25,
            "30x30 - Mosaico\tMQ": 49.0,
            "30x60 - Stonemix\tMQ": 35.5,
            "7,5x60 - Battiscopa Rettificato\tML": 8.0,
            "7x80 - Battiscopa Rettificato\tML": 8.0,
            "7x120 - Battiscopa Rettificato\tML": 8.75,
            "10x40 - Battiscopa\tML": 5.5,
            "16,5x30 - Elemento a L Monolitico\tML": 21.5,
            "33x60 - Gradone Lineare Rettificato\tPC": 31.0,
            "33x33 - Gradone Angolare Rettificato\tPC": 36.5,
            "33x120 - Gradone Lineare Rettificato\tPC": 83.5,
            "33x120 - Gradone Angolare Rettificato DX-SX\tPC": 96.5
        }
        st.warning("Používám hard-coded ceník z promptu.")

    st.success(f"Načteno {len(price_map)} cenových položek.")

    # ——— 4) Load XML template ——————————————————————————
    tree = ET.parse(io.BytesIO(template_file.getvalue()))
    root = tree.getroot()
    ns = {"h": root.tag.split("}")[0].strip("{")}
    for old in root.findall("h:SHOPITEM", ns):
        root.remove(old)

    total = 0
    # ——— 5) Process each PDF with GPT —————————————————————
    for pdf in pdfs:
        # Extract text via PyPDF2
        reader = PyPDF2.PdfReader(io.BytesIO(pdf.getvalue()))
        text = ""
        for page in reader.pages:
            text += page.extract_text() or ""

        # Build prompt schema
        schema = {
            "ITEM_ID": "string",
            "PRODUCTNAME": "string",
            "DESCRIPTION": "string",
            "CATEGORIES": "string",
            "NETTO_PRICE": "number",
            "WEIGHT": "number",
            "WIDTH": "number",
            "HEIGHT": "number",
            "THICKNESS": "number",
            "MAIN_IMAGE_URL": "string (URL)",
            "ADDITIONAL_IMAGE_URLS": ["string"],
            "PARAMS": "object"
        }
prompt = f"""
You are an expert at extracting product data from catalogs.
Extract *every* product into a JSON array matching this schema:

{json.dumps(schema, indent=2, ensure_ascii=False)}

Use this price map for NETTO_PRICE (key→price):
```json
{json.dumps(price_map, ensure_ascii=False)}
Catalog filename: {pdf.name}
Catalog text excerpt: {text[:2000]}
 Return ONLY a valid JSON array."""
        resp = openai.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "user", "content": prompt}],
        temperature=0
    )
    try:
        products = json.loads(resp.choices[0].message.content)
    except Exception as e:
        st.error(f"Chyba parsování JSON od GPT: {e}")
        st.code(resp.choices[0].message.content)
        st.stop()

    # Inject each product into XML
    for it in products:
        itm = ET.SubElement(root, f"{{{ns['h']}}}SHOPITEM")
        def add(tag, val):
            e = ET.SubElement(itm, f"{{{ns['h']}}}{tag}")
            e.text = str(val)
        add("ITEM_ID", it.get("ITEM_ID", ""))
        add("PRODUCTNAME", it.get("PRODUCTNAME", ""))
        add("DESCRIPTION", it.get("DESCRIPTION", ""))
        add("CATEGORIES", it.get("CATEGORIES", ""))
        add("NETTO_PRICE", it.get("NETTO_PRICE", ""))
        add("WEIGHT", it.get("WEIGHT", ""))
        add("WIDTH", it.get("WIDTH", ""))
        add("HEIGHT", it.get("HEIGHT", ""))
        add("THICKNESS", it.get("THICKNESS", ""))
        add("MAIN_IMAGE_URL", it.get("MAIN_IMAGE_URL", ""))
        for url in it.get("ADDITIONAL_IMAGE_URLS", []):
            add("ADDITIONAL_IMAGE_URL", url)
        for k, v in it.get("PARAMS", {}).items():
            p = ET.SubElement(itm, f"{{{ns['h']}}}PARAM")
            ET.SubElement(p, f"{{{ns['h']}}}PARAM_NAME").text = k
            ET.SubElement(p, f"{{{ns['h']}}}VAL").text        = str(v)
        total += 1

st.success(f"✨ Vygenerováno {total} položek do XML.")

# ——— 6) Pretty-print & download —————————————————————
rough = ET.tostring(root, "utf-8")
pretty = minidom.parseString(rough).toprettyxml(indent="  ", encoding="UTF-8")
st.download_button(
    "📥 Stáhnout výsledné XML",
    data=pretty,
    file_name="export.xml",
    mime="application/xml"
)
