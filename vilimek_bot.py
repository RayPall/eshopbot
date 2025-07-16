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

st.set_page_config(page_title="Universal Catalog→Heureka XML", layout="wide")
st.title("🤖 Universal Catalog → Heureka XML Exporter")

# ── 1) OpenAI Key ──────────────────────────────────────────────────
openai.api_key = os.getenv("OPENAI_API_KEY")
if not openai.api_key:
    st.error("Chybí `OPENAI_API_KEY` v prostředí. Přidejte jej do Streamlit Secrets.")
    st.stop()

# ── 2) File Uploader ───────────────────────────────────────────────
uploaded = st.file_uploader(
    "Vyberte PDF katalogy, ceníky (.txt/.csv/.xlsx) a XML šablonu",
    type=["pdf","txt","csv","xlsx","xml"], accept_multiple_files=True
)
if not uploaded:
    st.stop()

pdfs       = [f for f in uploaded if f.name.lower().endswith(".pdf")]
prices_txt = [f for f in uploaded if f.name.lower().endswith((".txt","csv"))]
prices_xlsx= [f for f in uploaded if f.name.lower().endswith(".xlsx")]
templates  = [f for f in uploaded if f.name.lower().endswith(".xml")]

st.markdown(f"""- 📑 **PDF katalogů:** {len(pdfs)}  
- 💲 **Ceníků (.txt/.csv):** {len(prices_txt)}  
- 💲 **Ceníků (.xlsx):** {len(prices_xlsx)}  
- 📄 **XML šablon:** {len(templates)}
""")

# select exactly one template
template_file = None
if templates:
    choice = st.selectbox("Vyberte XML šablonu", ["–"]+[t.name for t in templates])
    if choice != "–":
        template_file = next(t for t in templates if t.name==choice)

# helper: extract JSON array from GPT’s reply
def extract_json_array(text: str) -> str:
    start = text.find('[')
    if start<0:
        raise ValueError("No '[' found")
    depth=0
    for i,ch in enumerate(text[start:], start):
        if ch=='[': depth+=1
        elif ch==']':
            depth-=1
            if depth==0:
                return text[start:i+1]
    raise ValueError("No matching ']'")

# ── 3) Generate Button ────────────────────────────────────────────
if st.button("🚀 Generovat XML"):
    # validation
    if not pdfs:
        st.error("Nahrajte alespoň 1 PDF katalog."); st.stop()
    if not (prices_txt or prices_xlsx):
        st.error("Nahrajte alespoň 1 ceník."); st.stop()
    if not template_file:
        st.error("Vyberte XML šablonu."); st.stop()

    # 4) Build unified price map
    price_map={}
    # from txt/csv
    for pf in prices_txt:
        txt=pf.getvalue().decode("utf-8",errors="ignore")
        for L in txt.splitlines():
            m=re.match(r"(.+?)\s+([\d.,]+)\s*€",L)
            if m:
                price_map[m.group(1).strip()]=float(m.group(2).replace(",","."))
    # from xlsx
    for xf in prices_xlsx:
        try:
            dfp=pd.read_excel(xf)
            kcol, pcol = dfp.columns[:2]
            for _,r in dfp.iterrows():
                k=str(r[kcol]).strip()
                v=r[pcol]
                try: price_map[k]=float(v)
                except: pass
        except Exception as e:
            st.warning(f"Nelze číst {xf.name}: {e}")

    st.success(f"Ceník: {len(price_map)} položek.")

    # 5) Load & clear XML template
    tree=ET.parse(io.BytesIO(template_file.getvalue()))
    root=tree.getroot()
    ns={"h":root.tag.split("}")[0].strip("{")}
    for old in root.findall("h:SHOPITEM",ns):
        root.remove(old)

    # ── 6) Process each PDF ────────────────────────────────────────
    count=0
    for pdf in pdfs:
        # extract text
        reader=PyPDF2.PdfReader(io.BytesIO(pdf.getvalue()))
        txt=""
        for page in reader.pages:
            txt+=page.extract_text() or ""
        # fallback ensure text if PyPDF2 missed pages
        if not txt.strip():
            with pdfplumber.open(io.BytesIO(pdf.getvalue())) as doc:
                txt="\n\n".join(p.extract_text() or "" for p in doc.pages)

        # build prompt
        schema={
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
        prompt=f'''
Extract every product from this catalog into a JSON array of objects matching this schema:
{json.dumps(schema,indent=2,ensure_ascii=False)}

Use this price map for NETTO_PRICE (key→price):
{json.dumps(price_map,ensure_ascii=False)}

Catalog filename: {pdf.name}

Catalog text excerpt (first 2000 chars):
{txt[:2000]}

Return ONLY the JSON array.'''

        resp=openai.chat.completions.create(
            model="gpt-4",
            messages=[{"role":"user","content":prompt}],
            temperature=0
        )
        raw=resp.choices[0].message.content
        st.text_area(f"GPT raw for {pdf.name}", raw, height=150)

        try:
            arr=extract_json_array(raw)
            prods=json.loads(arr)
            st.write(f"✅ Parsed {len(prods)} items from {pdf.name}")
        except Exception as e:
            st.error(f"JSON parse error: {e}")
            st.code(raw)
            st.stop()

        # inject into XML
        for it in prods:
            si=ET.SubElement(root,f"{{{ns['h']}}}SHOPITEM")
            def A(tag,val):
                e=ET.SubElement(si,f"{{{ns['h']}}}{tag}")
                e.text=str(val)
            A("ITEM_ID",it.get("ITEM_ID",""))
            A("PRODUCTNAME",it.get("PRODUCTNAME",""))
            A("DESCRIPTION",it.get("DESCRIPTION",""))
            A("CATEGORIES",it.get("CATEGORIES",""))
            A("NETTO_PRICE",it.get("NETTO_PRICE",""))
            A("WEIGHT",it.get("WEIGHT",""))
            A("WIDTH",it.get("WIDTH",""))
            A("HEIGHT",it.get("HEIGHT",""))
            A("THICKNESS",it.get("THICKNESS",""))
            A("MAIN_IMAGE_URL",it.get("MAIN_IMAGE_URL",""))
            for url in it.get("ADDITIONAL_IMAGE_URLS",[]):
                A("ADDITIONAL_IMAGE_URL",url)
            for k,v in it.get("PARAMS",{}).items():
                p=ET.SubElement(si,f"{{{ns['h']}}}PARAM")
                ET.SubElement(p,f"{{{ns['h']}}}PARAM_NAME").text=k
                ET.SubElement(p,f"{{{ns['h']}}}VAL").text=str(v)
            count+=1

    st.success(f"✨ Celkem vygenerováno {count} položek.")

    # ── 7) Download XML ────────────────────────────────────────────
    rough=ET.tostring(root,"utf-8")
    pretty=minidom.parseString(rough).toprettyxml(indent="  ",encoding="UTF-8")
    st.download_button(
        "📥 Stáhnout XML",
        data=pretty,
        file_name="export.xml",
        mime="application/xml"
    )
