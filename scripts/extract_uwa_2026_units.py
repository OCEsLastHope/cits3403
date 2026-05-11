#!/usr/bin/env python3
import re
from pathlib import Path

import certifi
import requests


UNITS_URL = "https://www.handbooks.uwa.edu.au/units"
OUTPUT_FILE = Path("data/uwa_2026_unit_codes.txt")
CODE_PATTERN = re.compile(r"\b[A-Z]{4}\d{4}\b")


response = requests.get(UNITS_URL, timeout=30, verify=certifi.where())
response.raise_for_status()
page_text = response.text
codes = sorted(set(CODE_PATTERN.findall(page_text)))

OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
OUTPUT_FILE.write_text("\n".join(codes) + "\n", encoding="utf-8")

print(f"Extracted {len(codes)} codes to {OUTPUT_FILE}")
