import os
import io
import re
import json
import PyPDF2               # pip install PyPDF2
import pdfplumber          # pip install pdfplumber
import pandas as pd        # pip install pandas
import streamlit as st     # pip install streamlit
import openai              # pip install openai
import xml.etree.ElementTree as ET
from xml.dom import minidom

st.set_page_config(page_title="Smart PDF→Heureka XML", layout="wide")
st.title("🤖 Smart PDF → Heureka XML Exporter")

# ——— 1) Read API key from environment —————————————————————
openai.api_key = os.getenv("OPENAI_API_KEY")
if not openai.api_key:
    st.error("Chybí OPENAI_API_KEY v prostředí. Přidejte jej do Streamlit Secrets.")
    st.stop()

# Helper to pull JSON array out of GPT’s free-form reply
def extract_json_array(text: str) -> str:
    start = text.find('[')
    if start == -1:
        raise ValueError("No '[' found in GPT response")
    depth = 0
    for idx in range(start, len(text)):
        if text[idx] == '[':
            depth += 1
        elif text[idx] == ']':
            depth -= 1
            if depth == 0:
                return text[start:idx+1]
    raise ValueError("No matching ']' found in GPT response")

# ——— 2) File uploader ————————————————————————————————————
uploaded = st.file_uploader(
    "📁 Nahrajte PDF katalogy, ceníky (.txt/.csv/.xlsx) a XML šablonu",
    type=["pdf","txt","csv","xlsx","xml"],
    accept_multiple_files=True
)
if not uploaded:
    st.stop()

pdfs       = [f for f in uploaded if f.name.lower().endswith(".pdf")]
prices_txt = [f for f in uploaded if f.name.lower().endswith((".txt","csv"))]
prices_xlsx= [f for f in uploaded if f.name.lower().endswith(".xlsx")]
templates  = [f for f in uploaded if f.name.lower().endswith(".xml")]

st.write(f"- 📑 PDF katalogů: {len(pdfs)}")
st.write(f"- 💲 Ceníků (.txt/.csv): {len(prices_txt)}")
st.write(f"- 💲 Ceníků (.xlsx): {len(prices_xlsx)}")
st.write(f"- 📄 XML šablon: {len(templates)}")

template_file = None
if templates:
    choice = st.selectbox("Vyberte XML šablonu", ["–"]+[t.name for t in templates])
    if choice != "–":
        template_file = next(t for t in templates if t.name == choice)

# ——— 3) Main button —————————————————————————————————————
if st.button("🚀 Generovat XML"):
    # validations
    if not pdfs:
        st.error("Potřebujete alespoň 1 PDF."); st.stop()
    if not (prices_txt or prices_xlsx):
        st.error("Potřebujete alespoň 1 ceník."); st.stop()
    if not template_file:
        st.error("Potřebujete vybrat XML šablonu."); st.stop()

    # ——— 4) Build price_map ——————————————————————————
    price_map = {}
    for pf in prices_txt:
        txt = pf.getvalue().decode("utf-8", errors="ignore")
        for line in txt.splitlines():
            m = re.match(r"(.+?)\s+([\d.,]+)\s*€", line)
            if m:
                price_map[m.group(1).strip()] = float(m.group(2).replace(",","."))
    for xf in prices_xlsx:
        try:
            dfp = pd.read_excel(xf)
            key_col, price_col = dfp.columns[:2]
            for _, r in dfp.iterrows():
                k, v = str(r[key_col]).strip(), r[price_col]
                try:
                    price_map[k] = float(v)
                except:
                    pass
        except Exception as e:
            st.warning(f"Chyba při čtení {xf.name}: {e}")

    if not price_map:
        # fallback hard-coded
        price_map = {
            "60x120 - Rettificato": 14.5,
            "120x120 - Rettificato": 19.0,
            # … další podle potřeby …
        }
        st.warning("Používám hard-coded ceník.")

    st.success(f"Načteno {len(price_map)} cenových položek.")

    # ——— 5) Load and clear XML template ——————————————————
    tree = ET.parse(io.BytesIO(template_file.getvalue()))
    root = tree.getroot()
    ns = {"h": root.tag.split("}")[0].strip("{")}
    for old in root.findall("h:SHOPITEM", ns):
        root.remove(old)

    total = 0
    # ——— 6) Process each PDF with GPT —————————————————————
    for pdf in pdfs:
        # extract text via PyPDF2
        reader = PyPDF2.PdfReader(io.BytesIO(pdf.getvalue()))
        text = "".join(p.extract_text() or "" for p in reader.pages)

        # prepare prompt
        schema = {
            "ITEM_ID":"string",
            "PRODUCTNAME":"string",
            "DESCRIPTION":"string",
            "CATEGORIES":"string",
            "NETTO_PRICE":"number",
            "WEIGHT":"number",
            "WIDTH":"number",
            "HEIGHT":"number",
            "THICKNESS":"number",
            "MAIN_IMAGE_URL":"string",
            "ADDITIONAL_IMAGE_URLS":["string"],
            "PARAMS":"object"
        }
        prompt = f'''You are an expert at extracting product data from catalogs.
Extract every product into a JSON array matching this schema:
{json.dumps(schema, ensure_ascii=False, indent=2)}

Use this price_map for NETTO_PRICE (key→price):
{json.dumps(price_map, ensure_ascii=False)}

Catalog filename: {pdf.name}
Catalog text excerpt (first 2000 chars):
{text[:2000]}

Return ONLY a valid JSON array.'''

        resp = openai.chat.completions.create(
            model="gpt-4",
            messages=[{"role":"user","content":prompt}],
            temperature=0
        )
        raw = resp.choices[0].message.content
        try:
            arr = extract_json_array(raw)
            products = json.loads(arr)
        except Exception as e:
            st.error(f"Chyba parsování JSON od GPT: {e}")
            st.code(raw)
            st.stop()

        # inject into XML
        for it in products:
            itm = ET.SubElement(root, f"{{{ns['h']}}}SHOPITEM")
            def add(tag,val):
                el = ET.SubElement(itm, f"{{{ns['h']}}}{tag}")
                el.text = str(val)
            add("ITEM_ID", it.get("ITEM_ID",""))
            add("PRODUCTNAME", it.get("PRODUCTNAME",""))
            add("DESCRIPTION", it.get("DESCRIPTION",""))
            add("CATEGORIES", it.get("CATEGORIES",""))
            add("NETTO_PRICE", it.get("NETTO_PRICE",""))
            add("WEIGHT", it.get("WEIGHT",""))
            add("WIDTH", it.get("WIDTH",""))
            add("HEIGHT", it.get("HEIGHT",""))
            add("THICKNESS", it.get("THICKNESS",""))
            add("MAIN_IMAGE_URL", it.get("MAIN_IMAGE_URL",""))
            for url in it.get("ADDITIONAL_IMAGE_URLS",[]):
                add("ADDITIONAL_IMAGE_URL", url)
            for k,v in it.get("PARAMS",{}).items():
                p = ET.SubElement(itm, f"{{{ns['h']}}}PARAM")
                ET.SubElement(p, f"{{{ns['h']}}}PARAM_NAME").text = k
                ET.SubElement(p, f"{{{ns['h']}}}VAL").text        = str(v)
            total += 1

    st.success(f"✨ Vygenerováno {total} položek do XML.")

    # ——— 7) Pretty-print & download —————————————————————
    rough = ET.tostring(root, "utf-8")
    pretty = minidom.parseString(rough).toprettyxml(indent="  ", encoding="UTF-8")
    st.download_button(
        "📥 Stáhnout výsledné XML",
        data=pretty,
        file_name="export.xml",
        mime="application/xml"
    )
