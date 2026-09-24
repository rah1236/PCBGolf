#!/usr/bin/env python3
"""Remove disconnected power markers left at prior symbol locations."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS = {
    'pcbgolf_2.kicad_sch': '#GND014',
    'pcbgolf_4.kicad_sch': '#PWR056',
}


def balanced(text, start):
    n = 0
    quote = escape = False
    for i in range(start, len(text)):
        c = text[i]
        if quote:
            if escape:
                escape = False
            elif c == '\\':
                escape = True
            elif c == '"':
                quote = False
        elif c == '"':
            quote = True
        elif c == '(':
            n += 1
        elif c == ')':
            n -= 1
            if n == 0:
                return i + 1
    raise ValueError(start)


for filename, ref in TARGETS.items():
    path = ROOT / filename
    text = path.read_text()
    for match in re.finditer(r'\(lib_id ', text):
        start = text.rfind('(symbol\n', 0, match.start())
        if start < 0:
            continue
        end = balanced(text, start)
        if re.search(r'\(property "Reference" "' + re.escape(ref) + r'"', text[start:end]):
            path.write_text(text[:start] + text[end:])
            print('Removed', ref, 'from', filename)
            break
