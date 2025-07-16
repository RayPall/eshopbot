import io
import re
import json
import camelot        # pip install camelot-py[cv]
import pdfplumber
import pandas as pd
import openai

# ——— 1) Nastavení OpenAI klíče ——————————————————————————————
openai.api_key = "OPENAI_API_KEY"

# ——— 2) Definice sloupců A–U ——————————————————————————————
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

# ——— 3) Základní prompt pro LLM ——————————————————————————
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
    Z libovolného textu (ceník.txt, CSV, TSV) vytáhne mapování
    klíč→cena (float).
    """
    price_map = {}
    for line in raw_text.splitlines():
        # hledáme vzor např. "60x60 - Rettificato    12,25 €"
        m = re.match(r"(.+?)\s+([\d.,]+)\s*€", line)
        if m:
            key = m.group(1).strip()
            price = float(m.group(2).replace(",", "."))
            price_map[key] = price
    return price_map

def parse_pdf_universal(pdf_bytes: bytes, price_map: dict) -> pd.DataFrame:
    """
    1) Zkus camelot na detekci tabulek
    2) Pokud selže, fallback na pdfplumber + LLM podle BASE_PROMPT
    """
    # 1) Camelot
    try:
        tables = camelot.read_pdf(io.BytesIO(pdf_bytes), pages="all", flavor="stream")
        if tables and len(tables) > 0:
            # vyber největší tabulku
            df = max((t.df for t in tables), key=lambda d: d.shape[0])
            df.columns = df.iloc[0]  # první řádek jako hlavičky
            df = df.drop(0).reset_index(drop=True)
            return df
    except Exception:
        pass

    # 2) Fallback: čistý text
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        text = "\n\n".join(p.extract_text() or "" for p in pdf.pages)

    # Sestav prompt
    cols_descr = "\n".join(f"{k}: {v}" for k,v in COLUMNS)
    prompt = BASE_PROMPT.format(cols=cols_descr, data=text)

    resp = openai.chat.completions.create(
        model="gpt-4",
        messages=[{"role":"user","content":prompt}],
        temperature=0,
        max_tokens=2000,
    )
    content = resp.choices[0].message.content.strip()

    # Parse JSON pole
    data = json.loads(content)
    return pd.DataFrame(data)

if __name__ == "__main__":
    # ——— Příklad načtení souborů z disku ——————————————————
    with open("Del-Conca-Lavaredo-Katalog-produktu.pdf", "rb") as f:
        pdf_bytes = f.read()
    raw_cenik = open("cenik.txt", "r", encoding="utf-8").read()

    # ——— Připrav ceník dict ——————————————————————————
    price_map = parse_price_file(raw_cenik)
    print(f"Načteno {len(price_map)} cenových záznamů")

    # ——— Spusť univerzální parser ——————————————————————
    df = parse_pdf_universal(pdf_bytes, price_map)

    # ——— Vypsání výsledku nebo uložení —————————————————————
    print(df.head())
    df.to_excel("vystup_products.xlsx", index=False)
