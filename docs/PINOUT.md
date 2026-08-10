# docs/PINOUT.md

Working pinout for Tesla iBooster PN `1037123-00-B` — **Gen1**, fitment 2016-2020 Model S.

**Status: the power and CAN pins are MEASURED on this unit** (2026-08-06) — see
Measured results at the bottom. The pedal-sensor and auxiliary rows below remain
unverified hypotheses from community work on *other* variants (Golf MK8, Yaris Gen4,
Citroën, Honda CR-V), and their confidence reflects agreement among those sources,
not evidence about this part number.

Connector: 26-pin EuCon (medium confidence — verify by cavity count and housing
markings in Phase 0).

---

## Hypothesis table

| Pin | Function | Terminal | Confidence | How to settle it |
|---|---|---|---|---|
| 1 | +12V permanent, 40A fused | large 4.8 spade | **CONFIRMED** | Powers the unit; assists with 1+9+20 |
| 9 | GND | large 4.8 spade | **CONFIRMED** | Powers the unit; assists with 1+9+20 |
| 17 | +12V permanent, 5A fused | medium 2.8 | low | **Gen1 has this pin** and this unit is Gen1, so expect it populated. Unverified |
| 20 | +12V ignition, 5A fused | small 1.5 | **CONFIRMED** | Assist present with this energised |
| 25 | Vehicle CAN-H | small 1.5 | **CONFIRMED** | Captured 0x39D at 500 kbps with this polarity |
| 16 | Vehicle CAN-L | small 1.5 | **CONFIRMED** | Captured 0x39D at 500 kbps with this polarity |
| 18 | YAW CAN-H | small 1.5 | **CONFIRMED** | Captured 0x38E/0x38F at 500 kbps |
| 10 | YAW CAN-L | small 1.5 | **CONFIRMED** | Captured 0x38E/0x38F at 500 kbps |
| 2 | Pedal sensor #1 (Gen1 mapping) | small 1.5 | low | Gen1 mapping applies here. Unverified |
| 8 | Pedal sensor #3 (Gen1 mapping) | small 1.5 | low | Unverified |
| 22 | Pedal sensor #2 (Gen1 mapping) | small 1.5 | low | Unverified |
| 23 | Pedal sensor #4 (Gen1 mapping) | small 1.5 | low | Unverified |
| 24 | Brake signal output | small 1.5 | low | Reported on the VAG Gen2 unit; may not exist here |
| 4 | CLIN (to BCPM pin 2) | small 1.5 | low | Reported on the Yaris Gen2; Toyota-specific, likely absent |

**Both CAN buses: 500 kbps, no internal termination.** Higher confidence than the
individual pin numbers — this is consistent across every source.

The "vehicle" and "YAW" labels come from other platforms. On the Tesla unit,
identify each bus by **what it carries**, not by which pin it arrived on.

---

## Bench wiring (derived from the hypotheses above)

Primary: the CANable clone (Jhoinrch RH02), screw terminals CANH / GND / CANL.

    iBooster pin 1  ── fuse ──  +12V     (battery for Phase 4+, not a bench PSU)
    iBooster pin 9  ─────────── GND ──── CANable GND
    iBooster pin 20 ── fuse ──  +12V     (Phase 4 only — motor becomes live)

    iBooster CAN-H ──┬── CANable CANH    (R120 ON at the dongle)
                     └── 120R ──┐
    iBooster CAN-L ──┬── CANable CANL
                     └───────────┘       (loose 120R at the booster end)

Fallback, if the ESP32 path is ever taken up:

    SN65HVD230 CANH/CANL/GND  as above
    SN65HVD230 CTX ── ESP32 GPIO4
    SN65HVD230 CRX ── ESP32 GPIO8
    SN65HVD230 3V3 ── ESP32 3V3

Unpowered sanity check before applying power: **H-to-L reads ~60R.**

⚠️ **R120 inverts between the two buses you will touch.** ON for the iBooster
(2 nodes, booster terminates neither end); **OFF** when tapping the iDrive bus in
Phase -1 (already terminated both ends — you would be a third). Both are 500 kbps
2-node buses, so label the dongle rather than trusting memory.

⚠️ **Not the MCP2551.** 5V-only: RXD swings to 5V into a non-5V-tolerant S3 GPIO,
and TXD's 3.5V threshold sits above the 3.3V the S3 drives — a marginal high read as
dominant jams the bus. SN65HVD230 or TJA1051T/3 only.

---

## CAN signal hypotheses

| Bus | ID | Community claim | Outcome on this unit |
|---|---|---|---|
| YAW | `0x38E` | byte 3 = pedal position; idle `0x40`, full `0xC0` | **Half right.** Idle `0x40` exact. But `b3` is the *low byte* of a 16-bit LE field with `b4`, so it wraps — `0xC0` is a mid-travel value here, not full scale |
| YAW | `0x38F` | transmitted, purpose unknown | **Confirmed present**, 49.8 Hz. Still undecoded |
| Vehicle | ? | brake input stroke in mm | **Found**: `0x39D` b2:b3 uint16 LE. Not millimetres raw — 320.68 counts/mm |

From a GM Volt integration, for shape only — **not** applicable here and listed
solely so it is not mistaken for this unit's protocol later: `FrictionBrakeCmd`
ID 789 inbound, `FrictionBrakeStatus` ID 368 outbound.

Do not assume big-endian. Do not assume a raw byte is millimetres. Two known
displacement points from the Phase 5 sweep give you scale and offset.

---

## Measured results — 2026-08-06

**Power:** pin 1 = 12 V, pin 9 = GND, pin 20 = ignition. With only these three the
booster **assists** — no CAN input of any kind required.

**CAN, both buses 500 kbps, neither internally terminated:**

| Bus | CAN-H | CAN-L | Verified by |
|---|---|---|---|
| Vehicle | **25** | **16** | `0x39D`, `0x33D`, `0x35D`, `0x32D` + 8 more decoded off it |
| YAW | **18** | **10** | `0x38E` @ 99.7 Hz, `0x38F` @ 49.8 Hz |

Polarity is **assigned, not merely paired** — these orientations produced clean
frames. Signals in [DECODE.md](DECODE.md).

⚠️ Contact at these pins is the failure mode that cost six rounds of debugging.
Verify continuity from the adapter's screw terminal through to the pin.

**Not measured:** the pedal-sensor pins (2, 8, 22, 23), pin 17, pin 24, pin 4, and
peak current draw during assist. Those rows above remain hypotheses.
