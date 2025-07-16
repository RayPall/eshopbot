#!/usr/bin/env python3
import io
import re
import camelot        # pip install camelot-py[cv]
import pdfplumber
import pandas as pd
import xml.etree.ElementTree as ET

# ——— CONFIG ——————————————————————————————————————————————
PDF_PATH      = "Del-Conca-Lavaredo-Katalog-produktu.pdf"
CENIK_PATH    = "cenik.txt"
TEMPLATE_XML  = "resultFromUIForImport.xml"
OUTPUT_XML    = "exported.xml"

# Heureka XML namespace
NS = {"h": "http://www.heureka.cz/ns/offer/1.0"}
ET.register_namespace('', NS["h"])

# The minimal set of XML tags we want to fill. You can extend this dict
# with more tags from your template as needed.
XML_FIELD_MAP = {
    "ITEM_ID":      ("C", str),   # Produktový kód → ITEM_ID
    "PRODUCTNAME":  ("D", str),   # Název produktu → PRODUCTNAME
    "CATEGORIES":   ("S", str),   # Hlavní kategorie → CATEGORIES
    "WEIGHT":       ("I", float), # Váha → WEIGHT
    "NETTO_PRICE":  ("P", float), # Cena → NETTO_PRICE
    # add more mappings here...
}

def parse_price_list(path):
    price_map = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            m = re.match(r"(.+?)\s+([\d.,]+)\s*€", line)
            if m:
                key = m.group(1).strip()
                price = float(m.group(2).replace(",", "."))
                price_map[key] = price
    return price_map

def extract_table_from_pdf(path):
    b = open(path, "rb").read()
    # 1) Try Camelot
    try:
        tables = camelot.read_pdf(io.BytesIO(b), pages="all", flavor="stream")
        if tables:
            df = max((t.df for t in tables), key=lambda d: d.shape[0])
            df.columns = df.iloc[0]
            df = df.drop(0).reset_index(drop=True)
            return df
    except Exception:
        pass

    # 2) Fallback: plain text + split on whitespace
    with pdfplumber.open(io.BytesIO(b)) as pdf:
        text = "\n".join(p.extract_text() or "" for p in pdf.pages)
    rows = []
    for line in text.splitlines():
        parts = re.split(r"\s{2,}", line.strip())
        if len(parts) >= 6 and re.match(r"^\d", parts[0]):
            rows.append(parts)
    # you will need to adjust this to your PDF’s actual column layout!
    cols = ["size","pieces","sqm","kg","boxes","total_sqm","total_kg"]
    df = pd.DataFrame(rows, columns=cols[:len(rows[0])])
    return df

def build_heureka_xml(df, price_map, template_path, output_path):
    # Load template
    tree = ET.parse(template_path)
    root = tree.getroot()

    # Remove any existing SHOPITEMs
    for item in root.findall("h:SHOPITEM", NS):
        root.remove(item)

    # For each row in df, create a new SHOPITEM
    for _, row in df.iterrows():
        item = ET.SubElement(root, f"{{{NS['h']}}}SHOPITEM")
        # Fill direct tags
        for tag, (col, caster) in XML_FIELD_MAP.items():
            val = row.get(col)
            # if that column doesn’t exist in df, skip
            if val is None or (isinstance(val, float) and pd.isna(val)):
                continue
            # if this is a key that we need to look up in the price map:
            if tag == "NETTO_PRICE":
                # try matching by size or code
                price = price_map.get(str(row.get("C"))) or price_map.get(str(row.get("size")))
                val = price or val
            el = ET.SubElement(item, f"{{{NS['h']}}}{tag}")
            el.text = str(caster(val))

        # Example: add PARAM blocks for A–U if you want them in PARAM tags
        #for col in ["A","B","E","F","G","H","J","K","L","M","N","O","Q","R","T","U"]:
        #    if col in row and pd.notna(row[col]):
        #        p = ET.SubElement(item, f"{{{NS['h']}}}PARAM")
        #        name = ET.SubElement(p, f"{{{NS['h']}}}PARAM_NAME"); name.text = col
        #        v    = ET.SubElement(p, f"{{{NS['h']}}}VAL");        v.text  = str(row[col])

    # Pretty-print and write
    rough = ET.tostring(root, encoding="utf-8")
    from xml.dom import minidom
    doc = minidom.parseString(rough)
    with open(output_path, "wb") as f:
        f.write(doc.toprettyxml(indent="  ", encoding="UTF-8"))

if __name__ == "__main__":
    price_map = parse_price_list(CENIK_PATH)
    print(f"Prices: {len(price_map)} items")
    df = extract_table_from_pdf(PDF_PATH)
    print(f"Extracted table with {len(df)} rows and columns: {list(df.columns)}")
    build_heureka_xml(df, price_map, TEMPLATE_XML, OUTPUT_XML)
    print("Wrote:", OUTPUT_XML)
