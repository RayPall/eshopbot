#!/usr/bin/env python3
import os
import re
import io
import sys
import glob
import pdfplumber     # pip install pdfplumber
import pandas as pd   # pip install pandas
import xml.etree.ElementTree as ET
from xml.dom import minidom

# ——— CONFIG ——————————————————————————————————————————————
INPUT_DIR    = "./inputs"                    # place PDFs and price lists here
TEMPLATE_XML = "resultFromUIForImport.xml"   # fixed template :contentReference[oaicite:1]{index=1}
OUTPUT_XML   = "exported.xml"
# ————————————————————————————————————————————————————————

# register namespace
NS = {"h": "http://www.heureka.cz/ns/offer/1.0"}
ET.register_namespace('', NS["h"])

def parse_prices(path):
    """Parse any .txt/.csv into key→float map from lines like 'KEY   12,34 €'"""
    pm = {}
    text = open(path, encoding="utf-8", errors="ignore").read()
    for line in text.splitlines():
        m = re.match(r"(.+?)\s+([\d.,]+)\s*€", line)
        if m:
            key = m.group(1).strip()
            pm[key] = float(m.group(2).replace(",","."))
    return pm

def gather_price_map(folder):
    pm = {}
    for fn in glob.glob(os.path.join(folder,"*.txt")) + glob.glob(os.path.join(folder,"*.csv")):
        pm.update(parse_prices(fn))
    print(f"  → Loaded {len(pm)} price entries")
    return pm

def extract_rows_from_pdf(path):
    """Heuristic: split lines on big whitespace runs; keep those starting with a digit."""
    rows = []
    with pdfplumber.open(path) as pdf:
        for p in pdf.pages:
            for line in (p.extract_text() or "").splitlines():
                parts = re.split(r"\s{2,}", line.strip())
                if len(parts)>=2 and re.match(r"\d", parts[0]):
                    rows.append(parts)
    return rows

def build_dataframe(rows):
    if not rows:
        return pd.DataFrame()
    # if first row contains no digit, treat as header
    header = rows[0] if not re.search(r"\d", "".join(rows[0])) else None
    data = rows[1:] if header else rows
    cols = header or [f"col{i}" for i in range(len(data[0]))]
    df = pd.DataFrame(data, columns=cols)
    return df

def main():
    # 1) Load template
    tree = ET.parse(TEMPLATE_XML)
    root = tree.getroot()

    # 2) Remove existing SHOPITEMs
    for el in root.findall("h:SHOPITEM", NS):
        root.remove(el)

    # 3) Build price map
    pm = gather_price_map(INPUT_DIR)

    # 4) Iterate PDFs and extract data
    total = 0
    for pdf_path in glob.glob(os.path.join(INPUT_DIR,"*.pdf")):
        print(f"Processing {os.path.basename(pdf_path)} ...")
        rows = extract_rows_from_pdf(pdf_path)
        df = build_dataframe(rows)
        print(f"  → extracted {len(df)} rows, columns: {list(df.columns)}")
        # 5) Inject each row as SHOPITEM
        for _, row in df.iterrows():
            itm = ET.SubElement(root, f"{{{NS['h']}}}SHOPITEM")
            # ITEM_ID & PRODUCTNAME = first column
            code = str(row.iloc[0])
            ET.SubElement(itm, f"{{{NS['h']}}}ITEM_ID").text     = code
            ET.SubElement(itm, f"{{{NS['h']}}}PRODUCTNAME").text = code
            # price lookup
            price = pm.get(code) or pm.get(str(row.iloc[1]))
            if price is not None:
                ET.SubElement(itm, f"{{{NS['h']}}}NETTO_PRICE").text = f"{price:.4f}"
            # generic PARAM blocks for all columns
            for col in df.columns:
                val = row[col]
                if val is None or val == "":
                    continue
                p = ET.SubElement(itm, f"{{{NS['h']}}}PARAM")
                ET.SubElement(p, f"{{{NS['h']}}}PARAM_NAME").text = col
                ET.SubElement(p, f"{{{NS['h']}}}VAL").text        = str(val)
            total += 1

    print(f"Injected {total} SHOPITEM entries.")

    # 6) Pretty-print and save
    rough = ET.tostring(root, encoding="utf-8")
    pretty = minidom.parseString(rough).toprettyxml(indent="  ", encoding="UTF-8")
    with open(OUTPUT_XML, "wb") as f:
        f.write(pretty)
    print(f"Wrote output to {OUTPUT_XML}")

if __name__ == "__main__":
    main()
