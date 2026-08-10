# DECODE.md

Confirmed signal definitions for the Tesla iBooster `1037123-00-B`.

Everything here is **measured on this unit**, not inherited from community sources.
Anything unverified belongs in `VERIFY_FIRST.md`, not here.

---

## `0x39D` — brake pedal stroke — CONFIRMED 2026-08-06

500 kbps · DLC 4 · **25.0 Hz**

**Bus: pin 25 = CAN-H, pin 16 = CAN-L.** Confirmed by capture, not just by pairing —
this exact polarity produced clean frames, so H/L are assigned, not merely paired.
Under the community naming this is the **"Vehicle CAN"**, and it is consistent with
their claim that the vehicle bus carries brake input stroke. The second pair
(18/10, their "YAW CAN") is **not yet captured**.

| Byte | Field | Notes |
|---|---|---|
| `b0` | checksum | `(b1 + b2 + b3 + 0xA0) & 0xFF` — **validates on 100% of 2250 frames** |
| `b1` | alive counter | +1 per frame, mod 16. Upper nibble always 0 |
| `b2:b3` | **stroke, uint16 little-endian** | rest ≈ **262**, max observed **14070** |

### Raw examples

    B7 0E 08 01   counter 14, stroke 264   (at rest)
    85 00 C8 1D   counter  0, stroke 7624  (mid-travel)
    D4 0B F8 31   counter 11, stroke 12792 (near full)

### How it was identified

Ranking candidate fields by *smoothness* — `mean(|delta|) / range` — rather than by
range. A checksum or counter spans 00..FF but jumps randomly frame to frame; a
physical signal moves smoothly. `b2:b3` LE scored 0.009 against ~0.12 for the
counter/checksum pair. `tools/analyze.py` does this.

### Scaling — CALIBRATED 2026-08-06

Two-point fit from held plateaus at 21 mm and 42 mm (161 and 80 samples):

    counts = 333.866 * mm - 897.2
    mm     = (counts + 897.2) / 333.866

    0.0030 mm per count  (~3 um resolution)

| Position | Raw (measured) | Samples |
|---|---|---|
| rest | **263.1** | 319 |
| 21 mm | **6114.0** | 161 |
| 42 mm | **13125.2** | 80 |
| end-stop pulse | **13606** (peak) = **43.44 mm** | — |

**Rest does not sit on the line.** 263 counts extrapolates to 3.475 mm, not zero.
The consistent explanation is roughly **3.5 mm of free play** before the sensor
engages, with the reading held at a floor of ~263 below that:

    263 + 333.87 * (21 - 3.475) = 6113   (measured 6114)
    263 + 333.87 * (42 - 3.475) = 13123  (measured 13125)

Both within 2 counts.

⚠️ **Only one point below the dead band was measured**, so this cannot yet
distinguish a hard floor from a non-linear region near rest. A third hold at ~10 mm
would settle it. Do not rely on values under ~4 mm meaning anything.
- Whether `b1` rolling over or a checksum failure ever signals anything meaningful.
- Whether the 0xA0 constant is fixed or derived from the CAN ID. `0x39D + 3 = 0x3A0`,
  whose low byte is `0xA0` — that is almost certainly a coincidence, but a second
  message with a checksum would settle it.

---

## The two buses

| Bus | Pins | Rate at rest | IDs | Carries |
|---|---|---|---|---|
| "Vehicle CAN" | **25 = H, 16 = L** | 36.4 fps | 4 at rest, 11 under activity | `0x39D` 16-bit stroke |
| "YAW CAN" | **18 = H, 10 = L** | **149.5 fps** | 2 | `0x38E` 99.7 Hz, `0x38F` 49.8 Hz |

Community naming holds on this unit — their documented YAW IDs `0x38E`/`0x38F` are
exactly what appears on 18/10.

⚠️ **Adapter index is not stable.** USB indices reorder on replug. Identify which
adapter is on which bus **by content** — whichever sees `0x39D` is on 25/16 — never
by index or USB address.

---

## `0x38E` — YAW bus — PARTIALLY DECODED 2026-08-06

500 kbps · DLC 8 · **99.7 Hz** · pins 18/10

At rest: `77 2B 00 40 11 00 00 00`

| Byte | Field | Notes |
|---|---|---|
| `b0` | checksum? | ranges 1E..F9, varies every frame — same role as `0x39D` `b0` |
| `b1` | alive counter | `0x20`..`0x2F` — low nibble counts, upper nibble fixed at 2 |
| `b2` | — | constant `00` at rest |
| `b3` | position, **8-bit and WRAPS** | `0x40` at rest as the community states — but see below |
| `b4` | — | constant `11` at rest |
| `b5:b7` | — | constant `00` |

### ⚠️ `b3` wraps — do not use it as a position signal

Measured against the same physical holds: rest `64`, 21 mm `246`. That is
**8.67 counts/mm**, so `b3` passes `0xC0` (192) at about **14.8 mm**, not at full
travel, and exceeds 255 and **wraps** before 42 mm. Its observed range is the full
`00..FF`.

The community's *idle* value (`0x40`) transfers exactly. Their *full-scale* claim
(`0xC0`) does not — this firmware uses roughly 2.8x their scaling, so `0xC0` is a
mid-travel value here, not an endpoint.

Where the high bits live is **unresolved**. `b4` also moves (15 -> 21 -> 27 across
the three holds) but is not the high byte: it advances ~6 per 21 mm, far too fast
for a carry. `b3:b4` as 12- or 16-bit, either endianness, does not fit linearly.

**Use `0x39D` instead.** It gives 13822 counts over the same travel against `b3`'s
~128 before wrapping — over 100x finer, no wrap, and calibrated.

## `0x38F` — YAW bus — NOT decoded

500 kbps · DLC 8 · **49.8 Hz** · at rest `3F 2D E2 53 02 00 00 00`

Same header shape: `b0` varies every frame (checksum), `b1` = `0x20`..`0x2F`
counter. `b2:b4` constant at rest (`E2 53 02`), `b5:b7` zero. Nothing moved at rest —
needs a pedal sweep before anything can be said.

---

## Other IDs seen — NOT yet decoded

**Vehicle bus (25/16).** At rest with ignition on, four IDs. Under pedal activity,
**eleven**.

| ID | rate | at-rest bytes | note |
|---|---|---|---|
| `0x39D` | 25.0 Hz | `B5 0C 08 01` | decoded above |
| `0x33D` | 10.1 Hz | `00 00 FF FF FF FF FF FF` | trailing `FF` = signals unavailable; comes alive under activity |
| `0x35D` | 1.0 Hz | `05 55 55 55 55 55 55 55` | `0x55` fill — placeholder |
| `0x32D` | 0.5 Hz | `0D 00 00 00 8D 79 20 21` | structured; identity or config? |
| `0x3AD` | 0.2 Hz | — | appears under activity |
| `0x31D` `0x34D` `0x36D` `0x37D` `0x38D` | 0.1 Hz | — | **appear together in a burst**, 6 frames each, first seen within 0.1 s of one another. Likely one logical group |
| `0x5BD` | one-shot | `CF 40 01 00 00 00 00 00` | seen once |

⚠️ `0x33D`'s bytes rank as "smooth" in `analyze.py` but are a **false positive**: they
sit at `FF` and jump rarely, so mean delta stays low. Judge by the plotted shape, not
the smoothness number alone.
