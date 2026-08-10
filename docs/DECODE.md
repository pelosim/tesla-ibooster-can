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

## Other IDs seen — NOT yet decoded

**All on pins 25/16 only.** The 18/10 pair has not been captured yet, so nothing
below should be assumed to be the unit's complete output.

At rest with ignition on, four IDs. Under pedal activity, **eleven**.

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
