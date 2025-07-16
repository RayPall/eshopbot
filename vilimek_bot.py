import io
import re
import pandas as pd
import pdfplumber
import streamlit as st
import xml.etree.ElementTree as ET
from xml.dom import minidom

st.set_page_config(page_title="Universal Heureka Exporter", layout="wide")
st.title("🛠️ Universal PDF → Heureka XML Exporter (Streamlit)")

# 1) Upload all files at once (PDFs, price-lists, **XML template**)
uploaded = st.file_uploader(
    "Vyberte PDF katalogy, ceník (.txt/.csv) a XML šablonu",
    type=["pdf","txt","csv","xml"],
    accept_multiple_files=True
)

if not uploaded:
    st.info("Nahrajte nejprve všechny potřebné soubory (PDF, ceník, XML).")
    st.stop()

# Separate uploads by extension
pdf_files     = [f for f in uploaded if f.name.lower().endswith(".pdf")]
price_files   = [f for f in uploaded if f.name.lower().endswith((".txt","csv"))]
xml_templates = [f for f in uploaded if f.name.lower().endswith(".xml")]

st.write(f"- PDF katalogy: {len(pdf_files)}")
st.write(f"- Ceníky: {len(price_files)}")
st.write(f"- XML šablony: {len(xml_templates)}")

# Choose exactly one XML template
template_file = None
if xml_templates:
    choice = st.selectbox("Vyberte Heureka XML šablonu", ["–"] + [f.name for f in xml_templates])
    if choice != "–":
        template_file = next(f for f in xml_templates if f.name == choice)

# Trigger button
if st.button("🔄 Generovat výsledné XML"):

    # Validation
    if not pdf_files:
        st.error("Musíte nahrát alespoň jeden PDF katalog.")
        st.stop()
    if not price_files:
        st.error("Musíte nahrát alespoň jeden soubor s ceníkem (.txt nebo .csv).")
        st.stop()
    if template_file is None:
        st.error("Musíte vybrat jednu XML šablonu.")
        st.stop()

    # Parse price-lists
    price_map = {}
    for pf in price_files:
        txt = pf.getvalue().decode("utf-8", errors="ignore")
        for line in txt.splitlines():
            m = re.match(r"(.+?)\s+([\d.,]+)\s*€", line)
            if m:
                price_map[m.group(1).strip()] = float(m.group(2).replace(",","."))
    st.success(f"Načteno {len(price_map)} cenových položek.")

    # Extract product rows from all PDFs
    rows = []
    for pdf in pdf_files:
        text = "\n".join(page.extract_text() or "" for page in pdfplumber.open(io.BytesIO(pdf.getvalue())).pages)
        for line in text.splitlines():
            parts = re.split(r"\s{2,}", line.strip())
            if len(parts)>=2 and re.search(r"\d", parts[0]):
                rows.append(parts)

    if not rows:
        st.error("Nepodařilo se najít žádné produktové řádky v PDF.")
        st.stop()

    # Build DataFrame
    header = rows[0] if not re.search(r"\d", "".join(rows[0])) else None
    data = rows[1:] if header else rows
    cols = header or [f"col{i}" for i in range(len(data[0]))]
    df = pd.DataFrame(data, columns=cols)

    st.write("▶️ Ukázka extrahovaných dat")
    st.dataframe(df.head())

    # === HERE: parse the uploaded XML template ===
    xml_bytes = template_file.getvalue()
    tree = ET.parse(io.BytesIO(xml_bytes))
    root = tree.getroot()
    ns = {"h": root.tag.split("}")[0].strip("{")}

    # remove existing SHOPITEMs
    for old in root.findall("h:SHOPITEM", ns):
        root.remove(old)

    # inject one SHOPITEM per row
    for _, row in df.iterrows():
        itm = ET.SubElement(root, f"{{{ns['h']}}}SHOPITEM")
        code = str(row[cols[0]])
        ET.SubElement(itm, f"{{{ns['h']}}}ITEM_ID").text     = code
        ET.SubElement(itm, f"{{{ns['h']}}}PRODUCTNAME").text = code
        # price lookup
        price = price_map.get(code) or price_map.get(str(row.get(cols[1],"")))
        if price is not None:
            ET.SubElement(itm, f"{{{ns['h']}}}NETTO_PRICE").text = str(price)

        # generic PARAMs for every column
        for col in cols:
            val = row[col]
            if pd.isna(val) or val == "":
                continue
            p = ET.SubElement(itm, f"{{{ns['h']}}}PARAM")
            ET.SubElement(p, f"{{{ns['h']}}}PARAM_NAME").text = col
            ET.SubElement(p, f"{{{ns['h']}}}VAL").text        = str(val)

    # pretty-print final XML
    rough = ET.tostring(root, 'utf-8')
    pretty = minidom.parseString(rough).toprettyxml(indent="  ", encoding="UTF-8")

    st.success("✨ XML bylo úspěšně vygenerováno!")
    st.download_button(
        label="📥 Stáhnout exportované XML",
        data=pretty,
        file_name="exported.xml",
        mime="application/xml"
    )
