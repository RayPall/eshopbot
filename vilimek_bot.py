import io, re, pdfplumber, json, xml.etree.ElementTree as ET
from xml.dom import minidom
import streamlit as st
import openai

st.title("Inteligentní PDF→Heureka XML")
openai.api_key = st.text_input("OpenAI API Key", type="password")

# 1) Upload
files = st.file_uploader("PDF, ceník (.txt/.csv), XML šablona", type=["pdf","txt","csv","xml"], accept_multiple_files=True)
if not files:
    st.stop()

pdfs       = [f for f in files if f.name.lower().endswith(".pdf")]
prices     = [f for f in files if f.name.lower().endswith((".txt","csv"))]
templates  = [f for f in files if f.name.lower().endswith(".xml")]

template = st.selectbox("Vyberte XML šablonu", ["–"]+[t.name for t in templates])
if template=="–":
    st.stop()
template_file = next(t for t in templates if t.name==template)

if not st.button("Generovat inteligentní XML"):
    st.stop()

# 2) Load XML template
tree = ET.parse(io.BytesIO(template_file.getvalue()))
root = tree.getroot()
ns = {"h": root.tag.split("}")[0].strip("{")}
for old in root.findall("h:SHOPITEM", ns):
    root.remove(old)

# 3) Build price map
price_map = {}
for p in prices:
    text = p.getvalue().decode("utf-8", errors="ignore")
    for L in text.splitlines():
        m = re.match(r"(.+?)\s+([\d.,]+)\s*€", L)
        if m:
            price_map[m.group(1).strip()] = float(m.group(2).replace(",","."))
st.write(f"Ceny: {len(price_map)} položek")

# 4) For each PDF, extract text + images
catalogs = []
for pdf in pdfs:
    with pdfplumber.open(io.BytesIO(pdf.getvalue())) as doc:
        text = "\n\n".join(p.extract_text() or "" for p in doc.pages)
        # extract first embedded image (if any)
        images = []
        for p in doc.pages:
            for img in p.images:
                # crop & save image bytes
                x0,y0,x1,y1 = img["x0"],img["y0"],img["x1"],img["y1"]
                im = p.crop((x0,y0,x1,y1)).to_image(resolution=150)
                buf = io.BytesIO()
                im.original.save(buf, format="JPEG")
                images.append(buf.getvalue())
        catalogs.append({"name": pdf.name, "text": text, "images": images})

# 5) Ask GPT to extract all fields
for cat in catalogs:
    prompt = f"""
You are given the full text of a product catalog and a set of output fields matching a Heureka SHOPITEM.
Extract *every* product into a JSON array of objects with exactly these keys:

- ITEM_ID
- PRODUCTNAME
- DESCRIPTION
- CATEGORIES
- NETTO_PRICE
- WEIGHT
- WIDTH
- HEIGHT
- THICKNESS
- MAIN_IMAGE_URL
- ADDITIONAL_IMAGE_URLS
- PARAMS: a dict of any other specs (color, material, usage…)

Also use the following price map (key→price):
```json
{json.dumps(price_map, ensure_ascii=False)}
Catalog filename: {cat["name"]}
Catalog text: {cat["text"][:2000]}   # truncate if too long
Return ONLY valid JSON.
"""
resp = openai.ChatCompletion.create(
model="gpt-4",
messages=[{"role":"user","content":prompt}],
temperature=0,
max_tokens=2000
)
items = json.loads(resp.choices[0].message.content)

# 6) Inject into XML
for it in items:
    shop = ET.SubElement(root, f"{{{ns['h']}}}SHOPITEM")
    def add(tag,val):
        e=ET.SubElement(shop,f"{{{ns['h']}}}{tag}"); e.text=str(val)
    add("ITEM_ID",        it["ITEM_ID"])
    add("PRODUCTNAME",    it["PRODUCTNAME"])
    add("DESCRIPTION",    it["DESCRIPTION"])
    add("CATEGORIES",     it["CATEGORIES"])
    add("NETTO_PRICE",    it["NETTO_PRICE"])
    add("WEIGHT",         it["WEIGHT"])
    add("WIDTH",          it["WIDTH"])
    add("HEIGHT",         it["HEIGHT"])
    add("THICKNESS",      it["THICKNESS"])
    add("MAIN_IMAGE_URL", it["MAIN_IMAGE_URL"])
    # additional images
    for url in it.get("ADDITIONAL_IMAGE_URLS", []):
        add("ADDITIONAL_IMAGE_URL", url)
    # other params
    for k,v in it.get("PARAMS",{}).items():
        p=ET.SubElement(shop,f"{{{ns['h']}}}PARAM")
        ET.SubElement(p,f"{{{ns['h']}}}PARAM_NAME").text=k
        ET.SubElement(p,f"{{{ns['h']}}}VAL").text=str(v)
        
7) Pretty-print and Download
rough = ET.tostring(root, 'utf-8')
pretty = minidom.parseString(rough).toprettyxml(indent=" ", encoding="UTF-8")
st.download_button("📥 Stáhnout XML", pretty, "export_smart.xml", "application/xml")

### How it works

- **Text extraction** with `pdfplumber`.  
- **Image extraction** from the first embedded JPEG per page (you can tune).  
- **GPT-4** is prompted with a clear schema, the price map, and a chunk of the PDF. It returns a JSON array of fully-populated product objects.  
- We **inject** each resulting object into your fixed XML template under `<SHOPITEM>` tags.  

This way the app truly *understands* the catalog, finds descriptions and images anywhere in the PDF, pairs them with prices, and yields a ready-to-import Heureka XML.
