#!/usr/bin/env python3
import html
import re
from pathlib import Path

import certifi
import requests


MAJORS_URL = "https://www.handbooks.uwa.edu.au/majors"
OUTPUT_FILE = Path("data/uwa_majors.txt")
MAJOR_LINK_PATTERN = re.compile(r'href="/majors/[^"]+"[^>]*>([^<]+)</a>', re.IGNORECASE)


response = requests.get(MAJORS_URL, timeout=30, verify=certifi.where())
response.raise_for_status()
page_text = response.text

majors = set()
for match in MAJOR_LINK_PATTERN.findall(page_text):
    label = html.unescape(match)
    label = re.sub(r"\s+", " ", label).strip()
    if label:
        majors.add(label)

sorted_majors = sorted(majors, key=str.lower)

OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
OUTPUT_FILE.write_text("\n".join(sorted_majors) + "\n", encoding="utf-8")

print(f"Extracted {len(sorted_majors)} majors to {OUTPUT_FILE}")
