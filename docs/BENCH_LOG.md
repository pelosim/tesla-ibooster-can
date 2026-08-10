# BENCH_LOG.md

Dated findings, measured only. Signal definitions live in `docs/DECODE.md`;
outstanding hypotheses live in `VERIFY_FIRST.md`.

---

# 2026-08-06 — Bring-up complete

One bench session took this from an unpowered ECU to a calibrated, decoded,
read-only monitor. Headlines:

- **✅ It assists standalone.** No vehicle CAN, no wake frame, no keep-alive. The
  read-only design is viable and the risk of ever transmitting to a brake actuator
  is closed, not deferred. This was the project's central question.
- **✅ Both buses found, both decoded enough to use.** Pins 25/16 (H/L) carry a
  calibrated 16-bit stroke; pins 18/10 carry a second, faster position signal.
- **✅ Stroke calibrated to millimetres**, to roughly ±2 mm — limited by the ruler,
  not by the data.
- **✅ Phase 7 resolved to option A** — CANable straight onto the Pi.

---

## Confirmed hardware facts

| | |
|---|---|
| Adapter | CANable clone (Jhoinrch RH02), **candleLight/gs_usb** `1d50:606f` — no serial port |
| Vehicle bus | **pin 25 = CAN-H, pin 16 = CAN-L**, 500 kbps, 36 fps, 4 IDs at rest / 12 under activity |
| YAW bus | **pin 18 = CAN-H, pin 10 = CAN-L**, 500 kbps, 143 fps, 2 IDs |
| Power | 12V pin 1, GND pin 9, ignition pin 20. Assists on these alone |
| Termination | booster terminates neither bus; R120 ON at the adapter |

**Sensor initialises ~1.47 s after power-up.** Readings before that are invalid.

---

## Three things that cost real time — read before the next session

### 1. Contact at the pins, not the pinout

Six rounds of debugging — bitrate sweeps, polarity swaps, host power, ACK modes —
were **a bad connection at the booster end**. Nothing was wrong with the pinout,
bitrate, polarity, adapter, host, or unit.

**Verify continuity from the adapter's screw terminal through to the booster pin.**
A clip resting on an exposed pin looks connected and often is not.

### 2. Listen-only is unusable on a 2-node bus

Same booster, same 12 s window, mode the only difference:

| Mode | Total | Unique IDs |
|---|---|---|
| listen-only | 1006 fps | **1** |
| ACK | 37 fps | **4** |

No ACK means TEC climbs 8 per attempt → bus-off at 32 attempts (~32 ms) → automatic
recovery (~3 ms) → repeat. The 1006 fps is that cycle, not a signal — and it **hides
most of the IDs**. The adapter genuinely supports listen-only (feature bitmap
`0xF3`), so this is real behaviour, not a masked flag. **Always capture in ACK mode.**

### 3. A powered transceiver idles at 2.5V even when the ECU is dead

2.5V on a CAN pair proves the transceivers have power. It does **not** prove the ECU
is running. Don't lean on it as evidence the unit is alive.

---

## Reasoning errors made during this session

Kept deliberately — the pattern is that each one came from generalising past the
evidence actually in hand.

| Claim | Why it was wrong |
|---|---|
| "Zero frames rules out the ACK trap — you'd see the retransmissions" | The retry burst is milliseconds wide at power-up. A capture started later sees an already-bus-off node |
| "No `0x38E` on this unit, hypothesis killed" | Concluded from **one of two buses**. It was on the other pair, with the community's exact idle value |
| "`0x38E` `b3:b4` doesn't fit linearly in either endianness" | Averaged over windows spanning the boot transition, mixing pre- and post-init regimes |
| "`0x39D` is over 100x finer than `0x38E`" | Treated `b3` as the whole field. Real ratio 4.88x |
| "`0x33D` is likely the fault/status message" | It is a rare event message, all-`FF` 99.8% of the time |
| "10 mm reading 3048 vs 2441 predicted means non-linearity" | The 20-vs-21 mm inversion showed the *position measurement* was the inconsistency |

---

## Still open

1. **No periodic status or fault message has been found on either bus.** Everything
   decoded is position or events. The panel-B fault indicator in the Phase 7 plan
   assumes a signal that has not turned up — it may be in `0x32D`, in the burst
   group, or absent because the booster has nothing to complain about on a bench.
2. **`0x33D` payload** — needs a run with many deliberate brake applications varying
   force, depth and duration. Three samples is not enough.
3. **The `0x31D/34D/36D/37D/38D` burst group** — fires together within ~100 ms, at
   6.9 s in one run and 56.7 s in another. Event driven, trigger unknown.
4. **`0x38F`** (49.8 Hz, YAW) — `b2` and `b3` move; nothing decoded.
5. **Does it transmit on pins 1+9 without ignition?** Never measured — every
   successful capture had ignition live. Would let future bench work happen with the
   motor unable to move.
6. **Calibration to better than ~2 mm** would need a dial indicator on a fixed datum
   and a *single* run across the whole range. Not needed for display and logging.
