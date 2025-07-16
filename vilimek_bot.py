import io
import re
import pandas as pd
import pdfplumber
import streamlit as st
import xml.etree.ElementTree as ET
from xml.dom import minidom

st.set_page_config(page_title="Universal Heureka Exporter", layout="wide")
st.title("🛠️ Universal PDF → Heureka XML Exporter (Streamlit)")

# 1) Uploaders
st.markdown("#### 1️⃣ Nahrajte všechny soubory najednou")
uploaded = st.file_uploader(
    label="Vyberte PDF katalogy, ceník (.txt/.csv) a XML šablonu",
    type=["pdf","txt","csv","xml"],
    accept_multiple_files=True
)

if uploaded:
    # Separate by extension
    pdf_files   = [f for f in uploaded if f.name.lower().endswith(".pdf")]
    price_files = [f for f in uploaded if f.name.lower().endswith((".txt",".csv"))]
    xml_templates = [f for f in uploaded if f.name.lower().endswith(".xml")]

    st.write(f"- Katalogy (PDF): {len(pdf_files)}") 
    st.write(f"- Ceníky (.txt/.csv): {len(price_files)}")
    st.write(f"- Šablony XML: {len(xml_templates)}")

    # Let user choose their template if more than one
    template_file = None
    if xml_templates:
        names = [f.name for f in xml_templates]
        choice = st.selectbox("Vyberte Heureka XML šablonu", ["–"] + names)
        if choice != "–":
            template_file = next(f for f in xml_templates if f.name==choice)

    # Only enable when we have at least one PDF, one price-list, and a template
    if st.button("🔄 Generovat výsledné XML"):
        # Validation
        if not pdf_files:
            st.error("Potřebujete nahrát alespoň jeden PDF katalog.")
            st.stop()
        if not price_files:
            st.error("Potřebujete nahrát alespoň jeden ceník (.txt/.csv).")
            st.stop()
        if template_file is None:
            st.error("Vyberte prosím XML šablonu.")
            st.stop()

        # 2) Parse price-lists into a single dict
        price_map = {}
        for pf in price_files:
            txt = pf.getvalue().decode("utf-8", errors="ignore")
            for line in txt.splitlines():
                m = re.match(r"(.+?)\s+([\d.,]+)\s*€", line)
                if m:
                    key = m.group(1).strip()
                    price_map[key] = float(m.group(2).replace(",", "."))
        if not price_map:
            st.warning("Ceník byl načten, ale nenašel jsem žádné ceny (klíče → číslo €).")
        else:
            st.success(f"Načteno {len(price_map)} cenových položek.")

        # 3) Extract tables from PDFs into one DataFrame
        all_rows = []
        for pdf in pdf_files:
            raw = pdf.getvalue()
            with pdfplumber.open(io.BytesIO(raw)) as doc:
                text = "\n".join(p.extract_text() or "" for p in doc.pages)
            for line in text.splitlines():
                parts = re.split(r"\s{2,}", line.strip())
                # Heuristic: first token contains a digit
                if len(parts)>=2 and re.search(r"\d", parts[0]):
                    parts.append(pdf.name)  # track source
                    all_rows.append(parts)

        if not all_rows:
            st.error("Nepodařilo se najít žádné řádky produktů v PDF.")
            st.stop()

        # Build DataFrame: header = first row if non-numeric, else generic
        header = all_rows[0] if not re.search(r"\d", "".join(all_rows[0])) else None
        data_rows = all_rows[1:] if header else all_rows
        columns = header or [f"col{i}" for i in range(len(data_rows[0]))] + ["source"]
        df = pd.DataFrame(data_rows, columns=columns + (["source"] if header else []))

        st.write("▶️ Ukázka extrahovaných řádků")
        st.dataframe(df.head())

        # 4) Load XML template
        tree = ET.parse(io.BytesIO(template_file.getvalue()))
        root = tree.getroot()
        ns = {"h": root.tag.split("}")[0].strip("{")}

        # remove existing SHOPITEMs
        for existing in root.findall("h:SHOPITEM", ns):
            root.remove(existing)

        # 5) Inject one SHOPITEM per DataFrame row
        for _, row in df.iterrows():
            itm = ET.SubElement(root, f"{{{ns['h']}}}SHOPITEM")
            # ITEM_ID & PRODUCTNAME = first column
            code = str(row[columns[0]])
            ET.SubElement(itm, f"{{{ns['h']}}}ITEM_ID").text     = code
            ET.SubElement(itm, f"{{{ns['h']}}}PRODUCTNAME").text = code

            # NETTO_PRICE from price_map if possible
            price = price_map.get(code) or price_map.get(str(row.get(columns[1],"")))
            if price is not None:
                ET.SubElement(itm, f"{{{ns['h']}}}NETTO_PRICE").text = str(price)

            # generic PARAM blocks for every column
            for col in columns:
                val = row[col]
                if pd.isna(val) or val=="":
                    continue
                p = ET.SubElement(itm, f"{{{ns['h']}}}PARAM")
                ET.SubElement(p, f"{{{ns['h']}}}PARAM_NAME").text = col
                ET.SubElement(p, f"{{{ns['h']}}}VAL").text        = str(val)

        # 6) Pretty-print and offer download
        rough = ET.tostring(root, encoding="utf-8")
        pretty = minidom.parseString(rough).toprettyxml(indent="  ", encoding="UTF-8")

        st.success("✨ XML bylo vygenerováno!")
        st.download_button(
            label="📥 Stáhnout výstupní XML",
            data=pretty,
            file_name="exported_universal.xml",
            mime="application/xml"
        )
