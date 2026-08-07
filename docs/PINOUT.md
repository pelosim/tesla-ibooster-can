# docs/PINOUT.md

Working pinout for Tesla iBooster PN `1037123-00-B` (2020 Model S LR).

**Status: nothing in the hypothesis table has been measured on this unit.**
Confidence reflects agreement among community sources for *other* iBooster
variants (Golf MK8, Yaris Gen4, Citroën, Honda CR-V, generic Gen1/Gen2), not
evidence about this part number.

Connector: 26-pin EuCon (medium confidence — verify by cavity count and housing
markings in Phase 0).

---

## Hypothesis table

| Pin | Function | Terminal | Confidence | How to settle it |
|---|---|---|---|---|
| 1 | +12V permanent, 40A fused | large 4.8 spade | high | Heaviest terminal; continuity + current draw |
| 9 | GND | large 4.8 spade | high | Continuity to housing / ground stud |
| 17 | +12V permanent, 5A fused | medium 2.8 | low | **Gen1 only** — Gen2 reportedly drops this pin. Check whether the cavity is even populated |
| 20 | +12V ignition, 5A fused | small 1.5 | high | Behaviour: assist appears only when energised (Phase 4) |
| 25 | Vehicle CAN-H | small 1.5 | medium | ~2.5V idle when powered; scope the pair |
| 16 | Vehicle CAN-L | small 1.5 | medium | ~2.5V idle when powered; scope the pair |
| 18 | YAW CAN-H | small 1.5 | medium | Same |
| 10 | YAW CAN-L | small 1.5 | medium | Same |
| 2 | Pedal sensor — Gen1 #1 / Gen2 #2 | small 1.5 | low | Sources disagree; Gen1 and Gen2 swap the mapping |
| 8 | Pedal sensor — Gen1 #3 / Gen2 #4 | small 1.5 | low | Same |
| 22 | Pedal sensor — Gen1 #2 / Gen2 #1 | small 1.5 | low | Same |
| 23 | Pedal sensor — Gen1 #4 / Gen2 #3 | small 1.5 | low | Same |
| 24 | Brake signal output | small 1.5 | low | Reported on the VAG Gen2 unit; may not exist here |
| 4 | CLIN (to BCPM pin 2) | small 1.5 | low | Reported on the Yaris Gen2; Toyota-specific, likely absent |

**Both CAN buses: 500 kbps, no internal termination.** Higher confidence than the
individual pin numbers — this is consistent across every source.

The "vehicle" and "YAW" labels come from other platforms. On the Tesla unit,
identify each bus by **what it carries**, not by which pin it arrived on.

---

## Bench wiring (derived from the hypotheses above)

    iBooster pin 1  ── fuse ──  +12V        (battery for Phase 4+, not a bench PSU)
    iBooster pin 9  ─────────── GND ─┬── ESP32 GND
                                     └── SN65HVD230 GND
    iBooster pin 20 ── fuse ──  +12V        (Phase 4 only — motor becomes live)

    iBooster CAN-H ──┬── SN65HVD230 CANH
                     └── 120R ──┐
    iBooster CAN-L ──┬── SN65HVD230 CANL
                     └───────────┘         (second 120R is on the breakout)

    SN65HVD230 CTX ── ESP32 GPIO4
    SN65HVD230 CRX ── ESP32 GPIO8
    SN65HVD230 3V3 ── ESP32 3V3

Unpowered sanity check before applying power: **H-to-L reads ~60R.**

---

## CAN signal hypotheses

| Bus | ID | Claim | Confidence |
|---|---|---|---|
| YAW | `0x38E` | byte 3 = pedal position; idle `0x40` (64), full `0xC0` (192) | medium — **test this first, it is cheap** |
| YAW | `0x38F` | transmitted, purpose unknown | medium that it exists |
| Vehicle | ? | brake input stroke in mm, reportedly readable with a community Tesla DBC | low — ID unidentified |

From a GM Volt integration, for shape only — **not** applicable here and listed
solely so it is not mistaken for this unit's protocol later: `FrictionBrakeCmd`
ID 789 inbound, `FrictionBrakeStatus` ID 368 outbound.

Do not assume big-endian. Do not assume a raw byte is millimetres. Two known
displacement points from the Phase 5 sweep give you scale and offset.

---

## Measured results

_Empty. Add dated entries here as Phase 1–6 settle each row, and tick the matching
box in `VERIFY_FIRST.md`._
