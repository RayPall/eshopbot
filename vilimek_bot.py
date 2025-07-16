import os
import io
import re
import json
import PyPDF2
import pdfplumber
import pandas as pd
import streamlit as st
import openai
import xml.etree.ElementTree as ET
from xml.dom import minidom

st.set_page_config(page_title="Smart PDF→Heureka XML", layout="wide")
st.title("🤖 Smart PDF → Heureka XML Exporter")

# 1) API Key
openai.api_key = os.getenv("OPENAI_API_KEY")
if not openai.api_key:
    st.error("Set OPENAI_API_KEY in your environment (Streamlit Secrets).")
    st.stop()

# 2) File uploader
files = st.file_uploader(
    "Upload PDFs, pricelists (.xlsx/.txt/.csv) and XML template",
    type=["pdf","xlsx","txt","csv","xml"],
    accept_multiple_files=True
)
if not files:
    st.stop()

# Separate uploads
pdfs       = {f.name: f for f in files if f.name.lower().endswith(".pdf")}
prices_xlsx= {f.name: f for f in files if f.name.lower().endswith(".xlsx")}
templates  = [f for f in files if f.name.lower().endswith(".xml")]

st.write(f"- PDFs: {list(pdfs.keys())}")
st.write(f"- Excel pricelists: {list(prices_xlsx.keys())}")
st.write(f"- Templates: {[t.name for t in templates]}")

# Pick template
template_file = None
if templates:
    choice = st.selectbox("Choose XML template", ["–"] + [t.name for t in templates])
    if choice != "–":
        template_file = next(t for t in templates if t.name == choice)

if st.button("Generate Heureka XML"):
    # Validation
    if not template_file:
        st.error("Please select an XML template."); st.stop()
    if not pdfs:
        st.error("Please upload at least one PDF."); st.stop()

    # Load and clear XML template
    tree = ET.parse(io.BytesIO(template_file.getvalue()))
    root = tree.getroot()
    ns_uri = root.tag.split("}")[0].strip("{")
    ns = {"h": ns_uri}
    for old in root.findall("h:SHOPITEM", ns):
        root.remove(old)

    shopitems = []

    # --- Special case: Stone Edition ---
    if "Stone_Edition.pdf" in pdfs and "stoneedition2025.xlsx" in prices_xlsx:
        st.info("Detected Stone Edition files—using direct Excel→XML mapping.")
        # 1) Read Excel
        df = pd.read_excel(prices_xlsx["stoneedition2025.xlsx"])
        # assume columns: ['Code','Name','Width','Height','Thickness','Weight','Price']
        for _, r in df.iterrows():
            item = {
                "ITEM_ID":       r["Code"],
                "PRODUCTNAME":   r["Name"],
                "CATEGORIES":    "Dlažby, Obklady",
                "WEIGHT":        r["Weight"],
                "DESCRIPTION":   r["Name"],
                "MAIN_IMAGE_URL":"https://example.com/images/" + r["Code"] + "_main.jpg",
                "NETTO_PRICE":   r["Price"],
                "PARAMS": {
                    "Barva":            r.get("Color",""),
                    "Šířka":            f"{int(r['Width'])} mm",
                    "Výška":            f"{int(r['Height'])} mm",
                    "Tloušťka":         f"{r['Thickness']} mm",
                    "Rozměr":           f"{int(r['Width']/10)} × {int(r['Height']/10)} × {r['Thickness']/10} cm",
                    "Váha":             f"{r['Weight']} kg",
                    "Estetický vzhled": "Kámen",
                    "Použití":          "Dlažba, Obklad",
                    "Tvar":             "Čtverec" if r["Width"]==r["Height"] else "Obdélník",
                    "Povrch":           "Matný",
                    "Specifikace":      "Protiskluz R10",
                    "Materiál":         "Mrazuvzdorný slinutý",
                },
            }
            shopitems.append(item)
    # --- Universal fallback for any other PDF ---
    else:
        st.info("Using GPT pipeline for other PDFs.")
        # (Insert your existing GPT-based loop here,
        # skipping it if you only want Stone Edition.)

    # Inject all shopitems into XML
    for it in shopitems:
        si = ET.SubElement(root, f"{{{ns_uri}}}SHOPITEM")
        def add(tag, val):
            e = ET.SubElement(si, f"{{{ns_uri}}}{tag}")
            e.text = str(val)
        add("ITEM_ID",      it["ITEM_ID"])
        add("PRODUCTNAME",  it["PRODUCTNAME"])
        add("CATEGORIES",   it["CATEGORIES"])
        add("WEIGHT",       it["WEIGHT"])
        add("DESCRIPTION",  it["DESCRIPTION"])
        add("MAIN_IMAGE_URL", it["MAIN_IMAGE_URL"])
        add("NETTO_PRICE",  it["NETTO_PRICE"])
        # Params
        for k, v in it["PARAMS"].items():
            p = ET.SubElement(si, f"{{{ns_uri}}}PARAM")
            ET.SubElement(p, f"{{{ns_uri}}}PARAM_NAME").text = k
            ET.SubElement(p, f"{{{ns_uri}}}VAL").text        = str(v)

    # Pretty-print & download
    rough = ET.tostring(root, "utf-8")
    pretty = minidom.parseString(rough).toprettyxml(indent="  ", encoding="UTF-8")
    st.download_button("Download XML", data=pretty, file_name="exported.xml", mime="application/xml")

    st.success(f"Generated {len(shopitems)} SHOPITEM entries.")
