#!/usr/bin/env python3
"""Reconnect changed regulator symbols to existing power buses."""

from pathlib import Path
import shutil
import uuid

ROOT = Path(__file__).resolve().parents[1]
FILE = ROOT / 'pcbgolf.kicad_sch'


def wire(x1, y1, x2, y2):
    return (f'(wire (pts (xy {x1:g} {y1:g}) (xy {x2:g} {y2:g})) '
            f'(stroke (width 0) (type default)) (uuid "{uuid.uuid4()}"))')


def label(name, x, y, angle=0):
    justify = ' (justify right)' if angle == 180 else ''
    return (f'(global_label "{name}" (shape bidirectional) (at {x:g} {y:g} {angle}) '
            f'(fields_autoplaced yes) (effects (font (size 1.27 1.27)){justify}) '
            f'(uuid "{uuid.uuid4()}"))')


def junction(x, y):
    return f'(junction (at {x:g} {y:g}) (diameter 0) (color 0 0 0 0) (uuid "{uuid.uuid4()}"))'


def main():
    backup = ROOT / 'build/backups/pre-connection-repair'
    backup.mkdir(parents=True, exist_ok=True)
    shutil.copy2(FILE, backup / FILE.name)
    blocks = []
    # LT3083: all IN and VCONTROL pins share the existing +12 V rail.
    for y in (35.56, 38.10, 40.64, 43.18, 45.72, 48.26):
        blocks.append(wire(151.13, y, 151.765, y))
        blocks.append(junction(151.13, y))
    # All OUT pins share the existing +5 V rail. The SET pin is tied to
    # that rail while R3 sets the 5 V output through its 100 kOhm path to GND.
    for y in (36.83, 39.37, 41.91, 44.45, 46.99, 49.53):
        blocks.append(wire(180.975, y, 181.61, y))
        blocks.append(junction(181.61, y))
    blocks.append(wire(181.61, 43.18, 181.61, 48.26))
    blocks.append(wire(181.61, 48.26, 181.61, 49.53))
    blocks.append(label('+5V', 151.765, 50.8, 180))
    # TLV767: +5 V input, resistor-pulled enable, grounded exposed pad,
    # and sense fed from the same +3.3 V output bus.
    blocks.extend([
        label('+5V', 72.39, 113.03, 180),
        label('LDO_EN', 72.39, 115.57, 180),
        label('LDO_EN', 68.58, 121.92),
        label('GND', 72.39, 118.11, 180),
        label('GND', 72.39, 120.65, 180),
        label('GND', 100.33, 119.38),
        wire(100.33, 114.3, 101.6, 114.3),
        wire(100.33, 116.84, 101.6, 116.84),
        wire(101.6, 114.3, 101.6, 116.84),
    ])
    text = FILE.read_text()
    marker = text.index('(sheet_instances')
    FILE.write_text(text[:marker] + '\n' + '\n'.join(blocks) + '\n' + text[marker:])


if __name__ == '__main__':
    main()
