import streamlit as st
import sys
import io
import re
import json
import camelot
import pdfplumber
import pandas as pd
import openai
import xml.etree.ElementTree as ET
from xml.dom import minidom

# ——— 1) Configure your OpenAI API key ——————————————————————————————
openai.api_key = "OPENAI_API_KEY"  # Or set via environment variable

# ——— 2) Heureka XML namespace & columns A–U definition ——————————————
NS = "http://www.heureka.cz/ns/offer/1.0"
ET.register_namespace('', NS)

COLUMNS = [
    ("A","Název Keramičky"),
    ("B","Název kolekce"),
    ("C","Produktový kód"),
    ("D","Název produktu"),
    ("E","Barva"),
    ("F","Materiál - Rektifikovaný (0/1)"),
    ("G","Povrch (Matný/Lesklý)"),
    ("H","Hlavní obrázek (valid URL)"),
    ("I","Váha (kg)"),
    ("J","Šířka"),
    ("K","Výška"),
    ("L","Tloušťka"),
    ("M","Specifikace (Protiskluz R9–R12)"),
    ("N","Tvar"),
    ("O","Estetický vzhled"),
    ("P","Cena (EUR)"),
    ("Q","Materiál (typ střepu)"),
    ("R","Použití"),
    ("S","Hlavní kategorie"),
    ("T","Jednotka"),
    ("U","Velikost balení"),
]

BASE_PROMPT = """
Máš za úkol extrahovat všechny produkty z katalogu do JSON pole, kde každý objekt obsahuje přesně tyto sloupce A–U (klíče "A" až "U"):

{cols}

Níže je vstupní text z PDF (nebo čistý text v případě selhání tabulkového parseru). Vrať pouze JSON pole, bez dalšího komentáře:

---
{data}
---
""".strip()

def parse_price_file(raw_text: str) -> dict:
    """
    Z libovolného textu (ceník.txt, CSV, TSV) vytáhne mapování key→float price.
    """
    price_map = {}
    for line in raw_text.splitlines():
        m = re.match(r"(.+?)\s+([\d.,]+)\s*€", line)
        if m:
            key = m.group(1).strip()
            price = float(m.group(2).replace(",", "."))
            price_map[key] = price
    return price_map

def parse_pdf_universal(pdf_bytes: bytes, price_map: dict) -> pd.DataFrame:
    """
    1) Zkus camelot na detekci tabulek
    2) Pokud selže, fallback na pdfplumber + GPT
    """
    # 1) Camelot table extraction
    try:
        tables = camelot.read_pdf(io.BytesIO(pdf_bytes), pages="all", flavor="stream")
        if tables and len(tables) > 0:
            # choose the largest table by row count
            df = max((t.df for t in tables), key=lambda d: d.shape[0])
            df.columns = df.iloc[0]      # first row as header
            df = df.drop(0).reset_index(drop=True)
            return df
    except Exception:
        pass

    # 2) Fallback: plain text & GPT
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        text = "\n\n".join(p.extract_text() or "" for p in pdf.pages)

    cols_descr = "\n".join(f"{k}: {v}" for k,v in COLUMNS)
    prompt = BASE_PROMPT.format(cols=cols_descr, data=text)

    resp = openai.chat.completions.create(
        model="gpt-4",
        messages=[{"role":"user","content":prompt}],
        temperature=0,
        max_tokens=2000,
    )
    content = resp.choices[0].message.content.strip()
    data = json.loads(content)
    return pd.DataFrame(data)

def dataframe_to_heureka_xml(df: pd.DataFrame, default_manufacturer="Del Conca / Faetano") -> bytes:
    """
    Convert a DataFrame into Heureka SHOP XML.
    Expects df columns to include at least:
    ITEM_ID, PRODUCTNAME, and PARAM_<field> for any A–U or other parameters.
    """
    shop = ET.Element(f"{{{NS}}}SHOP", desc="export from universal parser")
    for _, row in df.iterrows():
        item = ET.SubElement(shop, f"{{{NS}}}SHOPITEM")
        def add(tag, text):
            el = ET.SubElement(item, f"{{{NS}}}{tag}")
            el.text = str(text) if text is not None else ""

        # Basic required tags (customize mapping as needed)
        add("ITEM_ID",      row.get("C", ""))  # Produktový kód
        add("PRODUCTNAME",  row.get("D", ""))  # Název produktu
        add("MANUFACTURER", row.get("A", default_manufacturer))

        # Example PARAMs for A–U
        for col_key, col_name in COLUMNS:
            val = row.get(col_key)
            if pd.notna(val) and val != "":
                param = ET.SubElement(item, f"{{{NS}}}PARAM")
                name = ET.SubElement(param, f"{{{NS}}}PARAM_NAME"); name.text = col_name
                v = ET.SubElement(param, f"{{{NS}}}VAL");        v.text  = str(val)

    rough = ET.tostring(shop, 'utf-8')
    parsed = minidom.parseString(rough)
    return parsed.toprettyxml(indent="  ", encoding="UTF-8")

def main():
    if len(sys.argv) != 4:
        print(__doc__)
        sys.exit(1)
    pdf_path, cenik_path, output_path = sys.argv[1:]

    # Read inputs
    pdf_bytes = open(pdf_path, "rb").read()
    raw_cenik = open(cenik_path, encoding="utf-8").read()
    price_map = parse_price_file(raw_cenik)
    print(f"Loaded {len(price_map)} price entries")

    # Parse PDF
    df = parse_pdf_universal(pdf_bytes, price_map)
    print(f"Extracted DataFrame with {len(df)} rows")

    # Convert to XML and save
    xml_bytes = dataframe_to_heureka_xml(df)
    with open(output_path, "wb") as f:
        f.write(xml_bytes)
    print(f"Wrote Heureka XML to {output_path}")

if __name__ == "__main__":
    main()
