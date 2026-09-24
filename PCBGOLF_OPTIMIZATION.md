# PCBGolf schematic optimization

## Selected parts

| Function | Part | Package / footprint | Source |
|---|---|---|---|
| MCU | STM32H503EBY6TR | WLCSP-25, 2.33 × 2.24 mm | LCSC C26803530 |
| 12 V to 5 V LDO | LT3083IDF#TRPBF | 4 × 4 mm DFN-12 EP | LCSC C670355 |
| 5 V to 3.3 V LDO | TLV76733DRVR | 2 × 2 mm WSON-6 EP | LCSC C2848334 |
| Addressable RGB | XL-1010RGBC-WS2812B | 1 × 1 mm | LCSC C5349953 |
| 16-bit GPIO expanders | 2 × AW9523BTQR | 4 × 4 mm VFQFPN-24 EP | LCSC C148077 |
| Analog sense selector | 74HC4067BQ,118 | 5.5 × 3.5 mm DHVQFN-24 EP | LCSC C547033 |
| CAN RX selector | TMUX1204DQAR | 2.5 × 1.0 mm USON-10 | LCSC C1849379 |
| 12 V input protection FET | DMP3026SFDF-7 | 2 × 2 mm U-DFN2020-6 | [Diodes](https://www.diodes.com/datasheet/download/DMP3026SFDF.pdf) |
| Channel dual FETs | 8 × AON2812 | 2 × 2 mm DFN | [AOS](https://www.aosmd.com/sites/default/files/res/datasheets/AON2812.pdf) |
| CAN sense amplifiers | 4 × OPA197IDBVR | SOT-23-5 | [TI](https://www.ti.com/lit/ds/symlink/opa197.pdf) |
| Green indicators | 8 × APG015ZGC/S-5MAV | 01005 | [Kingbright](https://www.kingbrightusa.com/images/catalog/SPEC/APG015ZGC-S-5MAV.pdf) |
| Red/green channel indicators | 8 × APTB1612ESGC-F01 | 1.6 × 1.25 mm, four pins | [Kingbright](https://www.kingbrightusa.com/images/catalog/SPEC/APTB1612ESGC-F01.pdf) |

All new symbols, footprints, and 3D models are project-local. The three PCB-edge
USB-C footprints (`PCBTypeC_10P`, `PCBTypeC_14P`, and `PCBTypeC_24P`) and their
symbols were copied into the `pcbgolf` project libraries.

The eight AON2812 devices have separately wired source pins 1 and 4. The
four-pin red/green indicators have separate cathodes 2 and 4, both tied to
ground. The OPA197 SOT-23-5 pin mapping was checked against TI's package pinout:
OUT 1, V− 2, +IN 3, −IN 4, V+ 5. No standalone red indicator is populated, so
APG015SURKKC-TT is retained as an option rather than placed.

The MCU, CAN selector, RGB indicator, and power regulators were reconnected to
their new symbol pin locations. All five schematic netlists export; none of
the five ERC reports has a `pin_not_connected` finding. Other ERC warnings
remain, especially on the standalone sheets that use global labels to join
signals across files.

All 217 placed schematic components point to an existing project-local
footprint. Their symbol pin numbers match footprint pad numbers except for the
legacy J1 barrel jack: its `DCJACK_2MM_SMT` footprint has an extra `PWR2` pad
that the J1 symbol does not define. The [manufacturer drawing](https://www.sameskydevices.com/product/resource/pj-002ah-smt-tr.pdf)
shows two physical pads for terminal 1 and one each for terminals 2 and 3; the
legacy footprint needs a separate mechanical and pad-number review before PCB
release. This audit did not alter the board.

## MCU I/O architecture

The WLCSP-25 part exposes only 19 GPIOs, so low-speed channel signals were
consolidated as follows:

- Native MCU: USB FS, one FDCAN RX/TX pair, SPI-mode SD card, SWD, I2C, button,
  addressable RGB data, one analog sense input, and two expander interrupts.
- U13: all 16 SBU ignition/relay controls.
- U14: four channel power enables, four CAN standby controls, four analog mux
  selects, and two CAN RX mux selects.
- U15: eight divided SBU sense signals and four current-monitor signals into one
  MCU ADC input.
- U16: four MCP2542FD RXD outputs into the single FDCAN RX input. All four
  transceiver TXD inputs share the single FDCAN TX signal. Firmware must put all
  unselected transceivers in standby before changing `CAN_SEL[1:0]`.

The SD interface is now SPI (`SD_CLK`, `SD_CMD`, `SD_D0`, `SD_D3`); `SD_D1` and
`SD_D2` are intentionally unused.

## Passive and decoupling policy

- General resistors and low-value capacitors use project-local 01005 footprints.
- MCU-rail bulk capacitors use 0201 where voltage and capacitance permit.
- 5 V/12 V bulk capacitors remain 0402 to preserve realistic capacitance and
  voltage derating.
- Power inductors and CAN common-mode chokes retain their electrically required
  footprints.
- The H725 SMPS network, HSE crystal network, duplicate VCAP capacitor, and DNP
  buck components were removed. The H503 VCAP capacitor, VDD/VDDA bypassing, and
  one 100 nF bypass per newly added active IC are retained.

## Engineering constraints requiring review

1. **12 V to 5 V thermal limit:** the LT3083 is electrically rated for 3 A, but a
   linear 12 V to 5 V conversion dissipates `(12 - 5) × ILOAD`. At 3 A this is
   21 W and is not thermally viable in this footprint. Confirm the measured 5 V
   load and provide copper/thermal protection, reduce the load, lower the input
   voltage, or explicitly allow a switching preregulator.
2. **MCU resources:** STM32H503EBY6TR has 128 KB flash and 32 KB SRAM, versus the
   much larger memory budget of the original STM32H725. Firmware must fit this
   reduced memory and implement the GPIO/analog/CAN selection state machines.
3. **PCB-edge USB-C:** the imported connector library is intended for 0.6 or
   0.8 mm PCB thickness and limited mating cycles. Confirm the final stack-up and
   mechanical use case before fabrication.
4. **Input surge:** D1 is the existing SMAJ16CA TVS. Its specified maximum clamp
   is 26 V at the rated 400 W pulse, leaving only 4 V to the DMP3026's 30 V
   drain-source limit. That is less than a 20% derating margin, and a qualified
   automotive load-dump pulse has not been checked against this protection
   network. Confirm the actual transient profile and redesign the clamp/FET
   protection if automotive surge survival is required. See the
   [SMAJ16CA](https://www.diodes.com/part/view/SMAJ16CA) and
   [DMP3026](https://www.diodes.com/part/view/DMP3026SFDF) ratings.
5. **PCB update:** the schematic part and net changes have not been applied to
   `pcbgolf.kicad_pcb`. The board was restored to its pre-sync state at the
   user's request to avoid layout work. Update it separately when PCB work is
   authorized.

## Reproduction and checks

`tools/optimize_pcbgolf.py` records the initial KiStack/easyeda2kicad
transformation. The `tools/reconnect_*.py` and `tools/swap_active_symbols.py`
scripts record the subsequent schematic changes. KiCad 10 netlist export
succeeds for all five schematic files. Current ERC reports are in
`build/work/`; backups are in `build/backups/`.
