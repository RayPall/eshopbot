#!/usr/bin/env python3
"""
Universal PDF catalog to Heureka XML exporter.

Usage:
    python universal_parser.py <catalog.pdf> <cenik.txt> <output.xml>

This script will:
 1. Parse the price list (cenik) into a mapping key→price
 2. Try to extract a table from the PDF via Camelot
 3. If Camelot finds no tables, fallback to pdfplumber + OpenAI GPT to parse the text
 4. Map the resulting DataFrame into Heureka SHOP XML format and write to output.xml
"""

import sys
import io
import re
import json
import camelot        # pip install camelot-py[cv]
import pdfplumber
import pandas as pd
import openai
import xml.etree.ElementTree as ET
from xml.dom import minidom

# ——— 1) Configure your OpenAI API key ——————————————————————————————
openai.api_key = "YOUR_OPENAI_API_KEY"  # Or set via environment variable

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

Níže je vstupní text z PDF (nebo čistý text v případě selhání tabulkového parseru). Vrať pouze JSON pole, bez dalšího
