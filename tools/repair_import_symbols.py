#!/usr/bin/env python3
"""Normalize the project's imported KiCad symbols without changing pin numbers."""

from __future__ import annotations

import re
import sys
from pathlib import Path


LIB = Path(__file__).resolve().parents[1] / "pcbgolf.kicad_sym"
TARGETS = (
    "74HC4067BQ_118",
    "AON2812",
    "APG015SURKKC-TT",
    "APG015ZGC_S-5MAV",
    "APHHS1005LCGCK",
    "APTB1612ESGC-F01",
    "AW9523BTQR",
    "DMP3026SFDF-7",
    "LT3083IDF#TRPBF",
    "STM32H503EBY6TR",
    "TLV76733DRVR",
    "TMUX1204DQAR",
    "XL-1010RGBC-WS2812B",
)


def balanced(source: str, start: int) -> tuple[int, str]:
    depth = 0
    quoted = False
    escaped = False
    for i in range(start, len(source)):
        ch = source[i]
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
                return i + 1, source[start : i + 1]
    raise ValueError(f"Unterminated S-expression at {start}")


def symbol(source: str, name: str) -> tuple[int, int, str]:
    marker = f'\t(symbol "{name}"'
    start = source.index(marker)
    end, data = balanced(source, start + 1)
    return start, end, data


def pin_map(data: str) -> list[tuple[str, str, str]]:
    found = []
    for match in re.finditer(r'\(pin\s+(\w+)\s+\w+', data):
        _, block = balanced(data, match.start())
        number = re.search(r'\(number "([^"]+)"', block)
        name = re.search(r'\(name "([^"]+)"', block)
        if number and name:
            found.append((number.group(1), name.group(1), match.group(1)))
    return found


def report() -> None:
    source = LIB.read_text()
    for name in TARGETS:
        _, _, data = symbol(source, name)
        pins = pin_map(data)
        print(f"{name} ({len(pins)} pins): " + ", ".join(f"{n}:{label}/{type_}" for n, label, type_ in pins))


def quote(value: str) -> str:
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'


def old_properties(data: str) -> list[tuple[str, str]]:
    found = []
    for match in re.finditer(r'\(property\s+"', data):
        _, prop = balanced(data, match.start())
        head = re.match(r'\(property\s+"([^"]+)"\s+"((?:\\.|[^"])*)"', prop)
        if head:
            found.append((head.group(1), head.group(2)))
    return found


def property_text(key: str, value: str, y: float, visible: bool) -> str:
    return (f'    (property {quote(key)} {quote(value)} (at 0 {y:.3f} 0)'
            f' (effects (font (size 1.27 1.27))' + ('' if visible else ' (hide yes)') + '))')


def electric_type(part: str, number: str, label: str) -> str:
    if part in {"AON2812", "DMP3026SFDF-7", "APG015SURKKC-TT",
                "APG015ZGC_S-5MAV", "APHHS1005LCGCK", "APTB1612ESGC-F01"}:
        return "passive"
    if part == "74HC4067BQ_118":
        if label in {"VCC", "GND"}:
            return "power_in"
        return "bidirectional" if label.startswith("Y") or label == "Z" else "input"
    if part == "AW9523BTQR":
        if label in {"VCC", "GND"}:
            return "power_in"
        if label.startswith("P0_") or label.startswith("P1_") or label == "SDA":
            return "bidirectional"
        return "output" if label == "INTN" else "input"
    if part == "LT3083IDF#TRPBF":
        if label == "OUT":
            return "power_out"
        if label in {"IN", "VCONTROL"}:
            return "power_in"
        return "input"
    if part == "STM32H503EBY6TR":
        if label.startswith("VDD") or label.startswith("VSS"):
            return "power_in"
        if label == "VCAP":
            return "power_out"
        if label in {"BOOT0", "NRST"}:
            return "input"
        return "bidirectional"
    if part == "TLV76733DRVR":
        if label == "OUT":
            return "power_out"
        if label in {"IN", "GND"}:
            return "power_in"
        if number == "7":
            return "passive"
        return "input"
    if part == "TMUX1204DQAR":
        if label in {"VDD", "GND"}:
            return "power_in"
        return "input" if label in {"A0", "A1", "EN"} else "bidirectional"
    if part == "XL-1010RGBC-WS2812B":
        if label in {"VDD", "GND"}:
            return "power_in"
        return "input" if label == "DIN" else "output"
    raise ValueError(part)


def pin_text(number: str, label: str, type_: str, x: float, y: float, angle: int) -> str:
    return (f'      (pin {type_} line (at {x:.3f} {y:.3f} {angle}) (length 2.54)'
            f' (name {quote(label)} (effects (font (size 1.27 1.27))))'
            f' (number {quote(number)} (effects (font (size 1.27 1.27)))))')


def line(points: list[tuple[float, float]], width: float = 0.254) -> str:
    pts = ' '.join(f'(xy {x:.3f} {y:.3f})' for x, y in points)
    return f'      (polyline (pts {pts}) (stroke (width {width}) (type default)) (fill (type none)))'


def rectangle(x1: float, y1: float, x2: float, y2: float) -> str:
    return (f'      (rectangle (start {x1:.3f} {y1:.3f}) (end {x2:.3f} {y2:.3f})'
            ' (stroke (width 0.254) (type default)) (fill (type background)))')


def text_shape(text: str, x: float, y: float, size: float = 1.27) -> str:
    return f'      (text {quote(text)} (at {x:.3f} {y:.3f} 0) (effects (font (size {size} {size}))))'


def box_body(part: str, pins: list[tuple[str, str, str]]) -> tuple[str, str, float]:
    by_number = {number: (label, type_) for number, label, type_ in pins}
    layouts: dict[str, tuple[list[str], list[str]]] = {
        "74HC4067BQ_118": (
            [str(n) for n in range(9, 1, -1)] + [str(n) for n in range(23, 15, -1)],
            ["1", "10", "11", "14", "13", "15", "24", "25", "12"]),
        "AON2812": (["2", "1", "5", "4"], ["6", "3"]),
        "AW9523BTQR": ([str(n) for n in range(5, 9)] + [str(n) for n in range(10, 14)] +
                       ["18", "24", "19", "20", "23", "9"],
                      [str(n) for n in range(1, 5)] + [str(n) for n in range(14, 18)] +
                       ["22", "21", "25"]),
        "DMP3026SFDF-7": (["3", "4", "8"], ["1", "2", "5", "6", "7"]),
        "LT3083IDF#TRPBF": (["9", "10", "11", "12", "7", "8", "6"],
                            ["1", "2", "3", "4", "5", "13"]),
        "STM32H503EBY6TR": (
            ["E5", "E4", "E3", "C1", "D1", "B1", "A1", "D2", "C2", "A2", "E2", "C3"],
            ["A3", "D5", "E1", "D3", "C4", "B3", "B4", "A4", "A5", "B5", "C5", "B2", "D4"]),
        "TLV76733DRVR": (["6", "4", "3", "5"], ["1", "2", "7"]),
        "TMUX1204DQAR": (["2", "9", "4", "7", "3"], ["8", "1", "10", "5", "6"]),
        "XL-1010RGBC-WS2812B": (["4", "3"], ["1", "2"]),
    }
    left, right = layouts[part]
    if set(left + right) != set(by_number) or len(left + right) != len(pins):
        raise ValueError(f"layout pin mismatch for {part}")
    max_left = max(len(by_number[n][0]) for n in left)
    max_right = max(len(by_number[n][0]) for n in right)
    half_width = max(11.43, 0.635 * (max_left + max_right) + 5.08)
    rows = max(len(left), len(right))
    half_height = max(7.62, (rows + 1) * 1.27)
    graphics = [rectangle(-half_width, half_height, half_width, -half_height)]
    if part == "AON2812":
        graphics.append(line([(-half_width, 0), (half_width, 0)], 0.127))
        graphics.append(text_shape("N1", 0, 3.81))
        graphics.append(text_shape("N2", 0, -3.81))
    elif part == "DMP3026SFDF-7":
        graphics.append(text_shape("P-MOS", 0, 0))
    elif part == "XL-1010RGBC-WS2812B":
        graphics.append(text_shape("RGB", 0, 0))
    elif part == "TMUX1204DQAR":
        graphics.append(text_shape("4:1 MUX", 0, 0))
    elif part == "74HC4067BQ_118":
        graphics.append(text_shape("16:1 MUX", 0, 0))
    pins_out = []
    for side, numbers in (("left", left), ("right", right)):
        for i, number in enumerate(numbers):
            label, _ = by_number[number]
            if part == "AON2812":
                label = {"1": "S1", "2": "G1", "3": "D2",
                         "4": "S2", "5": "G2", "6": "D1"}[number]
            if part == "LT3083IDF#TRPBF" and number == "13":
                label = "OUT"
            if part == "TLV76733DRVR" and number == "2":
                label = "SNS"
            if part == "TLV76733DRVR" and number == "7":
                label = "EP/GND"
            y = (len(numbers) - 1) * 1.27 - i * 2.54
            x = -half_width - 2.54 if side == "left" else half_width + 2.54
            angle = 0 if side == "left" else 180
            pins_out.append(pin_text(number, label, electric_type(part, number, label), x, y, angle))
    return '\n'.join(graphics), '\n'.join(pins_out), half_height


def led_graphics(y: float = 0) -> list[str]:
    # Cathode left, anode right, matching Kingbright pin 1 K / pin 2 A.
    return [
        line([(-1.27, y - 1.27), (-1.27, y + 1.27)]),
        line([(1.27, y - 1.27), (1.27, y + 1.27), (-1.27, y), (1.27, y - 1.27)]),
        line([(-1.27, y), (-3.81, y)], 0),
        line([(1.27, y), (3.81, y)], 0),
        line([(-2.54, y + 1.27), (-3.81, y + 2.54)], 0),
        line([(-1.27, y + 1.27), (-2.54, y + 2.54)], 0),
        line([(-3.81, y + 2.54), (-3.05, y + 2.54), (-3.81, y + 1.78)], 0),
        line([(-2.54, y + 2.54), (-1.78, y + 2.54), (-2.54, y + 1.78)], 0),
    ]


def led_body(part: str, pins: list[tuple[str, str, str]]) -> tuple[str, str, float]:
    if part == "APTB1612ESGC-F01":
        shapes = led_graphics(5.08) + led_graphics(-5.08)
        shapes += [text_shape("R", 0, 8.89), text_shape("G", 0, -8.89)]
        positions = {"1": (6.35, 5.08, 180), "2": (-6.35, 5.08, 0),
                     "3": (6.35, -5.08, 180), "4": (-6.35, -5.08, 0)}
        half_height = 10.16
    else:
        shapes = led_graphics(0)
        positions = {"1": (-6.35, 0, 0), "2": (6.35, 0, 180)}
        half_height = 3.81
    out_pins = [pin_text(n, label, "passive", *positions[n]) for n, label, _ in pins]
    return '\n'.join(shapes), '\n'.join(out_pins), half_height


def aon_body(source: str) -> str:
    """Reuse the QS5K2 artwork, but leave AON2812's sources independent."""
    _, _, reference = symbol(source, "NFET-DUAL-COMMON-SOURCE-QS5K2")
    marker = '(symbol "NFET-DUAL-COMMON-SOURCE-QS5K2_1_0"'
    start = reference.index(marker)
    _, drawing = balanced(reference, start)
    body = drawing[drawing.index('\n') + 1:-1].rstrip()
    removals = []
    for match in re.finditer(r'\(pin\s+|\(polyline\s+', body):
        end, shape = balanced(body, match.start())
        if shape.startswith('(pin ') or re.search(
                r'\(xy\s+0\s+-5\.08\)\s+\(xy\s+10\.16\s+-5\.08\)', shape):
            removals.append((match.start(), end))
    if len(removals) != 6:
        raise ValueError("QS5K2 artwork no longer has five pins and one source bridge")
    for start, end in reversed(removals):
        body = body[:start] + body[end:]
    positions = {
        "1": ("S1", 0, -7.62, 90),
        "2": ("G1", -7.62, 0, 0),
        "3": ("D2", 10.16, 5.08, 270),
        "4": ("S2", 10.16, -7.62, 90),
        "5": ("G2", 17.78, 0, 180),
        "6": ("D1", 0, 5.08, 270),
    }
    pins = [pin_text(number, label, "passive", x, y, angle)
            .replace('(size 1.27 1.27)', '(size 0 0)')
            for number, (label, x, y, angle) in positions.items()]
    return body + '\n' + '\n'.join(pins)


def rebuild(name: str, data: str, source: str) -> str:
    pins = pin_map(data)
    if name == "AON2812":
        graphics, pin_data, half_height = "", aon_body(source), 7.62
    elif name in {"APG015SURKKC-TT", "APG015ZGC_S-5MAV",
                "APHHS1005LCGCK", "APTB1612ESGC-F01"}:
        graphics, pin_data, half_height = led_body(name, pins)
    else:
        graphics, pin_data, half_height = box_body(name, pins)
    props = old_properties(data)
    if len(props) < 4:
        raise ValueError(f"missing properties for {name}")
    prop_text = []
    for key, value in props:
        if key == "Reference":
            if name in {"APG015SURKKC-TT", "APG015ZGC_S-5MAV",
                        "APHHS1005LCGCK", "APTB1612ESGC-F01"}:
                value = "D"
            prop_text.append(property_text(key, value, half_height + 3.81, True))
        elif key == "Value":
            prop_text.append(property_text(key, value, -half_height - 3.81, True))
        else:
            prop_text.append(property_text(key, value, 0, False))
    pin_names = '(pin_names (offset 0.762)' + (' (hide yes)' if name in {"APG015SURKKC-TT", "APG015ZGC_S-5MAV", "APHHS1005LCGCK"} else '') + ')'
    if name == "AON2812":
        units = f'    (symbol {quote(name + "_1_0")}\n{pin_data}\n    )\n'
    else:
        units = (f'    (symbol {quote(name + "_0_1")}\n{graphics}\n    )\n'
                 + f'    (symbol {quote(name + "_1_1")}\n{pin_data}\n    )\n')
    return ('\t(symbol ' + quote(name) + '\n'
            f'    {pin_names}\n'
            '    (exclude_from_sim no) (in_bom yes) (on_board yes) (in_pos_files yes)\n'
            '    (duplicate_pin_numbers_are_jumpers no)\n'
            + '\n'.join(prop_text) + '\n'
            + units
            + '    (embedded_fonts no)\n\t)')


def apply() -> None:
    source = LIB.read_text()
    original_pins = {}
    replacements = []
    for name in TARGETS:
        start, end, old = symbol(source, name)
        original_pins[name] = {n for n, _, _ in pin_map(old)}
        replacements.append((start, end, rebuild(name, old, source)))
    for start, end, new in sorted(replacements, reverse=True):
        source = source[:start] + new + source[end:]
    for name in TARGETS:
        _, _, updated = symbol(source, name)
        if {n for n, _, _ in pin_map(updated)} != original_pins[name]:
            raise ValueError(f"pin number changed for {name}")
    LIB.write_text(source)


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--report":
        report()
    elif len(sys.argv) == 2 and sys.argv[1] == "--apply":
        apply()
    else:
        raise SystemExit("Use --report or --apply")
