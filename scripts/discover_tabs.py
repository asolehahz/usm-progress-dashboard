"""Discover Google Sheet tab names and GIDs from the edit page HTML."""

import re
import urllib.request

SHEET_ID = "1-0DFZT-jrzdUkEfjS1v0S2Z13qSEjRcEGp5b6DbFp1o"
url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit"

html = urllib.request.urlopen(url).read().decode("utf-8", errors="ignore")

# Embedded waffle metadata: [index,0,"GID",[...,["INDUK"],...
pattern = r'\[\d+,0,"(\d+)",\[\{"1":\[\[0,0,"([^"]+)"'
for m in re.finditer(pattern, html):
    print(f'"{m.group(2)}": "{m.group(1)}",')
