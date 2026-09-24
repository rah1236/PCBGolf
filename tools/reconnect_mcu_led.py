#!/usr/bin/env python3
"""Reconnect the resized WS2812 indicator and its series links."""

import re
import shutil
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILE = ROOT / 'pcbgolf_2.kicad_sch'


def balanced(text, start):
    depth = 0
    quoted = escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if quoted:
            if escaped:
                escaped = False
            elif ch == '\\':
                escaped = True
            elif ch == '"':
                quoted = False
        elif ch == '"':
            quoted = True
        elif ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
            if depth == 0:
                return i + 1
    raise ValueError(start)


def label(name, x, y, angle=0):
    just = ' (justify right)' if angle == 180 else ''
    return (f'(global_label "{name}" (shape bidirectional) (at {x:g} {y:g} {angle}) '
            f'(fields_autoplaced yes) (effects (font (size 1.27 1.27)){just}) '
            f'(uuid "{uuid.uuid4()}"))')


def main():
    backup = ROOT / 'build/backups/pre-mcu-led-repair'
    backup.mkdir(parents=True, exist_ok=True)
    shutil.copy2(FILE, backup / FILE.name)
    text = FILE.read_text()
    # Remove the power label left behind at the previous LED footprint.
    for match in re.finditer(r'\(global_label "\+3V3"', text):
        start, end = match.start(), balanced(text, match.start())
        if re.search(r'\(at 223\.52 201\.93 0\)', text[start:end]):
            text = text[:start] + text[end:]
            break
    additions = [
        label('GND', 213.36, 191.77, 180),
        label('LED_GND', 223.52, 191.77),
        label('LED_GND', 227.33, 198.12, 180),
        label('LED_DIN', 227.33, 195.58, 180),
        label('LED_DIN', 256.54, 201.93),
        label('LED_DOUT_RAW', 255.27, 195.58),
        label('LED_DOUT_RAW', 256.54, 191.77),
        label('+3V3', 255.27, 198.12),
    ]
    marker = text.index('(sheet_instances')
    FILE.write_text(text[:marker] + '\n' + '\n'.join(additions) + '\n' + text[marker:])


if __name__ == '__main__':
    main()
