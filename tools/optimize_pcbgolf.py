#!/usr/bin/env python3
"""Apply the PCBGolf component-size optimization to the KiCad schematics.

This script is intentionally project-specific.  It preserves the existing drawing
layout while replacing the cached symbols and rewiring by pin position.
"""

from __future__ import annotations

import re
import shutil
import uuid
from pathlib import Path

import skip


ROOT = Path(__file__).resolve().parents[1]
GENERATED = Path("/private/tmp/pcbgolf-generated")
USB_LIB = Path("/private/tmp/pcb-edge-usb-c/unpacked")
KICAD_FP = Path("/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints")


def balanced_block(text: str, start: int) -> tuple[int, str]:
    depth = 0
    quoted = False
    escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if quoted:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                quoted = False
            continue
        if ch == '"':
            quoted = True
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i + 1, text[start : i + 1]
    raise ValueError(f"unterminated S-expression at {start}")


def named_symbol_block(text: str, name: str) -> tuple[int, int, str]:
    marker = f'(symbol "{name}"'
    start = text.index(marker)
    end, block = balanced_block(text, start)
    return start, end, block


def placed_symbol_block(text: str, lib_id: str) -> tuple[int, int, str]:
    marker = f'(lib_id "{lib_id}")'
    hit = text.index(marker)
    start = text.rfind("(symbol ", 0, hit)
    if start < 0:
        raise ValueError(f"placed symbol start not found for {lib_id}")
    end, block = balanced_block(text, start)
    return start, end, block


def pin_blocks(symbol: str) -> dict[str, tuple[int, int, str]]:
    found: dict[str, tuple[int, int, str]] = {}
    for match in re.finditer(r"\(pin\s+[^\s()]+\s+[^\s()]+", symbol):
        end, block = balanced_block(symbol, match.start())
        number = re.search(r'\(number "([^"]+)"', block)
        if number:
            found[number.group(1)] = (match.start(), end, block)
    return found


def pin_metadata(symbol: str) -> dict[str, tuple[str, str]]:
    """Return ball -> (pin name, original at expression)."""
    result: dict[str, tuple[str, str]] = {}
    for number, (_, _, block) in pin_blocks(symbol).items():
        name = re.search(r'\(name "([^"]+)"', block)
        at = re.search(r"\(at\s+([^\)]+)\)", block)
        if name and at:
            result[number] = (name.group(1), at.group(1))
    return result


def append_top_level(path: Path, blocks: list[str]) -> None:
    """Insert top-level schematic objects immediately before sheet_instances."""
    text = path.read_text()
    marker = text.index("(sheet_instances")
    text = text[:marker] + "\n" + "\n".join(blocks) + text[marker:]
    path.write_text(text)


def wire_block(start: tuple[float, float], end: tuple[float, float]) -> str:
    return (
        f'(wire (pts (xy {start[0]} {start[1]}) (xy {end[0]} {end[1]})) '
        f'(stroke (width 0) (type default)) (uuid "{uuid.uuid4()}"))'
    )


def global_label_block(name: str, at: tuple[float, float], angle: int = 0) -> str:
    justify = " (justify right)" if angle == 180 else ""
    return (
        f'(global_label "{name}" (shape bidirectional) (at {at[0]} {at[1]} {angle}) '
        f'(fields_autoplaced yes) (effects (font (size 1.27 1.27)){justify}) '
        f'(uuid "{uuid.uuid4()}"))'
    )


def add_symbol_instance(
    path: Path,
    template_lib: str,
    cached_symbol: str,
    new_lib: str,
    reference: str,
    value: str,
    footprint: str,
    datasheet: str,
    at: tuple[float, float],
) -> None:
    text = path.read_text()
    # Cache the project-local symbol in this schematic.
    cache_name = re.search(r'^\(symbol "([^"]+)"', cached_symbol).group(1)
    if f'(symbol "{cache_name}"' not in text:
        lib_start = text.index("(lib_symbols")
        lib_close, _ = balanced_block(text, lib_start)
        lib_end = lib_close - 1
        text = text[:lib_end] + "\n\t" + cached_symbol.replace("\n", "\n\t") + text[lib_end:]

    _, _, placed = placed_symbol_block(text, template_lib)
    placed = re.sub(r'\(lib_id "[^"]+"\)', f'(lib_id "{new_lib}")', placed, count=1)
    placed = re.sub(r"\(at\s+[^\)]+\)", f"(at {at[0]} {at[1]} 0)", placed, count=1)
    placed = re.sub(r'\(uuid "[^"]+"\)', f'(uuid "{uuid.uuid4()}")', placed, count=1)
    placed = re.sub(r'(property "Reference"\s+)"[^"]+"', rf'\1"{reference}"', placed, count=1)
    placed = re.sub(r'(property "Value"\s+)"[^"]*"', rf'\1"{value}"', placed, count=1)
    placed = re.sub(r'(property "Footprint"\s+)"[^"]*"', rf'\1"{footprint}"', placed, count=1)
    placed = re.sub(r'(property "Datasheet"\s+)"[^"]*"', rf'\1"{datasheet}"', placed, count=1)
    placed = re.sub(
        r'(property "Reference".*?\(at)\s+[^\)]+',
        rf'\1 {at[0]} {at[1] - 25.4} 0', placed, count=1, flags=re.S,
    )
    placed = re.sub(
        r'(property "Value".*?\(at)\s+[^\)]+',
        rf'\1 {at[0]} {at[1] + 25.4} 0', placed, count=1, flags=re.S,
    )
    placed = re.sub(r'\(reference "[^"]+"\)', f'(reference "{reference}")', placed)
    pin_match = re.search(r"\s+\(pin \"", placed)
    instances_match = re.search(r"\s+\(instances", placed)
    if pin_match is None or instances_match is None:
        raise ValueError(f"template instance has no pins: {template_lib}")
    new_pins = "".join(
        f'\n\t\t(pin "{ball}" (uuid "{uuid.uuid4()}"))'
        for ball in pin_blocks(cached_symbol)
    )
    placed = placed[: pin_match.start()] + new_pins + placed[instances_match.start() :]
    marker = text.index("(sheet_instances")
    text = text[:marker] + "\n" + placed + text[marker:]
    path.write_text(text)


def labels_for_symbol(
    cached_symbol: str,
    origin: tuple[float, float],
    nets: dict[str, str],
) -> list[str]:
    blocks: list[str] = []
    for ball, net in nets.items():
        _, at = pin_metadata(cached_symbol)[ball]
        x, y, angle = at.split()
        absolute = (round(origin[0] + float(x), 3), round(origin[1] - float(y), 3))
        blocks.append(global_label_block(net, absolute, int(angle)))
    return blocks


def move_pin(block: str, at: str) -> str:
    return re.sub(r"\(at\s+[^\)]+\)", f"(at {at})", block, count=1)


def customize_symbol(
    source: str,
    source_name: str,
    target_name: str,
    footprint: str,
    placements: dict[str, str],
    fallback_positions: list[str],
    rectangle: tuple[str, str],
) -> str:
    _, _, block = named_symbol_block(source, source_name)
    block = block.replace(f'(symbol "{source_name}"', f'(symbol "{target_name}"', 1)
    block = block.replace(f'(symbol "{source_name}_0_1"', f'(symbol "{target_name.split(":")[-1]}_0_1"', 1)
    block = re.sub(
        r'("Footprint"\s+)"[^"]*"',
        rf'\1"{footprint}"',
        block,
        count=1,
    )
    block = re.sub(
        r"\(rectangle\s+\(start [^\)]+\)\s+\(end [^\)]+\)",
        f"(rectangle\n        (start {rectangle[0]})\n        (end {rectangle[1]})",
        block,
        count=1,
    )
    pins = pin_blocks(block)
    unused_positions = iter(fallback_positions)
    edits: list[tuple[int, int, str]] = []
    for number, (start, end, pin) in pins.items():
        pos = placements.get(number)
        if pos is None:
            try:
                pos = next(unused_positions)
            except StopIteration as exc:
                raise ValueError(f"not enough fallback positions for {source_name}") from exc
        edits.append((start, end, move_pin(pin, pos)))
    for start, end, replacement in sorted(edits, reverse=True):
        block = block[:start] + replacement + block[end:]
    return block


def replace_cached_and_placed(
    path: Path,
    old_name: str,
    new_name: str,
    cached_symbol: str,
    value: str,
    footprint: str,
    mpn: str,
    datasheet: str,
) -> None:
    text = path.read_text()
    start, end, _ = named_symbol_block(text, old_name)
    text = text[:start] + cached_symbol + text[end:]
    start, end, placed = placed_symbol_block(text, old_name)
    placed = placed.replace(f'(lib_id "{old_name}")', f'(lib_id "{new_name}")', 1)
    placed = re.sub(r'(property "Value"\s+)"[^"]*"', rf'\1"{value}"', placed, count=1)
    placed = re.sub(r'(property "Footprint"\s+)"[^"]*"', rf'\1"{footprint}"', placed, count=1)
    placed = re.sub(r'(property "Datasheet"\s+)"[^"]*"', rf'\1"{datasheet}"', placed, count=1)
    placed = re.sub(r'(property "MPN"\s+)"[^"]*"', rf'\1"{mpn}"', placed, count=1)
    origin_match = re.search(r"\(at\s+([\d.\-]+)\s+([\d.\-]+)\s+", placed)
    ox, oy = (float(origin_match.group(1)), float(origin_match.group(2)))
    field_offset = 25.4 if len(pin_blocks(cached_symbol)) > 20 else 12.7
    placed = re.sub(
        r'(property "Reference".*?\(at)\s+[^\)]+',
        rf'\1 {ox} {oy - field_offset} 0', placed, count=1, flags=re.S,
    )
    placed = re.sub(
        r'(property "Value".*?\(at)\s+[^\)]+',
        rf'\1 {ox} {oy + field_offset} 0', placed, count=1, flags=re.S,
    )
    pin_match = re.search(r"\s+\(pin \"", placed)
    instances_match = re.search(r"\s+\(instances", placed)
    if pin_match is None or instances_match is None:
        raise ValueError(f"pin/instance list missing from {old_name}")
    pin_start = pin_match.start()
    instances = instances_match.start()
    balls = list(pin_blocks(cached_symbol))
    new_pins = "".join(f'\n\t\t(pin "{ball}" (uuid "{uuid.uuid4()}"))' for ball in balls)
    placed = placed[:pin_start] + new_pins + placed[instances:]
    text = text[:start] + placed + text[end:]
    path.write_text(text)


def delete_symbol_and_direct_wires(schematic: skip.Schematic, reference: str) -> None:
    symbol = getattr(schematic.symbol, reference)
    seen: set[str] = set()
    for wire in list(symbol.attached_wires):
        key = str(wire.uuid.value)
        if key not in seen:
            seen.add(key)
            wire.delete()
    symbol.delete()


def set_field(symbol, field: str, value: str) -> None:
    getattr(symbol.property, field).value = value


def shrink_passives(path: Path) -> None:
    schematic = skip.Schematic(str(path))
    for symbol in list(schematic.symbol):
        ref = str(symbol.property.Reference.value)
        value = str(symbol.property.Value.value)
        if ref.startswith("R"):
            set_field(symbol, "Footprint", "pcbgolf:01005-R")
        elif ref.startswith("C"):
            normalized = value.lower().replace("f", "")
            if normalized in {"10u", "10uf"}:
                # 0201 10 uF is used only on low-voltage MCU rails.  USB/5 V and
                # 12 V bulk capacitors retain the proven 0402 footprint.
                if path.name == "pcbgolf_2.kicad_sch":
                    set_field(symbol, "Footprint", "pcbgolf:0201-C")
                else:
                    set_field(symbol, "Footprint", "pcbgolf:0402-C")
            else:
                set_field(symbol, "Footprint", "pcbgolf:01005-C")
        elif ref == "L3":
            set_field(symbol, "Footprint", "pcbgolf:0201-L")
        elif ref == "L4":
            set_field(symbol, "Footprint", "pcbgolf:0402-L")
    schematic.write(str(path))


def edit_root_power() -> None:
    path = ROOT / "pcbgolf.kicad_sch"
    schematic = skip.Schematic(str(path))
    for reference in [
        "L1", "L2", "C2", "C4", "C5", "C6", "C7", "C9", "C10", "C11", "C13",
        "R3", "R4", "R5", "R6", "R7", "R8", "R10",
    ]:
        delete_symbol_and_direct_wires(schematic, reference)
    orphan_ground_refs = {"#GND02", "#GND08", "#GND09", "#GND010", "#GND011", "#GND015", "#GND017"}
    for symbol in list(schematic.symbol):
        if str(symbol.property.Reference.value) in orphan_ground_refs:
            symbol.delete()
    orphan_starts = {(101.6, 116.84), (148.59, 48.26), (181.61, 43.18)}
    for wire in list(schematic.wire):
        start = tuple(round(float(v), 2) for v in wire.pts.xy[0].value)
        if start in orphan_starts:
            wire.delete()
    set_field(schematic.symbol.R9, "Value", "100k")
    set_field(schematic.symbol.R9, "MPN", "RC0100FR-07100KL")
    set_field(schematic.symbol.C3, "Value", "1uF")
    schematic.write(str(path))

    # Rebuild the two regulator islands explicitly.  This avoids retaining any
    # switch-node stubs after the buck inductors and compensation networks go.
    wires = [
        # 12 V -> 5 V LT3083 and its SET resistor/output capacitor.
        ((83.82, 40.64), (151.13, 40.64)),
        ((104.14, 48.26), (104.14, 66.04)),
        ((181.61, 40.64), (241.3, 40.64)),
        ((232.41, 48.26), (232.41, 66.04)),
        ((181.61, 48.26), (184.15, 48.26)),
        ((184.15, 48.26), (184.15, 53.34)),
        ((184.15, 63.5), (184.15, 66.04)),
        # 5 V -> 3.3 V TLV76733, enable pull-up and sense return.
        ((30.48, 114.3), (71.12, 114.3)),
        ((30.48, 121.92), (30.48, 139.7)),
        ((30.48, 114.3), (55.88, 114.3)),
        ((55.88, 114.3), (55.88, 121.92)),
        ((68.58, 121.92), (71.12, 121.92)),
        ((86.36, 129.54), (86.36, 139.7)),
        ((101.6, 114.3), (154.94, 114.3)),
        ((154.94, 121.92), (154.94, 139.7)),
        ((101.6, 121.92), (142.24, 121.92)),
        ((142.24, 121.92), (142.24, 114.3)),
    ]
    append_top_level(path, [wire_block(a, b) for a, b in wires])


def edit_mcu_sheet() -> None:
    path = ROOT / "pcbgolf_2.kicad_sch"
    schematic = skip.Schematic(str(path))
    set_field(schematic.symbol.R21, "Value", "0R")
    set_field(schematic.symbol.R21, "MPN", "RC0100JR-070RL")
    set_field(schematic.symbol.R22, "Value", "0R")
    set_field(schematic.symbol.R22, "MPN", "RC0100JR-070RL")
    set_field(schematic.symbol.R23, "Value", "330R")
    set_field(schematic.symbol.R23, "MPN", "RC0100FR-07330RL")
    # Remove labels that were directly attached to the old 144-pin MCU.  The
    # resistor-input labels and off-MCU peripherals remain in place.
    for label in list(schematic.global_label):
        pos = [round(float(x), 2) for x in label.at.value[:2]]
        if 55.0 <= pos[0] <= 170.0:
            label.delete()
        elif label.value == "VLXSMPS":
            label.delete()
        elif label.value == "LED_B":
            label.value = "LED_DATA"
        elif label.value == "LED_G":
            label.value = "LED_DOUT"
        elif label.value == "LED_R" and pos == [62.23, 134.62]:
            label.delete()
        elif label.value == "LED_R":
            label.value = "GND"
        elif label.value == "VDDLDO":
            label.value = "VCAP"
    for marker in list(schematic.no_connect):
        marker.delete()
    for junction in list(schematic.junction):
        x, y = (float(v) for v in junction.at.value[:2])
        if 60 <= x <= 166 and 27 <= y <= 220:
            junction.delete()
    # H503 uses its internal LDO. Remove the H725 SMPS network, external HSE,
    # and duplicate VCAP/bulk capacitors; retain the mandatory VCAP and local
    # VDD/VDDA bypass network.
    for reference in ["L4", "C25", "C21", "C18", "C20", "Y1", "C14", "C17", "R11", "R12"]:
        delete_symbol_and_direct_wires(schematic, reference)
    for symbol in list(schematic.symbol):
        if str(symbol.property.Reference.value) in {
            "#GND018", "#GND019", "#GND020", "#GND021", "#GND022", "#GND023", "#GND024", "#GND025", "#GND026", "#GND027", "#GND028", "#GND029", "#GND030", "#GND031", "#GND032", "#GND033", "#GND034",
            "#PWR05", "#PWR06", "#PWR07", "#PWR08", "#PWR09", "#PWR010", "#PWR011",
        }:
            symbol.delete()
    # Drop the short wire tails that formerly joined labels and power rails to
    # the perimeter of the 144-pin H725 symbol.
    for wire in list(schematic.wire):
        pts = [tuple(round(float(v), 2) for v in xy.value) for xy in wire.pts.xy]
        (x1, y1), (x2, y2) = pts
        length = abs(x2 - x1) + abs(y2 - y1)
        old_side_stub = length <= 2.6 and (
            any(61.5 <= x <= 65.0 for x, _ in pts) or any(161.0 <= x <= 164.2 for x, _ in pts)
        )
        old_top_stub = length <= 5.1 and any(27.0 <= y <= 33.5 for _, y in pts) and any(80 <= x <= 145 for x, _ in pts)
        old_crystal = any(20 <= x <= 66 and 64 <= y <= 77 for x, y in pts)
        old_smps_stub = any(abs(x - 236.22) < 0.05 and abs(y - 91.44) < 0.05 for x, y in pts)
        old_ground_stub = any(109 <= x <= 117 and 220 <= y <= 224 for x, y in pts)
        if old_side_stub or old_top_stub or old_crystal or old_smps_stub or old_ground_stub:
            wire.delete()
    set_field(schematic.symbol.C15, "Value", "2.2uF")
    set_field(schematic.symbol.C16, "Value", "100nF")
    set_field(schematic.symbol.C19, "Value", "4.7uF")
    schematic.write(str(path))
    append_top_level(path, [
        wire_block((34.29, 185.42), (54.61, 185.42)),
        wire_block((44.45, 185.42), (54.61, 185.42)),
        global_label_block("GND", (34.29, 185.42)),
        global_label_block("GND", (44.45, 185.42)),
        *[global_label_block("GND", (x, 45.72)) for x in (201.93, 223.52, 233.68, 243.84, 254.0)],
        global_label_block("+3V3", (201.93, 35.56)),
        global_label_block("+3V3", (204.47, 64.77)),
        global_label_block("+3V3", (223.52, 185.42)),
        global_label_block("+3V3", (236.22, 138.43)),
        global_label_block("GND", (222.25, 77.47)),
    ])


def copy_assets() -> None:
    (ROOT / "pcbgolf.3dshapes").mkdir(exist_ok=True)
    required_tokens = {
        "DFN-12_L4.0-W4.0", "WSON-6_L2.0-W2.0", "LED-SMD_4P-L1.0-W1.0",
        "WLCSP-25_L2.3-W2.2", "VFQFPN-24_L4.0-W4.0", "DHVQFN24_L5.5-W3.5",
        "USON-10_L2.5-W1.0",
    }
    for source in (GENERATED / "pcbgolf.pretty").glob("*.kicad_mod"):
        if any(token in source.name for token in required_tokens):
            shutil.copy2(source, ROOT / "pcbgolf.pretty" / source.name)
    for source in (GENERATED / "pcbgolf.3dshapes").glob("*"):
        if any(token in source.name for token in required_tokens):
            shutil.copy2(source, ROOT / "pcbgolf.3dshapes" / source.name)
    for source in (USB_LIB / "footprints/PCB_USBC.pretty").glob("*.kicad_mod"):
        shutil.copy2(source, ROOT / "pcbgolf.pretty" / source.name)

    standards = {
        KICAD_FP / "Resistor_SMD.pretty/R_01005_0402Metric.kicad_mod": "01005-R.kicad_mod",
        KICAD_FP / "Capacitor_SMD.pretty/C_01005_0402Metric.kicad_mod": "01005-C.kicad_mod",
        KICAD_FP / "Capacitor_SMD.pretty/C_0201_0603Metric.kicad_mod": "0201-C.kicad_mod",
        KICAD_FP / "Inductor_SMD.pretty/L_0201_0603Metric.kicad_mod": "0201-L.kicad_mod",
        KICAD_FP / "Inductor_SMD.pretty/L_0402_1005Metric.kicad_mod": "0402-L.kicad_mod",
    }
    for source, destination in standards.items():
        shutil.copy2(source, ROOT / "pcbgolf.pretty" / destination)


def merge_project_symbols(custom_symbols: list[str]) -> None:
    path = ROOT / "pcbgolf.kicad_sym"
    text = path.read_text().rstrip()
    if not text.endswith(")"):
        raise ValueError("unexpected project symbol library")
    additions = []
    existing = set(re.findall(r'^\s*\(symbol "([^"]+)"', text, re.M))
    for block in custom_symbols:
        name = re.search(r'^\(symbol "([^"]+)"', block).group(1)
        if name not in existing:
            additions.append("\n  " + block.replace("\n", "\n  "))
            existing.add(name)
    usb_text = (USB_LIB / "symbols/PCB_USBC.kicad_sym").read_text()
    for name in re.findall(r'^\s*\(symbol "([^"]+)"', usb_text, re.M):
        _, _, block = named_symbol_block(usb_text, name)
        if name not in existing:
            additions.append("\n  " + block.replace("\n", "\n  "))
            existing.add(name)
    path.write_text(text[:-1] + "".join(additions) + "\n)\n")


def main() -> None:
    if not GENERATED.exists() or not USB_LIB.exists():
        raise SystemExit("staged KiCad assets are missing")
    backup = ROOT / "build/backups/pre-optimization"
    backup.mkdir(parents=True, exist_ok=True)
    for path in [*ROOT.glob("pcbgolf*.kicad_sch"), ROOT / "pcbgolf.kicad_sym"]:
        destination = backup / path.name
        if not destination.exists():
            shutil.copy2(path, destination)

    copy_assets()
    for path in ROOT.glob("pcbgolf*.kicad_sch"):
        shrink_passives(path)
    edit_root_power()
    edit_mcu_sheet()

    generated = (GENERATED / "pcbgolf.kicad_sym").read_text()
    mcu_positions = {
        "A1": "20.32 -5.08 180", "B1": "-20.32 -5.08 0",
        "B3": "-20.32 0 0", "B4": "20.32 0 180",
        "A4": "-20.32 5.08 0", "A5": "20.32 5.08 180",
        "C4": "-20.32 10.16 0", "A2": "-20.32 12.7 0",
        "E4": "20.32 10.16 180", "E3": "20.32 12.7 180",
        "E5": "-20.32 -10.16 0", "C1": "20.32 -10.16 180",
        "D1": "20.32 -12.7 180", "D2": "-20.32 17.78 0",
        "C2": "20.32 17.78 180", "D3": "-20.32 -12.7 0",
        "E1": "20.32 -2.54 180", "B5": "-20.32 7.62 0",
        "C5": "20.32 7.62 180", "A3": "-7.62 -22.86 90",
        "D5": "-20.32 20.32 0", "B2": "-2.54 22.86 270",
        "D4": "2.54 22.86 270", "C3": "0 -22.86 90",
        "E2": "5.08 -22.86 90",
    }
    mcu = customize_symbol(
        generated, "STM32H503EBY6TR_C26803530", "pcbgolf:STM32H503EBY6TR",
        "pcbgolf:WLCSP-25_L2.3-W2.2-R5-C5-P0.40-BR", mcu_positions, [],
        ("-17.78 20.32", "17.78 -20.32"),
    )

    aw_positions = {
        **{str(n): f"-20.32 {17.78 - (n - 1) * 2.54} 0" for n in range(1, 9)},
        **{str(n): f"20.32 {17.78 - (n - 10) * 2.54} 180" for n in range(10, 18)},
        "9": "-2.54 -22.86 90", "25": "0 -22.86 90", "21": "0 22.86 270",
        "19": "-7.62 22.86 270", "20": "-5.08 22.86 270",
        "18": "-10.16 -22.86 90", "24": "-7.62 -22.86 90",
        "22": "7.62 -22.86 90", "23": "10.16 -22.86 90",
    }
    aw = customize_symbol(
        generated, "AW9523BTQR", "pcbgolf:AW9523BTQR",
        "pcbgolf:VFQFPN-24_L4.0-W4.0-P0.50-BL-EP2.8", aw_positions, [],
        ("-17.78 20.32", "17.78 -20.32"),
    )

    analog_positions = {
        "1": "20.32 0 180", "24": "0 22.86 270", "25": "2.54 22.86 270",
        "12": "0 -22.86 90", "15": "-2.54 -22.86 90",
        "10": "-10.16 -22.86 90", "11": "-7.62 -22.86 90",
        "14": "-5.08 -22.86 90", "13": "-2.54 -22.86 90",
    }
    for index, ball in enumerate(["9", "8", "7", "6", "5", "4", "3", "2", "23", "22", "21", "20", "19", "18", "17", "16"]):
        analog_positions[ball] = f"-20.32 {19.05 - index * 2.54} 0"
    analog_mux = customize_symbol(
        generated, "74HC4067BQ,118", "pcbgolf:74HC4067BQ_118",
        "pcbgolf:DHVQFN24_L5.5-W3.5-P0.50-BL-EP", analog_positions, [],
        ("-17.78 21.59", "17.78 -21.59"),
    )

    can_mux_positions = {
        "2": "-15.24 7.62 0", "9": "-15.24 2.54 0",
        "4": "-15.24 -2.54 0", "7": "-15.24 -7.62 0",
        "8": "15.24 0 180", "1": "-5.08 -12.7 90", "10": "0 -12.7 90",
        "5": "5.08 -12.7 90", "3": "0 -15.24 90", "6": "0 15.24 270",
    }
    can_mux = customize_symbol(
        generated, "TMUX1204DQAR", "pcbgolf:TMUX1204DQAR",
        "pcbgolf:USON-10_L2.5-W1.0-P0.50-BL", can_mux_positions, [],
        ("-12.7 10.16", "12.7 -10.16"),
    )

    led_positions = {
        "2": "-15.24 -5.08 0", "3": "-15.24 5.08 0",
        "1": "12.7 5.08 180", "4": "12.7 -5.08 180",
    }
    led = customize_symbol(
        generated, "XL-1010RGBC-WS2812B", "pcbgolf:XL-1010RGBC-WS2812B",
        "pcbgolf:LED-SMD_4P-L1.0-W1.0-TL_XL-1010RGBC-WS2812B",
        led_positions, [], ("-12.7 7.62", "10.16 -7.62"),
    )

    tlv_positions = {
        "6": "-15.24 2.54 0", "1": "15.24 2.54 180",
        "2": "15.24 -5.08 180", "4": "-15.24 -5.08 0",
        "3": "0 -12.7 90", "5": "0 -12.7 90", "7": "0 -12.7 90",
    }
    tlv = customize_symbol(
        generated, "TLV76733DRVR", "pcbgolf:TLV76733DRVR",
        "pcbgolf:WSON-6_L2.0-W2.0-P0.65-TL-EP", tlv_positions, [],
        ("-12.7 10.16", "12.7 -10.16"),
    )

    lt_positions = {
        **{str(n): "15.24 2.54 180" for n in [1, 2, 3, 4, 5, 13]},
        "6": "15.24 -5.08 180",
        **{str(n): "-15.24 2.54 0" for n in [7, 8, 9, 10, 11, 12]},
    }
    lt = customize_symbol(
        generated, "LT3083IDF#TRPBF", "pcbgolf:LT3083IDF#TRPBF",
        "pcbgolf:DFN-12_L4.0-W4.0-P0.50-BL-EP", lt_positions, [],
        ("-12.7 10.16", "12.7 -10.16"),
    )

    mcu_path = ROOT / "pcbgolf_2.kicad_sch"
    add_symbol_instance(
        mcu_path, "pcbgolf:STM32H725ZGTx", aw, "pcbgolf:AW9523BTQR",
        "U13", "AW9523BTQR", "pcbgolf:VFQFPN-24_L4.0-W4.0-P0.50-BL-EP2.8",
        "https://www.lcsc.com/datasheet/C148077.pdf", (185.0, 78.0),
    )
    add_symbol_instance(
        mcu_path, "pcbgolf:STM32H725ZGTx", aw, "pcbgolf:AW9523BTQR",
        "U14", "AW9523BTQR", "pcbgolf:VFQFPN-24_L4.0-W4.0-P0.50-BL-EP2.8",
        "https://www.lcsc.com/datasheet/C148077.pdf", (235.0, 78.0),
    )
    add_symbol_instance(
        mcu_path, "pcbgolf:STM32H725ZGTx", analog_mux, "pcbgolf:74HC4067BQ_118",
        "U15", "74HC4067BQ,118", "pcbgolf:DHVQFN24_L5.5-W3.5-P0.50-BL-EP",
        "https://www.nexperia.com/pip/74HC4067BQ", (210.0, 147.0),
    )
    can_path = ROOT / "pcbgolf_4.kicad_sch"
    add_symbol_instance(
        can_path, "pcbgolf:comma.ai_11112255_MCP2542FDT-E/MNY", can_mux,
        "pcbgolf:TMUX1204DQAR", "U16", "TMUX1204DQAR",
        "pcbgolf:USON-10_L2.5-W1.0-P0.50-BL", "https://www.ti.com/lit/ds/symlink/tmux1204.pdf",
        (120.0, 160.0),
    )

    replace_cached_and_placed(
        ROOT / "pcbgolf_2.kicad_sch", "pcbgolf:STM32H725ZGTx",
        "pcbgolf:STM32H503EBY6TR", mcu, "STM32H503EBY6TR",
        "pcbgolf:WLCSP-25_L2.3-W2.2-R5-C5-P0.40-BR", "STM32H503EBY6TR",
        "https://www.st.com/resource/en/datasheet/stm32h503eb.pdf",
    )

    mcu_nets = {
        "A1": "STM_D_P", "B1": "STM_D_N", "B3": "CAN_RX", "B4": "CAN_TX",
        "A4": "HUB_SDA", "A5": "HUB_SCL", "C4": "SD_D0", "A2": "SD_D3",
        "E4": "SD_CLK", "E3": "SD_CMD", "E5": "SENSE_MUX", "C1": "LED_DATA",
        "D1": "BTN", "D2": "SWDIO", "C2": "SWCLK", "D3": "IOX_INT0",
        "E1": "IOX_INT1", "A3": "BTN", "D5": "NRST", "B2": "+3V3",
        "D4": "+3V3", "C3": "GND", "E2": "VCAP", "B5": "LSE_IN_SPARE",
        "C5": "LSE_OUT_SPARE",
    }
    aw13_nets = {
        "1": "CH1_SBU1_IGN", "2": "CH1_SBU1_RELAY", "3": "CH1_SBU2_IGN", "4": "CH1_SBU2_RELAY",
        "5": "CH2_SBU1_IGN", "6": "CH2_SBU1_RELAY", "7": "CH2_SBU2_IGN", "8": "CH2_SBU2_RELAY",
        "10": "CH3_SBU1_IGN", "11": "CH3_SBU1_RELAY", "12": "CH3_SBU2_IGN", "13": "CH3_SBU2_RELAY",
        "14": "CH4_SBU1_IGN", "15": "CH4_SBU1_RELAY", "16": "CH4_SBU2_IGN", "17": "CH4_SBU2_RELAY",
        "9": "GND", "25": "GND", "21": "+3V3", "19": "HUB_SCL", "20": "HUB_SDA",
        "18": "GND", "24": "GND", "22": "IOX_INT0", "23": "+3V3",
    }
    aw14_nets = {
        "1": "CH1_PWR_EN", "2": "CH2_PWR_EN", "3": "CH3_PWR_EN", "4": "CH4_PWR_EN",
        "5": "CAN0_EN", "6": "CAN1_EN", "7": "CAN2_EN", "8": "CAN3_EN",
        "10": "SENSE_SEL0", "11": "SENSE_SEL1", "12": "SENSE_SEL2", "13": "SENSE_SEL3",
        "14": "CAN_SEL0", "15": "CAN_SEL1", "9": "GND", "25": "GND", "21": "+3V3",
        "19": "HUB_SCL", "20": "HUB_SDA", "18": "+3V3", "24": "GND",
        "22": "IOX_INT1", "23": "+3V3", "16": "IOX_SPARE0", "17": "IOX_SPARE1",
    }
    sense_nets = [
        "CH2_SBU2_ADC", "CH4_SBU2_ADC", "CH2_SBU1_ADC", "CH4_SBU1_ADC",
        "CH3_SBU1_ADC", "CH3_SBU2_ADC", "CH1_SBU1_ADC", "CH1_SBU2_ADC",
        "CH1_IMON", "CH2_IMON", "CH3_IMON", "CH4_IMON",
    ]
    analog_balls = ["9", "8", "7", "6", "5", "4", "3", "2", "23", "22", "21", "20"]
    analog_nets = dict(zip(analog_balls, sense_nets))
    analog_nets.update({
        "1": "SENSE_MUX", "10": "SENSE_SEL0", "11": "SENSE_SEL1",
        "14": "SENSE_SEL2", "13": "SENSE_SEL3", "15": "GND", "12": "GND",
        "24": "+3V3", "25": "+3V3",
        "19": "SENSE_SPARE12", "18": "SENSE_SPARE13",
        "17": "SENSE_SPARE14", "16": "SENSE_SPARE15",
    })
    label_blocks = []
    label_blocks += labels_for_symbol(mcu, (113.03, 127.0), mcu_nets)
    label_blocks += labels_for_symbol(aw, (185.0, 78.0), aw13_nets)
    label_blocks += labels_for_symbol(aw, (235.0, 78.0), aw14_nets)
    label_blocks += labels_for_symbol(analog_mux, (210.0, 147.0), analog_nets)
    for name, pos in zip(sense_nets[:8], [
        (64.77, 104.14), (64.77, 106.68), (64.77, 109.22), (64.77, 111.76),
        (161.29, 129.54), (161.29, 132.08), (161.29, 134.62), (161.29, 137.16),
    ]):
        label_blocks.append(global_label_block(name, pos))
    append_top_level(mcu_path, label_blocks)

    # All transceivers share the FDCAN TX line. RXD remains isolated through
    # U16 because MCP2542FD drives RXD while in standby.
    can_schematic = skip.Schematic(str(can_path))
    for label in can_schematic.global_label:
        if str(label.value) in {"CAN0_TX", "CAN1_TX", "CAN2_TX", "CAN3_TX"}:
            label.value = "CAN_TX"
    can_schematic.write(str(can_path))
    append_top_level(can_path, labels_for_symbol(can_mux, (120.0, 160.0), {
        "2": "CAN0_RX", "9": "CAN1_RX", "4": "CAN2_RX", "7": "CAN3_RX",
        "8": "CAN_RX", "1": "CAN_SEL0", "10": "CAN_SEL1", "5": "GND",
        "3": "GND", "6": "+3V3",
    }))
    replace_cached_and_placed(
        ROOT / "pcbgolf_2.kicad_sch", "pcbgolf:comma.ai_11112255_CREE-RGB-CLMVC",
        "pcbgolf:XL-1010RGBC-WS2812B", led, "XL-1010RGBC-WS2812B",
        "pcbgolf:LED-SMD_4P-L1.0-W1.0-TL_XL-1010RGBC-WS2812B",
        "XL-1010RGBC-WS2812B", "https://www.lcsc.com/datasheet/C5349953.pdf",
    )
    replace_cached_and_placed(
        ROOT / "pcbgolf.kicad_sch", "pcbgolf:comma.ai_11112255_AP62300T",
        "pcbgolf:TLV76733DRVR", tlv, "TLV76733DRVR",
        "pcbgolf:WSON-6_L2.0-W2.0-P0.65-TL-EP", "TLV76733DRVR",
        "https://www.ti.com/lit/ds/symlink/tlv767.pdf",
    )
    # The second AP62300 cache entry shares the same library symbol, so after the
    # first replacement only the placed instance needs conversion.
    text = (ROOT / "pcbgolf.kicad_sch").read_text()
    start, end, placed = placed_symbol_block(text, "pcbgolf:comma.ai_11112255_AP62300T")
    placed = placed.replace('(lib_id "pcbgolf:comma.ai_11112255_AP62300T")', '(lib_id "pcbgolf:LT3083IDF#TRPBF")', 1)
    placed = re.sub(r'(property "Value"\s+)"[^"]*"', r'\1"LT3083IDF#TRPBF"', placed, count=1)
    placed = re.sub(r'(property "Footprint"\s+)"[^"]*"', r'\1"pcbgolf:DFN-12_L4.0-W4.0-P0.50-BL-EP"', placed, count=1)
    placed = re.sub(r'(property "Datasheet"\s+)"[^"]*"', r'\1"https://www.analog.com/media/en/technical-documentation/data-sheets/LT3083.pdf"', placed, count=1)
    placed = re.sub(r'(property "MPN"\s+)"[^"]*"', r'\1"LT3083IDF#TRPBF"', placed, count=1)
    pin_match = re.search(r"\s+\(pin \"", placed)
    instances_match = re.search(r"\s+\(instances", placed)
    if pin_match is None or instances_match is None:
        raise ValueError("pin/instance list missing from U2")
    pstart = pin_match.start()
    instances = instances_match.start()
    balls = list(pin_blocks(lt))
    pins = "".join(f'\n\t\t(pin "{ball}" (uuid "{uuid.uuid4()}"))' for ball in balls)
    placed = placed[:pstart] + pins + placed[instances:]
    text = text[:start] + placed + text[end:]
    # Add the LT3083 cached symbol alongside the TLV767 cache.
    lib_start = text.index("(lib_symbols")
    lib_close, _ = balanced_block(text, lib_start)
    lib_end = lib_close - 1
    text = text[:lib_end] + "\n\t" + lt.replace("\n", "\n\t") + text[lib_end:]
    (ROOT / "pcbgolf.kicad_sch").write_text(text)

    merge_project_symbols([mcu, led, tlv, lt, aw, analog_mux, can_mux])


if __name__ == "__main__":
    main()
