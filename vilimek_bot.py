#!/usr/bin/env python3
import os
import io
import re
import sys
import camelot        # pip install camelot-py[cv]
import pdfplumber    # pip install pdfplumber
import pandas as pd  # pip install pandas
import xml.etree.ElementTree as ET
from xml.dom import minidom

# -------------- CONFIG --------------
INPUT_DIR    = "./inputs"                   # place your PDFs + price-lists here
TEMPLATE_XML = "resultFromUIForImport.xml"  # your existing XML template
OUTPUT_XML   = "exported_universal.xml"     # where to write the result
# -------------------------------------

NS = {"h": "http://www.heureka.cz/ns/offer/1.0"}
ET.register_namespace('', NS["h"])

def parse_all_price_lists(folder):
    """Scan folder for .txt/.csv and build a single key→float map."""
    price_map = {}
    for fn in os.listdir(folder):
        if fn.lower().endswith((".txt",".csv")):
            path = os.path.join(folder, fn)
            text = open(path, encoding="utf-8", errors="ignore").read()
            for line in text.splitlines():
                m = re.match(r"(.+?)\s+([\d.,]+)\s*€", line)
                if m:
                    key = m.group(1).strip()
                    price_map[key] = float(m.group(2).replace(",","."))
    print(f"Parsed prices: {len(price_map)} entries")
    return price_map

def extract_table(path):
    """Try Camelot, otherwise pdfplumber + whitespace split."""
    b = open(path,"rb").read()
    try:
        tables = camelot.read_pdf(io.BytesIO(b), pages="all", flavor="stream")
        if tables:
            # take largest
            df = max((t.df for t in tables), key=lambda d: d.shape[0])
            df.columns = df.iloc[0]
            return df.drop(0).reset_index(drop=True)
    except Exception:
        pass

    # fallback
    with pdfplumber.open(io.BytesIO(b)) as pdf:
        text = "\n".join(p.extract_text() or "" for p in pdf.pages)
    rows=[]
    for L in text.splitlines():
        parts = re.split(r"\s{2,}", L.strip())
        if len(parts)>=2 and any(c.isdigit() for c in parts[0]):
            rows.append(parts)
    if not rows:
        return pd.DataFrame()
    # header = first row if it is all non-numeric
    header = rows[0] if not any(ch.isdigit() for ch in "".join(rows[0])) else None
    data = rows[1:] if header else rows
    cols = header or [f"col_{i}" for i in range(len(data[0]))]
    return pd.DataFrame(data, columns=cols)

def build_universal_df(input_dir):
    """Load all PDFs, extract tables, concat into one DF."""
    dfs=[]
    for fn in os.listdir(input_dir):
        if fn.lower().endswith(".pdf"):
            path = os.path.join(input_dir, fn)
            print("Extracting:", fn)
            df = extract_table(path)
            df["__source_file"] = fn
            dfs.append(df)
    if not dfs:
        print("No PDF tables found.")
        sys.exit(1)
    return pd.concat(dfs, ignore_index=True)

def write_heureka_xml(df, price_map, template_xml, output_xml):
    """Remove existing SHOPITEMs, then append one per DataFrame row."""
    tree = ET.parse(template_xml)
    root = tree.getroot()
    # remove old items
    for it in root.findall("h:SHOPITEM", NS):
        root.remove(it)

    for _, row in df.iterrows():
        item = ET.SubElement(root, f"{{{NS['h']}}}SHOPITEM")
        # Minimal required tags
        code = row.get("Produktový kód") or row.get(row.index[0])  # try header 'Produktový kód' or first column
        ET.SubElement(item, f"{{{NS['h']}}}ITEM_ID").text = str(code)
        ET.SubElement(item, f"{{{NS['h']}}}PRODUCTNAME").text = str(code)

        # Price lookup
        price = price_map.get(str(code)) or price_map.get(str(row.get("col_1","")))
        if price is not None:
            ET.SubElement(item, f"{{{NS['h']}}}NETTO_PRICE").text = str(price)

        # Generic PARAM for every column in the DF
        for col in df.columns:
            val = row[col]
            if pd.isna(val) or col=="__source_file":
                continue
            p = ET.SubElement(item, f"{{{NS['h']}}}PARAM")
            ET.SubElement(p, f"{{{NS['h']}}}PARAM_NAME").text = str(col)
            ET.SubElement(p, f"{{{NS['h']}}}VAL").text = str(val)

    # pretty write
    rough = ET.tostring(root, "utf-8")
    pretty = minidom.parseString(rough).toprettyxml(indent="  ", encoding="UTF-8")
    with open(output_xml, "wb") as f:
        f.write(pretty)
    print("Wrote XML:", output_xml)

if __name__=="__main__":
    pm = parse_all_price_lists(INPUT_DIR)
    df = build_universal_df(INPUT_DIR)
    print("Combined DataFrame shape:", df.shape)
    write_heureka_xml(df, pm, TEMPLATE_XML, OUTPUT_XML)
