import os
import io
import re
import json
import PyPDF2
import streamlit as st
import openai
import xml.etree.ElementTree as ET
from xml.dom import minidom

st.set_page_config(page_title="Smart PDF→Heureka XML", layout="wide")
st.title("🤖 Smart PDF → Heureka XML Exporter")

# 1) Read API key from environment
openai.api_key = os.getenv("OPENAI_API_KEY")
if not openai.api_key:
    st.error("Chybí OPENAI_API_KEY v prostředí.")
    st.stop()

# 2) Upload files
uploaded = st.file_uploader(
    "Nahrajte PDF katalogy, ceník (.txt/.csv) a XML šablonu",
    type=["pdf","txt","csv","xml"],
    accept_multiple_files=True
)
if not uploaded:
    st.stop()

pdfs      = [f for f in uploaded if f.name.lower().endswith(".pdf")]
prices    = [f for f in uploaded if f.name.lower().endswith((".txt","csv"))]
templates = [f for f in uploaded if f.name.lower().endswith(".xml")]

template = None
if templates:
    pick = st.selectbox("Vyberte XML šablonu", ["–"] + [t.name for t in templates])
    if pick != "–":
        template = next(t for t in templates if t.name == pick)

if st.button("🚀 Generovat XML"):
    if not pdfs or not template:
        st.error("Potřebujete alespoň 1 PDF a 1 XML šablonu."); st.stop()

    # 3) Build price_map
    price_map = {}
    for pf in prices:
        txt = pf.getvalue().decode("utf-8", errors="ignore")
        for L in txt.splitlines():
            m = re.match(r"(.+?)\s+([\d.,]+)\s*€", L)
            if m:
                price_map[m.group(1).strip()] = float(m.group(2).replace(",","."))
    # fallback to your hard‐coded map if none uploaded
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
        st.warning("Používám hard‐coded ceník z promptu.")

    st.success(f"Ceny: {len(price_map)} položek")

    # 4) Load XML template
    tree = ET.parse(io.BytesIO(template.getvalue()))
    root = tree.getroot()
    ns = {"h": root.tag.split("}")[0].strip("{")}
    for old in root.findall("h:SHOPITEM", ns):
        root.remove(old)

    total = 0
    # 5) Process each PDF
    for pdf in pdfs:
        # extract text via PyPDF2
        reader = PyPDF2.PdfReader(io.BytesIO(pdf.getvalue()))
        text = ""
        for p in reader.pages:
            text += p.extract_text() or ""
        # build prompt
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
        prompt = f"""
You have a product catalog text and a price map:
{json.dumps(schema, ensure_ascii=False)}

Price map:
{json.dumps(price_map, ensure_ascii=False)}

Filename: {pdf.name}

Text snippet:
{text[:2000]}

Extract all products into a JSON array following the schema. Return ONLY JSON.
"""
        resp = openai.chat.completions.create(
            model="gpt-4",
            messages=[{"role":"user","content":prompt}],
            temperature=0
        )
        try:
            products = json.loads(resp.choices[0].message.content)
        except Exception:
            st.error("Chyba parsování JSON od GPT"); st.code(resp.choices[0].message.content); st.stop()

        # inject into XML
        for it in products:
            itm = ET.SubElement(root, f"{{{ns['h']}}}SHOPITEM")
            def add(tag, val):
                e = ET.SubElement(itm, f"{{{ns['h']}}}{tag}")
                e.text = str(val)
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

    st.success(f"✨ Vygenerováno {total} položek.")
    # 6) Download
    rough = ET.tostring(root,'utf-8')
    pretty = minidom.parseString(rough).toprettyxml(indent="  ", encoding="UTF-8")
    st.download_button("📥 Stáhnout XML", pretty, "export.xml", "application/xml")
