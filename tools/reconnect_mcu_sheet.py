#!/usr/bin/env python3
"""Reconnect placed compact MCU symbols to their intended named nets."""

from __future__ import annotations

import re
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "build/vendor"))
import sexpdata as sx


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "pcbgolf_2.kicad_sch"


def children(node, name):
    return [item for item in node if isinstance(item, list) and str(item[0]) == name]


def balanced(source, start):
    depth = 0
    quoted = escaped = False
    for pos in range(start, len(source)):
        ch = source[pos]
        if quoted:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                quoted = False
        elif ch == '"':
            quoted = True
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return pos + 1
    raise ValueError(start)


def block_ranges(source, kind):
    for match in re.finditer(r"\(" + kind + r"\s", source):
        start = match.start()
        end = balanced(source, start)
        yield start, end, source[start:end]


MCU = {
    "A1": "STM_D_P", "B1": "STM_D_N", "B3": "CAN_RX", "B4": "CAN_TX",
    "A4": "HUB_SDA", "A5": "HUB_SCL", "C4": "SD_D0", "A2": "SD_D3",
    "E4": "SD_CLK", "E3": "SD_CMD", "E5": "SENSE_MUX", "C1": "LED_DATA",
    "D1": "BTN", "D2": "SWDIO", "C2": "SWCLK", "D3": "IOX_INT0",
    "E1": "IOX_INT1", "A3": "BTN", "D5": "NRST", "B2": "+3V3",
    "D4": "+3V3", "C3": "GND", "E2": "VCAP", "B5": "LSE_IN_SPARE",
    "C5": "LSE_OUT_SPARE",
}
AW1 = {
    "1": "CH1_SBU1_IGN", "2": "CH1_SBU1_RELAY", "3": "CH1_SBU2_IGN",
    "4": "CH1_SBU2_RELAY", "5": "CH2_SBU1_IGN", "6": "CH2_SBU1_RELAY",
    "7": "CH2_SBU2_IGN", "8": "CH2_SBU2_RELAY", "10": "CH3_SBU1_IGN",
    "11": "CH3_SBU1_RELAY", "12": "CH3_SBU2_IGN", "13": "CH3_SBU2_RELAY",
    "14": "CH4_SBU1_IGN", "15": "CH4_SBU1_RELAY", "16": "CH4_SBU2_IGN",
    "17": "CH4_SBU2_RELAY", "9": "GND", "25": "GND", "21": "+3V3",
    "19": "HUB_SCL", "20": "HUB_SDA", "18": "GND", "24": "GND",
    "22": "IOX_INT0", "23": "+3V3",
}
AW2 = {
    "1": "CH1_PWR_EN", "2": "CH2_PWR_EN", "3": "CH3_PWR_EN", "4": "CH4_PWR_EN",
    "5": "CAN0_EN", "6": "CAN1_EN", "7": "CAN2_EN", "8": "CAN3_EN",
    "10": "SENSE_SEL0", "11": "SENSE_SEL1", "12": "SENSE_SEL2",
    "13": "SENSE_SEL3", "14": "CAN_SEL0", "15": "CAN_SEL1",
    "9": "GND", "25": "GND", "21": "+3V3", "19": "HUB_SCL",
    "20": "HUB_SDA", "18": "+3V3", "24": "GND", "22": "IOX_INT1",
    "23": "+3V3", "16": "IOX_SPARE0", "17": "IOX_SPARE1",
}
MUX = dict(zip(
    ["9", "8", "7", "6", "5", "4", "3", "2", "23", "22", "21", "20"],
    ["CH2_SBU2_ADC", "CH4_SBU2_ADC", "CH2_SBU1_ADC", "CH4_SBU1_ADC",
     "CH3_SBU1_ADC", "CH3_SBU2_ADC", "CH1_SBU1_ADC", "CH1_SBU2_ADC",
     "CH1_IMON", "CH2_IMON", "CH3_IMON", "CH4_IMON"],
))
MUX.update({
    "1": "SENSE_MUX", "10": "SENSE_SEL0", "11": "SENSE_SEL1",
    "14": "SENSE_SEL2", "13": "SENSE_SEL3", "15": "GND", "12": "GND",
    "24": "+3V3", "25": "+3V3", "19": "SENSE_SPARE12",
    "18": "SENSE_SPARE13", "17": "SENSE_SPARE14", "16": "SENSE_SPARE15",
})
NETS = {"U3": MCU, "U4": AW1, "U6": AW2, "U5": MUX}


def old_component_label(name, x, y):
    if abs(x - 90.17) < .02 or abs(x - 135.89) < .02:
        return 160 <= y <= 200
    if abs(x - 106.68) < .02 or abs(x - 147.32) < .02:
        return 57 <= y <= 78
    if abs(x - 214.63) < .02 or abs(x - 255.27) < .02:
        return 60 <= y <= 80
    if x in (119.38, 121.92, 227.33, 229.87) and 53 <= y <= 55:
        return name in ("HUB_SCL", "HUB_SDA")
    if abs(x - 187.96) < .02 and 126 <= y <= 166:
        return True
    if abs(x - 228.6) < .02 and abs(y - 146.05) < .02:
        return True
    if x in (198.12, 200.66, 203.2, 205.74) and abs(y - 170.18) < .02:
        return True
    return name == "GND" and abs(x - 210.82) < .02 and abs(y - 191.77) < .02


def label(name, x, y, angle):
    justify = " (justify right)" if angle == 180 else ""
    return (f'(global_label "{name}" (shape bidirectional) (at {x:g} {y:g} {angle}) '
            f'(fields_autoplaced yes) (effects (font (size 1.27 1.27)){justify}) '
            f'(uuid "{uuid.uuid4()}"))')


def wire(x1, y1, x2, y2):
    return (f'(wire (pts (xy {x1:g} {y1:g}) (xy {x2:g} {y2:g})) '
            f'(stroke (width 0) (type default)) (uuid "{uuid.uuid4()}"))')


def main():
    source = PATH.read_text()
    tree = sx.loads(source)
    lib = {item[1]: item for item in children(children(tree, "lib_symbols")[0], "symbol")}
    placed = {}
    for item in children(tree, "symbol"):
        ref = next((p[2] for p in children(item, "property") if p[1] == "Reference"), None)
        if ref in NETS:
            placed[ref] = item
    assert set(placed) == set(NETS)
    edits = []
    removed = []
    for start, end, block in block_ranges(source, "global_label"):
        item = sx.loads(block)
        x, y = children(item, "at")[0][1:3]
        if old_component_label(item[1], x, y):
            removed.append(item[1])
            edits.append((start, end, ""))
    additions = []
    for ref, nets in NETS.items():
        instance = placed[ref]
        ox, oy, orientation = children(instance, "at")[0][1:]
        assert orientation == 0
        symbol = lib[children(instance, "lib_id")[0][1]]
        pins = {children(pin, "number")[0][1]: pin
                for unit in children(symbol, "symbol") for pin in children(unit, "pin")}
        assert set(nets) == set(pins), (ref, set(nets) ^ set(pins))
        for number, net in nets.items():
            px, py, pa = children(pins[number], "at")[0][1:]
            x, y = round(ox + px, 4), round(oy - py, 4)
            if pa == 180:
                far_x = round(x + 20.32, 4)
                additions.append(wire(x, y, far_x, y))
                additions.append(label(net, far_x, y, 0))
            else:
                additions.append(label(net, x, y, 180))
    for start, end, replacement in sorted(edits, reverse=True):
        source = source[:start] + replacement + source[end:]
    marker = source.index("(sheet_instances")
    source = source[:marker] + "\n" + "\n".join(additions) + "\n" + source[marker:]
    PATH.write_text(source)
    print(f"Replaced {len(removed)} stale labels with {len(additions)} pin labels")


if __name__ == "__main__":
    main()
