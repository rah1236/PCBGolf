#!/usr/bin/env python3
"""Reconnect CAN RX mux pins after compact symbol geometry changed."""

import re
import shutil
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILE = ROOT / 'pcbgolf_4.kicad_sch'


def balanced(text, start):
    depth = 0
    quoted = escaped = False
    for i in range(start, len(text)):
        c = text[i]
        if quoted:
            if escaped:
                escaped = False
            elif c == '\\':
                escaped = True
            elif c == '"':
                quoted = False
        elif c == '"':
            quoted = True
        elif c == '(':
            depth += 1
        elif c == ')':
            depth -= 1
            if depth == 0:
                return i + 1
    raise ValueError(start)


def label(name, x, y, angle=0):
    just = ' (justify right)' if angle == 180 else ''
    return (f'(global_label "{name}" (shape bidirectional) (at {x:g} {y:g} {angle}) '
            f'(fields_autoplaced yes) (effects (font (size 1.27 1.27)){just}) '
            f'(uuid "{uuid.uuid4()}"))')


def wire(x1, y1, x2, y2):
    return (f'(wire (pts (xy {x1:g} {y1:g}) (xy {x2:g} {y2:g})) '
            f'(stroke (width 0) (type default)) (uuid "{uuid.uuid4()}"))')


def main():
    backup = ROOT / 'build/backups/pre-can-mux-repair'
    backup.mkdir(parents=True, exist_ok=True)
    shutil.copy2(FILE, backup / FILE.name)
    text = FILE.read_text()
    edits = []
    for match in re.finditer(r'\(global_label ', text):
        a, b = match.start(), balanced(text, match.start())
        block = text[a:b]
        pos = re.search(r'\(at ([\d.]+) ([\d.]+)', block)
        if not pos:
            continue
        x, y = float(pos[1]), float(pos[2])
        if (abs(x - 26.67) < .02 and 177 <= y <= 194 or
                abs(x - 57.15) < .02 and abs(y - 185.42) < .02 or
                x in (36.83, 41.91) and abs(y - 198.12) < .02):
            edits.append((a, b))
    for a, b in sorted(edits, reverse=True):
        text = text[:a] + text[b:]
    nets = {
        2: ('CAN0_RX', 27.94, 180.34),
        9: ('CAN1_RX', 27.94, 182.88),
        4: ('CAN2_RX', 27.94, 185.42),
        7: ('CAN3_RX', 27.94, 187.96),
        3: ('GND', 27.94, 190.5),
        8: ('CAN_RX', 55.88, 180.34),
        1: ('CAN_SEL0', 55.88, 182.88),
        10: ('CAN_SEL1', 55.88, 185.42),
        5: ('GND', 55.88, 187.96),
        6: ('+3V3', 55.88, 190.5),
    }
    additions = []
    for pin, (net, x, y) in nets.items():
        if x < 41.91:
            additions.append(label(net, x, y, 180))
        else:
            additions.append(wire(x, y, x + 17.78, y))
            additions.append(label(net, x + 17.78, y))
    marker = text.index('(sheet_instances')
    FILE.write_text(text[:marker] + '\n' + '\n'.join(additions) + '\n' + text[marker:])


if __name__ == '__main__':
    main()
