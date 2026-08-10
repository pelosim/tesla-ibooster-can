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

### Not yet known

- **Physical scaling.** rest ≈ 262 and full ≈ 14070 are raw counts. Converting to mm
  needs a sweep with a dial indicator and two known displacement points. Do not
  assume the raw value is millimetres, or that rest is a true zero.
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
| `b3` | **pedal position** | **`0x40` at rest — matches the community's stated idle exactly.** Their claim of `0xC0` at full travel is **untested** |
| `b4` | — | constant `11` at rest |
| `b5:b7` | — | constant `00` |

**Resolution note:** this is an 8-bit signal spanning roughly `0x40`..`0xC0`, about
128 counts. `0x39D` on the other bus gives 13822 counts over the same travel — over
100x finer. Prefer `0x39D` for anything that logs or displays a value.

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
