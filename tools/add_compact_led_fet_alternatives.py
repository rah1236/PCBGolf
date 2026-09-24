#!/usr/bin/env python3
"""Add compact, unplaced LED/FET alternatives to the project KiCad libraries."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STAGING = Path("/private/tmp/pcbgolf-compact-alternatives")
LIB = ROOT / "pcbgolf.kicad_sym"
PRETTY = ROOT / "pcbgolf.pretty"
SHAPES = ROOT / "pcbgolf.3dshapes"


def block(source: str, name: str) -> str:
    start = source.index(f'(symbol "{name}"')
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
                return source[start : i + 1]
    raise ValueError(name)


def pin(number: str, name: str, x: float, y: float, angle: int) -> str:
    return f'''      (pin passive line (at {x} {y} {angle}) (length 2.54)
        (name "{name}" (effects (font (size 1.27 1.27))))
        (number "{number}" (effects (font (size 1.27 1.27)))))'''


def simple_symbol(name: str, reference: str, footprint: str, datasheet: str,
                  description: str, pins: list[tuple[str, str, float, float, int]],
                  mpn: str | None = None) -> str:
    pin_text = "\n".join(pin(*p) for p in pins)
    return f'''(symbol "{name}"
    (in_bom yes) (on_board yes)
    (property "Reference" "{reference}" (id 0) (at 0 7.62 0)
      (effects (font (size 1.27 1.27))))
    (property "Value" "{name}" (id 1) (at 0 -7.62 0)
      (effects (font (size 1.27 1.27))))
    (property "Footprint" "pcbgolf:{footprint}" (id 2) (at 0 -10.16 0)
      (effects (font (size 1.27 1.27)) hide))
    (property "Datasheet" "{datasheet}" (id 3) (at 0 -12.7 0)
      (effects (font (size 1.27 1.27)) hide))
    (property "Description" "{description}" (id 4) (at 0 -15.24 0)
      (effects (font (size 1.27 1.27)) hide))
    (property "MPN" "{mpn or name}" (id 5) (at 0 -17.78 0)
      (effects (font (size 1.27 1.27)) hide))
    (symbol "{name}_0_1"
      (rectangle (start -2.54 5.08) (end 2.54 -5.08)
        (stroke (width 0.254) (type default)) (fill (type background))))
    (symbol "{name}_1_1"
{pin_text}
    )
  )'''


def footprint(name: str, pads: list[tuple[str, float, float, float, float]],
              width: float, height: float, value: str) -> str:
    # This is a top-view land pattern, not a drawing of the underside of the part.
    pad_text = "\n".join(
        f'  (pad "{n}" smd rect (at {x} {y}) (size {w} {h}) (layers "F.Cu" "F.Paste" "F.Mask"))'
        for n, x, y, w, h in pads
    )
    return f'''(footprint "{name}" (version 20240108) (generator "pcbnew")
  (layer "F.Cu")
  (property "Reference" "REF**" (at 0 {-height / 2 - 0.8:.3f}) (layer "F.SilkS")
    (effects (font (size 0.6 0.6) (thickness 0.1))))
  (property "Value" "{value}" (at 0 {height / 2 + 0.8:.3f}) (layer "F.Fab")
    (effects (font (size 0.6 0.6) (thickness 0.1))))
  (attr smd)
  (fp_rect (start {-width / 2:.3f} {-height / 2:.3f})
    (end {width / 2:.3f} {height / 2:.3f})
    (stroke (width 0.05) (type default)) (fill none) (layer "F.Fab"))
  (fp_rect (start {-width / 2 - 0.1:.3f} {-height / 2 - 0.1:.3f})
    (end {width / 2 + 0.1:.3f} {height / 2 + 0.1:.3f})
    (stroke (width 0.05) (type default)) (fill none) (layer "F.CrtYd"))
{pad_text}
)\n'''


def install() -> None:
    staged = (STAGING / "compact.kicad_sym").read_text()
    imported = []
    for name in ("DMP3026SFDF-7", "APHHS1005LCGCK"):
        b = block(staged, name).replace("compact:", "pcbgolf:")
        if name == "DMP3026SFDF-7":
            b = b.replace("https://www.lcsc.com/datasheet/C461076.pdf",
                          "https://www.diodes.com/datasheet/download/DMP3026SFDF.pdf")
            b = b.replace("pcbgolf:U-DFN2020-6_L2.0-W2.0-P0.65-BL-DMP2035UFDF-7",
                          "pcbgolf:DMP3026SFDF-7_U-DFN2020-6")
        else:
            b = b.replace("https://www.lcsc.com/datasheet/C5354975.pdf",
                          "https://www.kingbrightusa.com/images/catalog/spec/aphhs1005lcgck.pdf")
        imported.append(b)

    handmade = [
        simple_symbol("AON2812", "Q", "AON2812_DFN2x2A_6L_EP2_S",
                      "https://www.aosmd.com/sites/default/files/res/datasheets/AON2812.pdf",
                      "30 V dual N-MOSFET, 4.5 A, Rds(on) max 70 mOhm at 2.5 V; independent sources",
                      [("1", "S1", -7.62, 2.54, 0), ("2", "G1", -7.62, 0, 0),
                       ("3", "D2", 7.62, -2.54, 180), ("4", "S2", -7.62, -2.54, 0),
                       ("5", "G2", -7.62, -5.08, 0), ("6", "D1", 7.62, 2.54, 180)]),
        simple_symbol("APG015ZGC_S-5MAV", "D", "Kingbright_APG015_01005",
                      "https://www.kingbrightusa.com/images/catalog/SPEC/APG015ZGC-S-5MAV.pdf",
                      "01005 green LED, 525 nm, 220 mcd typ at 5 mA",
                      [("1", "K", -7.62, 0, 0), ("2", "A", 7.62, 0, 180)],
                      "APG015ZGC/S-5MAV"),
        simple_symbol("APG015SURKKC-TT", "D", "Kingbright_APG015_01005",
                      "https://www.kingbrightusa.com/images/catalog/SPEC/APG015SURKKC-TT.pdf",
                      "01005 hyper-red LED, 631 nm, 105 mcd typ at 10 mA",
                      [("1", "K", -7.62, 0, 0), ("2", "A", 7.62, 0, 180)]),
        simple_symbol("APTB1612ESGC-F01", "D", "Kingbright_APTB1612ESGC-F01",
                      "https://www.kingbrightusa.com/images/catalog/SPEC/APTB1612ESGC-F01.pdf",
                      "1.6 x 1.25 mm red/green LED, separate anode and cathode for each color",
                      [("1", "R_A", 7.62, 2.54, 180), ("2", "R_K", -7.62, 2.54, 0),
                       ("3", "G_A", 7.62, -2.54, 180), ("4", "G_K", -7.62, -2.54, 0)]),
    ]

    library = LIB.read_text()
    for b in imported + handmade:
        name = re.match(r'\(symbol "([^"]+)"', b).group(1)
        if f'(symbol "{name}"' in library:
            raise ValueError(f"symbol already exists: {name}")
    LIB.write_text(library.rstrip()[:-1] + "\n" + "\n".join(imported + handmade) + "\n)\n")

    # Imported EasyEDA models stay project-local. The P-FET package has six side
    # lands plus separate drain/source thermal lands (pads 7 and 8).
    for filename, installed in (("U-DFN2020-6_L2.0-W2.0-P0.65-BL-DMP2035UFDF-7", "DMP3026SFDF-7_U-DFN2020-6"),
                                ("LED0402-RD_GREEN", "LED0402-RD_GREEN")):
        src = STAGING / "compact.pretty" / f"{filename}.kicad_mod"
        dst = PRETTY / f"{installed}.kicad_mod"
        if dst.exists():
            raise ValueError(f"footprint already exists: {dst}")
        content = src.read_text().replace("compact.3dshapes", "pcbgolf.3dshapes")
        if installed != filename:
            content = content.replace(f"easyeda2kicad:{filename}", installed)
            content = content.replace(f"{filename}.wrl", f"{installed}.wrl")
            content = content.replace(f"{filename}.step", f"{installed}.step")
            content = content.replace(f"(fp_text value {filename}", f"(fp_text value {installed}")
            content = content.replace("(attr through_hole)", "(attr smd)")
        dst.write_text(content)
        for suffix in ("step", "wrl"):
            src_model = STAGING / "compact.3dshapes" / f"{filename}.{suffix}"
            dst_model = SHAPES / f"{installed}.{suffix}"
            if dst_model.exists():
                raise ValueError(f"model already exists: {dst_model}")
            dst_model.write_bytes(src_model.read_bytes())

    led_pads = [("1", -0.14, 0, 0.15, 0.20), ("2", 0.14, 0, 0.15, 0.20)]
    (PRETTY / "Kingbright_APG015_01005.kicad_mod").write_text(
        footprint("Kingbright_APG015_01005", led_pads, 0.45, 0.25, "Kingbright APG015 01005 LED"))
    aon_pads = [
        ("1", -0.65, 0.8625, 0.30, 0.325),
        ("2", 0, 0.8625, 0.30, 0.325),
        ("3", 0.65, 0.8625, 0.30, 0.325),
        ("4", 0.65, -0.8625, 0.30, 0.325),
        ("5", 0, -0.8625, 0.30, 0.325),
        ("6", -0.65, -0.8625, 0.30, 0.325),
        ("6", -0.47, 0, 0.615, 0.725),
        ("3", 0.47, 0, 0.615, 0.725),
    ]
    (PRETTY / "AON2812_DFN2x2A_6L_EP2_S.kicad_mod").write_text(
        footprint("AON2812_DFN2x2A_6L_EP2_S", aon_pads, 2.0, 2.0, "AON2812"))
    bicolor_pads = [
        ("1", 0.825, -0.4, 0.8, 0.4), ("2", -0.825, -0.4, 0.8, 0.4),
        ("3", 0.825, 0.4, 0.8, 0.4), ("4", -0.825, 0.4, 0.8, 0.4),
    ]
    (PRETTY / "Kingbright_APTB1612ESGC-F01.kicad_mod").write_text(
        footprint("Kingbright_APTB1612ESGC-F01", bicolor_pads, 1.6, 1.25,
                  "APTB1612ESGC-F01"))


if __name__ == "__main__":
    install()
