#!/usr/bin/env python3
"""Swap placed active devices while preserving their existing electrical nets."""

from __future__ import annotations

import re
import shutil
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "pcbgolf.kicad_sym"


def balanced(text, start):
    depth = 0
    quoted = escaped = False
    for i in range(start, len(text)):
        ch = text[i]
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
                return i + 1
    raise ValueError(start)


def symbol_block(text, name):
    start = text.index(f'(symbol "{name}"')
    end = balanced(text, start)
    return start, end, text[start:end]


def property_value(text, key, value):
    return re.sub(r'(\(property "' + re.escape(key) + r'"\s+)"[^"]*"',
                  lambda m: m[1] + '"' + value + '"', text, count=1)


def pin_number(block):
    return re.search(r'\(number "([^"]+)"', block)[1]


def pin_transform(block, number, name=None, position=None):
    block = re.sub(r'\(number "[^"]+"', f'(number "{number}"', block, count=1)
    if name is not None:
        block = re.sub(r'\(name "[^"]*"', f'(name "{name}"', block, count=1)
    if position is not None:
        block = re.sub(r'\(at [^)]+\)', f'(at {position})', block, count=1)
    return block


def alter_symbol(original, old_name, new_name, mapping, properties, extra=None):
    result = original.replace(f'(symbol "{old_name}"', f'(symbol "{new_name}"', 1)
    old_short, new_short = old_name.split(':')[-1], new_name.split(':')[-1]
    result = result.replace(f'(symbol "{old_short}_', f'(symbol "{new_short}_')
    for key, value in properties.items():
        result = property_value(result, key, value)
    edits = []
    pin_by_old = {}
    for match in re.finditer(r'\(pin\s+(?:input|output|passive|power_in|power_out|no_connect|bidirectional)\s+', result):
        start = match.start()
        end = balanced(result, start)
        old = pin_number(result[start:end])
        pin_by_old[old] = result[start:end]
        new = mapping.get(old)
        edits.append((start, end, "" if new is None else pin_transform(result[start:end], *new)))
    if extra:
        extra_pin = pin_transform(pin_by_old[extra[0]], extra[1], extra[2], extra[3])
        edits.append((edits[-1][1], edits[-1][1], "\n" + extra_pin))
    for start, end, replacement in sorted(edits, reverse=True):
        result = result[:start] + replacement + result[end:]
    return result


def alter_instances(source, old_id, new_id, mapping, properties, extra=None):
    found = []
    edits = []
    for match in re.finditer(r'\(lib_id "' + re.escape(old_id) + r'"\)', source):
        start = source.rfind('(symbol\n', 0, match.start())
        if start < 0:
            start = source.rfind('(symbol ', 0, match.start())
        end = balanced(source, start)
        block = source[start:end]
        ref = re.search(r'\(property "Reference" "([^"]+)"', block)[1]
        found.append((ref, re.search(r'\(at ([^)]+)\)', block)[1]))
        block = block.replace(f'(lib_id "{old_id}")', f'(lib_id "{new_id}")', 1)
        for key, value in properties.items():
            block = property_value(block, key, value)
        if new_id == 'pcbgolf:APG015ZGC_S-5MAV':
            value_start = block.index('(property "Value"')
            value_end = balanced(block, value_start)
            value_block = block[value_start:value_end]
            if '(hide yes)' not in value_block:
                value_block = value_block.replace('(effects', '(hide yes)\n\t\t\t(effects', 1)
            block = block[:value_start] + value_block + block[value_end:]
        pin_edits = []
        pins = {}
        for pm in re.finditer(r'\(pin "([^"]+)"', block):
            ps, pe = pm.start(), balanced(block, pm.start())
            old = pm[1]
            pins[old] = block[ps:pe]
            pin_edits.append((ps, pe, "" if old not in mapping else
                              block[ps:pe].replace(f'(pin "{old}"', f'(pin "{mapping[old][0]}"', 1)))
        if extra:
            new_pin = pins[extra[0]].replace(f'(pin "{extra[0]}"', f'(pin "{extra[1]}"', 1)
            new_pin = re.sub(r'\(uuid "[^"]+"\)', f'(uuid "{uuid.uuid4()}")', new_pin, count=1)
            pin_edits.append((pin_edits[-1][1], pin_edits[-1][1], "\n" + new_pin))
        for ps, pe, value in sorted(pin_edits, reverse=True):
            block = block[:ps] + value + block[pe:]
        edits.append((start, end, block))
    for start, end, value in sorted(edits, reverse=True):
        source = source[:start] + value + source[end:]
    return source, found


def install_symbol(library, old_name, new_name, mapping, properties, extra=None):
    _, _, old = symbol_block(library, old_name)
    revised = alter_symbol(old, old_name, new_name, mapping, properties, extra)
    if f'(symbol "{new_name}"' in library:
        start, end, _ = symbol_block(library, new_name)
        library = library[:start] + revised + library[end:]
    else:
        library = library.rstrip()[:-1] + "\n" + revised + "\n)\n"
    return library


def cached_swap(source, old_id, new_id, mapping, properties, extra=None):
    start, end, old = symbol_block(source, old_id)
    new = alter_symbol(old, old_id, new_id, mapping, properties, extra)
    source = source[:start] + new + source[end:]
    return alter_instances(source, old_id, new_id, mapping, properties, extra)


def wire(x1, y1, x2, y2):
    return (f'(wire (pts (xy {x1:g} {y1:g}) (xy {x2:g} {y2:g})) '
            f'(stroke (width 0) (type default)) (uuid "{uuid.uuid4()}"))')


def label(name, x, y, angle=0):
    justify = " (justify right)" if angle == 180 else ""
    return (f'(global_label "{name}" (shape bidirectional) (at {x:g} {y:g} {angle}) '
            f'(fields_autoplaced yes) (effects (font (size 1.27 1.27)){justify}) '
            f'(uuid "{uuid.uuid4()}"))')


def append(source, blocks):
    pos = source.index('(sheet_instances')
    return source[:pos] + "\n" + "\n".join(blocks) + "\n" + source[pos:]


def main():
    backup = ROOT / 'build/backups/pre-active-swap'
    backup.mkdir(parents=True, exist_ok=True)
    for name in ['pcbgolf.kicad_sym', 'pcbgolf_4.kicad_sch', 'pcbgolf_5.kicad_sch']:
        shutil.copy2(ROOT / name, backup / name)

    lib = LIB.read_text()
    can = (ROOT / 'pcbgolf_4.kicad_sch').read_text()
    channels = (ROOT / 'pcbgolf_5.kicad_sch').read_text()

    op_map = {'2': ('4', '-IN'), '3': ('3', '+IN'), '4': ('2', 'V-'),
              '6': ('1', 'OUT'), '7': ('5', 'V+')}
    op_props = {'Value': 'OPA197IDBVR', 'Footprint': 'pcbgolf:SOT23-5',
                'MPN': 'OPA197IDBVR',
                'Description': '36 V precision rail-to-rail op amp, SOT-23-5',
                'ki_fp_filters': 'SOT23-5*'}
    _, _, old = symbol_block(lib, 'OPA197IDR')
    op_new = alter_symbol(old, 'OPA197IDR', 'OPA197IDBVR', op_map, op_props)
    lib = lib.rstrip()[:-1] + '\n' + op_new + '\n)\n'
    can, op_instances = cached_swap(can, 'pcbgolf:OPA197IDR',
                                     'pcbgolf:OPA197IDBVR', op_map, op_props)

    fet_map = {'1': ('2', 'G1'), '2': ('1', 'S1'), '3': ('5', 'G2'),
               '4': ('3', 'D2'), '5': ('6', 'D1')}
    fet_props = {'Value': 'AON2812',
                 'Footprint': 'pcbgolf:AON2812_DFN2x2A_6L_EP2_S',
                 'MPN': 'AON2812',
                 'Datasheet': 'https://www.aosmd.com/sites/default/files/res/datasheets/AON2812.pdf'}
    fet_extra = ('2', '4', 'S2', '7.62 -7.62 90')
    old_fet = 'comma.ai_11112255_NFET-DUAL-COMMON-SOURCE-QS5K2'
    lib = install_symbol(lib, old_fet, 'AON2812', fet_map, fet_props, fet_extra)
    channels, fet_instances = cached_swap(channels, 'pcbgolf:' + old_fet,
                                          'pcbgolf:AON2812', fet_map, fet_props, fet_extra)
    source_links = []
    for ref, coords in fet_instances:
        ox, oy, angle = [float(x) for x in coords.split()]
        assert angle == 0, ref
        source_links.append(wire(round(ox + 5.08, 4), round(oy + 7.62, 4),
                                 round(ox + 7.62, 4), round(oy + 7.62, 4)))
    channels = append(channels, source_links)

    green_map = {'A': ('2', 'A'), 'C': ('1', 'K')}
    green_props = {'Value': 'APG015ZGC/S-5MAV',
                   'Footprint': 'pcbgolf:Kingbright_APG015_01005',
                   'MPN': 'APG015ZGC/S-5MAV',
                   'Datasheet': 'https://www.kingbrightusa.com/images/catalog/SPEC/APG015ZGC-S-5MAV.pdf'}
    old_led = 'comma.ai_11112255_LED-0805'
    lib = install_symbol(lib, old_led, 'APG015ZGC_S-5MAV', green_map, green_props)
    can, green_can = cached_swap(can, 'pcbgolf:' + old_led,
                                 'pcbgolf:APG015ZGC_S-5MAV', green_map, green_props)
    channels, green_channels = cached_swap(channels, 'pcbgolf:' + old_led,
                                           'pcbgolf:APG015ZGC_S-5MAV', green_map, green_props)

    dual_map = {'1': ('1', 'R_A'), '2': ('3', 'G_A'), '3': ('2', 'R_K')}
    dual_props = {'Value': 'APTB1612ESGC-F01',
                  'Footprint': 'pcbgolf:Kingbright_APTB1612ESGC-F01',
                  'MPN': 'APTB1612ESGC-F01',
                  'Datasheet': 'https://www.kingbrightusa.com/images/catalog/SPEC/APTB1612ESGC-F01.pdf'}
    dual_extra = ('3', '4', 'G_K', '-2.54 -2.54 90')
    old_dual = 'comma.ai_11112255_LED-CC-GREEN-RED-AM23ESG'
    lib = install_symbol(lib, old_dual, 'APTB1612ESGC-F01',
                         dual_map, dual_props, dual_extra)
    channels, dual_instances = cached_swap(channels, 'pcbgolf:' + old_dual,
                                           'pcbgolf:APTB1612ESGC-F01',
                                           dual_map, dual_props, dual_extra)
    dual_links = []
    for ref, coords in dual_instances:
        ox, oy, angle = [float(x) for x in coords.split()]
        assert angle == 270, ref
        x, y = round(ox - 2.54, 4), round(oy, 4)
        dual_links.append(wire(x, round(y - 2.54, 4), x, y))
        # The first old common-cathode LED had a dangling ground stub.
        if ref == 'LED10':
            dual_links.append(label('GND', round(ox - 5.08, 4), y, 180))
    channels = append(channels, dual_links)

    # D3 was a disconnected example of the imported bicolor LED.
    for match in re.finditer(r'\(lib_id "pcbgolf:APTB1612ESGC-F01"\)', channels):
        start = channels.rfind('(symbol\n', 0, match.start())
        end = balanced(channels, start)
        if re.search(r'\(property "Reference" "D3"', channels[start:end]):
            channels = channels[:start] + channels[end:]
            break
    first, last, _ = symbol_block(channels, 'pcbgolf:APTB1612ESGC-F01')
    channels = channels[:first] + channels[last:]

    LIB.write_text(lib)
    (ROOT / 'pcbgolf_4.kicad_sch').write_text(can)
    (ROOT / 'pcbgolf_5.kicad_sch').write_text(channels)
    print('OPA', [r for r, _ in op_instances])
    print('FET', [r for r, _ in fet_instances])
    print('green LED', [r for r, _ in green_can + green_channels])
    print('red/green LED', [r for r, _ in dual_instances])


if __name__ == '__main__':
    main()
