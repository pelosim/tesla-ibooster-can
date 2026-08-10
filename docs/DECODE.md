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

### ⚠️ Second run contradicts the first — position measurement is the bottleneck

A second capture held at 10/20/30 mm. It does not agree with the first:

| mm | measured counts | run |
|---|---|---|
| 10 | 3048.0 | 2 |
| 20 | 6886.4 | 2 |
| **21** | **6114.0** | **1** |
| 30 | 10286.5 | 2 |
| 42 | 13125.2 | 1 |

**20 mm reads higher than 21 mm.** A monotonic sensor cannot do that, so at least one
set of physical positions is wrong.

| | counts/mm |
|---|---|
| run 1 (21, 42) | 333.87 |
| run 2 (10, 20, 30) | 361.93 |
| all five points | 320.68 |

Residuals against the combined fit are +-2 mm and **flip sign by run** rather than
scattering randomly — the signature of a datum shift between runs, not noise.

**The limiting factor is the ruler, not the CAN data:**

| | precision |
|---|---|
| CAN value within a single hold | **+-20 counts = 0.062 mm** |
| disagreement between runs | **up to 4.4 mm** |

The signal is ~70x more precise than the measurement of it. More captures will not
help; better instrumentation will.

**Dead band: still unresolved.** The run-1 model predicts 2441 counts at 10 mm; run 2
measured 3048. That 1.8 mm gap is inside the run-to-run error, so the dead band is
neither confirmed nor refuted — it is simply swamped.

### To calibrate properly

- **Dial indicator with a fixed datum**, referencing the same feature every time.
- **One single run covering the whole range** — rest, 5, 10, 20, 30, 40, end stop.
  The error is *between* runs, not within them, so a single run eliminates it
  entirely regardless of instrument quality.

### Is this good enough already?

For **display and logging — yes.** The scope is a status indicator, and ~2 mm accuracy
on pedal travel is far more than that needs. Use the combined fit:

    mm = (counts - 3.3) / 320.68

Chasing better numbers is only worth it if something downstream ever needs absolute
millimetres, which nothing currently does.
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
| `b3` | position, **LOW byte** | `0x40` at settled rest; wraps, because it is not the whole field |
| `b4` | position, **HIGH byte** | `0x11` at settled rest |
| `b4` | — | constant `11` at rest |
| `b5:b7` | — | constant `00` |

### `b3:b4` = position, uint16 LITTLE-endian — CONFIRMED

`b3` alone wraps because **it is the low byte**. `b4` is the high byte. Visible
directly in the boot trace: across a fast push `b4` climbs `17->18->19->1A->1B` and
walks straight back down `1A->19->...->11` on release, once per `b3` wrap.

    position = b3 | (b4 << 8)      rest 4416 (0x1140), full travel ~7148

**Validated against the calibrated `0x39D`** on two independent runs:

| Run | matched samples | fit | r |
|---|---|---|---|
| 1 | 15296 | `39D = 4.8797 * X - 21290.3` | **0.999627** |
| 2 | 12116 | `39D = 4.8736 * X - 21264.2` | **0.999853** |

The two runs agree to **0.13% on slope and 0.12% on intercept** — far tighter than
either agrees with the ruler, which independently confirms that the run-to-run
calibration conflict was measurement error and not the sensor.

    mm = 0.015207 * (b3 | b4<<8) - 66.36

Sanity check: rest 4416 -> 0.79 mm, and 7148 -> 42.3 mm. Both consistent with the
`0x39D` calibration.

### Two corrections

1. **`b3` is not unusable and `b4` is not a state field.** An earlier reading here
   claimed `b3:b4` "does not fit linearly in either endianness" and that `b4`
   advanced "far too fast to be a carry". Both were wrong, and came from averaging
   over time windows that spanned the boot transition — `b4` reads `0x01` before
   the sensor initialises at ~1.5 s and `0x11` after, so any window crossing that
   point mixes two regimes.
2. **`0x39D` is ~4.88x finer than `0x38E`, not "over 100x".** The 100x figure came
   from treating `b3` as an 8-bit field. Real resolution: `0x38E` gives ~2732 counts
   over full travel (~0.016 mm/count), `0x39D` ~13350 (~0.003 mm/count). `0x39D`
   remains the better choice, but `0x38E` at 99.7 Hz is perfectly usable — and it is
   **4x faster**, which matters more than resolution for anything rate-sensitive.

The community's *idle* `0x40` for `b3` transfers exactly. Their `0xC0` full-scale
claim does not, because `b3` is only the low byte on this firmware.

---

## Power-up sequence — CONFIRMED 2026-08-06

Consistent across both captures, ms after the first frame:

| t | bus | ID | note |
|---|---|---|---|
| 0 | both | `0x33D` / `0x38E` | first out of the gate, within 2 ms of each other |
| ~88 | both | `0x38F`, `0x39D` | |
| ~150 | VEH | `0x5BD` | |
| ~1070 | VEH | `0x35D` | |
| ~1400-1500 | VEH | `0x30D` | fires once per boot |
| ~2070 | VEH | `0x32D` | |
| ~2190 | VEH | `0x3AD` | |

**Sensor initialises at ~1.47 s**: `0x38E` position jumps from 320 (`b4=0x01`, a
pre-init reading) to 4416 (`b4=0x11`, true rest). Treat anything before that as
invalid.

`0x31D` `0x34D` `0x36D` `0x37D` `0x38D` are **not** part of boot — they appeared at
6.9 s in one run and 56.7 s in the other, always as a group within ~100 ms. Event
driven, trigger unknown.

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
