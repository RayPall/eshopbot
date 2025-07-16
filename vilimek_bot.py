import io
import os
import re
import json
import pdfplumber
import streamlit as st
import openai
import xml.etree.ElementTree as ET
from xml.dom import minidom

st.set_page_config(page_title="Inteligentní PDF→Heureka XML", layout="wide")
st.title("🛠️ Inteligentní PDF → Heureka XML Exporter")

# ——— 1) API Key ——————————————————————————————————————————————
openai.api_key = os.getenv("OPENAI_API_KEY")
if not openai.api_key:
    st.error("Chybí proměnná prostředí OPENAI_API_KEY. Nastavte ji v Secrets.")
    st.stop()

# ——— 2) File Uploader —————————————————————————————————————————
uploaded = st.file_uploader(
    "Nahrajte PDF katalogy, ceník (.txt/.csv) a XML šablonu",
    type=["pdf", "txt", "csv", "xml"],
    accept_multiple_files=True
)
if not uploaded:
    st.stop()

# separate by extension
pdfs      = [f for f in uploaded if f.name.lower().endswith(".pdf")]
prices    = [f for f in uploaded if f.name.lower().endswith((".txt", ".csv"))]
templates = [f for f in uploaded if f.name.lower().endswith(".xml")]

st.write(f"- PDF katalogů: {len(pdfs)}") 
st.write(f"- Ceníků: {len(prices)}") 
st.write(f"- XML šablon: {len(templates)}")

# choose one XML template
template_file = None
if templates:
    choice = st.selectbox("Vyberte Heureka XML šablonu", ["–"] + [t.name for t in templates])
    if choice != "–":
        template_file = next(t for t in templates if t.name == choice)

if st.button("🔄 Generovat inteligentní XML"):
    # validation
    if not pdfs:
        st.error("Musíte nahrát alespoň jeden PDF katalog.")
        st.stop()
    if not prices:
        st.error("Musíte nahrát alespoň jeden ceník (.txt/.csv).")
        st.stop()
    if template_file is None:
        st.error("Musíte vybrat jednu XML šablonu.")
        st.stop()

    # ——— 3) Parse price map —————————————————————————————
    price_map = {}
    for pf in prices:
        text = pf.getvalue().decode("utf-8", errors="ignore")
        for line in text.splitlines():
            m = re.match(r"(.+?)\s+([\d.,]+)\s*€", line)
            if m:
                price_map[m.group(1).strip()] = float(m.group(2).replace(",", "."))
    st.success(f"Načteno {len(price_map)} cenových položek.")

    # ——— 4) Load XML template ————————————————————————————
    xml_bytes = template_file.getvalue()
    tree = ET.parse(io.BytesIO(xml_bytes))
    root = tree.getroot()
    ns = {"h": root.tag.split("}")[0].strip("{")}
    # remove existing SHOPITEM
    for old in root.findall("h:SHOPITEM", ns):
        root.remove(old)

    # ——— 5) Process each PDF with GPT —————————————————————
    items_total = 0
    for pdf in pdfs:
        # extract text
        with pdfplumber.open(io.BytesIO(pdf.getvalue())) as doc:
            full_text = "\n\n".join(page.extract_text() or "" for page in doc.pages)

        # build prompt
        prompt = f"""
You are given a full text of a product catalog and must extract every product into a JSON array of objects with these keys:
ITEM_ID, PRODUCTNAME, DESCRIPTION, CATEGORIES, NETTO_PRICE, WEIGHT, WIDTH, HEIGHT, THICKNESS, MAIN_IMAGE_URL, ADDITIONAL_IMAGE_URLS, PARAMS.
Use this price map: {json.dumps(price_map, ensure_ascii=False)}
Catalog filename: {pdf.name}
Catalog text snippet:
{full_text[:2000]}
Return ONLY valid JSON array.
"""

        # call GPT
        resp = openai.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}],
            temperature=0
        )
        try:
            products = json.loads(resp.choices[0].message.content)
        except Exception as e:
            st.error("Chyba parsování JSON od GPT: " + str(e))
            st.code(resp.choices[0].message.content)
            st.stop()

        # inject into XML
        for it in products:
            item = ET.SubElement(root, f"{{{ns['h']}}}SHOPITEM")
            def add(tag, val):
                el = ET.SubElement(item, f"{{{ns['h']}}}{tag}")
                el.text = str(val)
            # required tags
            add("ITEM_ID",        it.get("ITEM_ID", ""))
            add("PRODUCTNAME",    it.get("PRODUCTNAME", ""))
            add("DESCRIPTION",    it.get("DESCRIPTION", ""))
            add("CATEGORIES",     it.get("CATEGORIES", ""))
            add("NETTO_PRICE",    it.get("NETTO_PRICE", ""))
            add("WEIGHT",         it.get("WEIGHT", ""))
            add("WIDTH",          it.get("WIDTH", ""))
            add("HEIGHT",         it.get("HEIGHT", ""))
            add("THICKNESS",      it.get("THICKNESS", ""))
            add("MAIN_IMAGE_URL", it.get("MAIN_IMAGE_URL", ""))

            # additional images
            for url in it.get("ADDITIONAL_IMAGE_URLS", []):
                add("ADDITIONAL_IMAGE_URL", url)

            # other params
            for k, v in it.get("PARAMS", {}).items():
                p = ET.SubElement(item, f"{{{ns['h']}}}PARAM")
                ET.SubElement(p, f"{{{ns['h']}}}PARAM_NAME").text = k
                ET.SubElement(p, f"{{{ns['h']}}}VAL").text        = str(v)

            items_total += 1

    st.success(f"✨ Vygenerováno {items_total} SHOPITEM elementů.")

    # ——— 6) Pretty-print and download —————————————————————
    rough = ET.tostring(root, 'utf-8')
    pretty = minidom.parseString(rough).toprettyxml(indent="  ", encoding="UTF-8")
    st.download_button(
        label="📥 Stáhnout XML",
        data=pretty,
        file_name="export_smart.xml",
        mime="application/xml"
    )
