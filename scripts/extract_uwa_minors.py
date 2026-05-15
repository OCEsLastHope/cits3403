#!/usr/bin/env python3
import html
import re
from pathlib import Path

import certifi
import requests


MINORS_URL = "https://www.handbooks.uwa.edu.au/minors"
OUTPUT_FILE = Path("data/uwa_minors.txt")
MINOR_LINK_PATTERN = re.compile(r'href="/minors/[^"]+"[^>]*>([^<]+)</a>', re.IGNORECASE)


response = requests.get(MINORS_URL, timeout=30, verify=certifi.where())
response.raise_for_status()
page_text = response.text

minors = set()
for match in MINOR_LINK_PATTERN.findall(page_text):
    label = html.unescape(match)
    label = re.sub(r"\s+", " ", label).strip()
    if label:
        minors.add(label)

sorted_minors = sorted(minors, key=str.lower)

OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
OUTPUT_FILE.write_text("\n".join(sorted_minors) + "\n", encoding="utf-8")

print(f"Extracted {len(sorted_minors)} minors to {OUTPUT_FILE}")
