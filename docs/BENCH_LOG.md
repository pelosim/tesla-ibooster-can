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

## 2026-08-11 — Hotplug: a replugged adapter came back dead

Pulling a CANable's USB and putting it back left that bus dead until someone
intervened. udev renamed the interface correctly; nothing brought it **up**. It
returned DOWN, state STOPPED, no bitrate — and `ibooster-can.service` is
`Type=oneshot RemainAfterExit=yes`, so systemd considers it active forever and
never re-runs it.

**The fix that did not work, and the test that lied.** Setting
`ENV{SYSTEMD_WANTS}` on the `ACTION=="add"` rule looked right, and
`udevadm trigger --action=add` confirmed it. That confirmation was worthless:
`udevadm trigger` synthesises an event on a device that **already exists under its
final name**, which is not what a replug does.

Renaming a network interface emits **`add` under the OLD name, then `move` under
the NEW one**. A `SYSTEMD_WANTS` on the add rule attaches to the pre-rename device
and never reaches the `can-veh` device unit. Binding it to the **move** event is
what works.

**Test hotplug by unbinding and rebinding the real USB device**, not by reloading
the module and not with `udevadm trigger`:

    echo 1-1.3.1:1.0 | sudo tee /sys/bus/usb/drivers/gs_usb/unbind
    sleep 4
    echo 1-1.3.1:1.0 | sudo tee /sys/bus/usb/drivers/gs_usb/bind

Reloading `gs_usb` is also not faithful — remove and reinsert inside a couple of
seconds and systemd's device units never go inactive, so the `Wants` is never
re-evaluated.

Verified end to end: adapter removed, reinserted, interface back UP at 500 kbps
with frames flowing, and the backend's reader thread recovered on its own retry
loop with no restart.

---

## 2026-08-11 — Second pass over the existing logs: no new captures needed

No hardware was touched. This session re-read the six committed logs — 91,439 frames,
14 IDs, four power cycles — asking what everything *other* than rod position does.
Four of the six items on the old "still open" list closed without a bench session.

**The headline answer to "where are the assist numbers":** there aren't any, live.
Every field that moves while the pedal moves is position or a threshold flag derived
from position — that is now a measured result across all 14 IDs, not an absence of
looking. What the booster does emit is a **summary of each brake application, about a
second after it ends**, and two fields of it decode outright:

| Field | Is | r |
|---|---|---|
| `0x38D b5:b6` | peak rod travel of that application, 129.8 counts/mm | **0.9997** |
| `0x37D b0:b1` | how long the brake was held, 27.5 ticks/s | **0.9988** |

`0x38D b5:b6` agrees with the calibrated `0x39D` stroke to ±0.8 mm — tighter than the
±2 mm the ruler calibration is itself good to.

### What made the burst decodable was finding its trigger

The `0x31D/34D/36D/37D/38D` group was logged as "event driven, trigger unknown", seen
at 6.9 s in one run and 56.7 s in another. Pooling all six logs: **10 bursts, 10
preceding brake applications, lag 0.6–2.2 s after release, no exceptions.** Those two
timestamps were just the first brake application in each run. Pairing each burst with
an application whose peak and duration are known from `0x39D` is what turned a wall of
hex into a fit.

`0x33D` turns out not to be a separate message either — every payload-carrying `0x33D`
frame lands inside that same burst.

### Three things that were recorded as constant or unknown, and are not

- **`0x38E b6` is a brake flag** — on at 2.18–2.42 mm, off at 1.72–1.75 mm, ~0.55 mm
  hysteresis, repeating to 2 counts across four power cycles. It sat inside a byte
  range documented as "constant `00`".
- **`0x38F b2` is a state byte** with a *second* brake bit at a lower threshold
  (1.45–1.66 mm) and a third state at ~40 mm, near the end of travel. The old entry
  said "nothing moved at rest — needs a pedal sweep"; the pedal sweeps were already
  on disk.
- **`0x32D` is static identity data**, multiplexed on `b0`, byte-identical across all
  four power cycles.

**`0x38E`/`0x38F` byte 0 is CRC-8/SAE-J1850** (poly `0x1D`, init `0x00`, xorout `0x0A`,
over `b1..b7`) — 100% of 70,438 frames, same parameters for both IDs. That closes the
question of whether anything was hiding in a byte that looked random. Nothing was.

### The trap this session had to work around

**`0x31D`/`0x3AD b0:b1` is an uptime counter at 9.99 ticks/s**, and it fakes
correlations with everything. Later events in a run had longer, deeper applications
than earlier ones, so uptime tracks peak, duration and work done well enough to
impersonate a measurement. It is excluded from the analysis and carried as a control
column instead.

Two candidate findings failed that control and are **not** claimed: `0x37D b5`
(r = -0.90 with peak, but +0.82 with uptime) and `0x34D b5` (r = 0.88 with uptime,
stepping `0x26`→`0x28`→`0x2A` like a warming temperature). Peak and uptime split
these ten events identically. A 20-minute soak with no pedal input separates them;
nothing in the existing logs does.

### Method note

Every number here rests on **n = 10** events with far more candidate bytes than
events. The two 0.999 fits survive a 20,000-iteration permutation test. Below
|r| ≈ 0.9 nothing is claimed. Peak and duration are also partly confounded, because a
deep application was usually a long one — these were calibration sweeps, not a
designed experiment.

Plotted output: `report/correlations.html`.

---

## Reasoning errors made in the 2026-08-11 pass

| Claim | Why it was wrong |
|---|---|
| "`0x33D` `b0` is a checksum — a sum over `b1..b7` validates on 99.87% of frames" | The at-rest payload is constant, and it is 99.8% of all `0x33D` frames. Any constant passes. Checked against the ~10 frames that actually carry a payload, it fails every one. **A checksum hypothesis is only tested by the frames that vary** |
| "`0x37D b5` splits deep from shallow applications" | True and useless — every shallow application in the set also came late in the longest run. Adding an uptime control column is what caught it |
| "`0x38F b3` moves, so it is a signal" | It moves and correlates with nothing (r = 0.009 against position). A byte that changes is not automatically a measurement |

---

## Still open

1. ~~**No periodic status or fault message.**~~ **Closed** — resolved 2026-08-10:
   status is a *field* inside the position messages (`0x38E b4>>4`), not a message of
   its own, which is why looking for a message never found one. The 2026-08-11 pass
   adds two brake flags and a near-end-of-travel state to what the panel-B indicator
   can draw on.
2. ~~**`0x33D` payload**~~ — **partly closed.** It is one member of the post-brake
   burst, not a message with its own trigger. Its `b4:b7` quad is still undecoded.
3. ~~**The `0x31D/34D/36D/37D/38D` burst group**~~ — **closed.** Trigger is a brake
   release; two fields decoded. See `docs/DECODE.md`.
4. ~~**`0x38F`**~~ — **closed.** `b0` CRC, `b1` counter, `b2` state byte with a brake
   bit and a travel state. `b3` moves but correlates with nothing.
5. **Does it transmit on pins 1+9 without ignition?** Never measured — every
   successful capture had ignition live. Would let future bench work happen with the
   motor unable to move.
6. **Calibration to better than ~2 mm** would need a dial indicator on a fixed datum
   and a *single* run across the whole range. Not needed for display and logging.
7. **`0x33D b4:b7`** — four tightly-clustered channels, 76..90, tracking peak travel
   on a compressed scale. Redundant sensor channels or sampled supply readings; a
   bench-supply sweep from 11 V to 14 V while braking identically separates them.
8. **`0x37D b0:b1`'s tick is not a round number** (27.5/s). Either a ~36 ms tick, or
   the booster's own start/stop threshold differs from the one used to measure.
9. **Is `0x34D b5` a temperature?** Needs a 20-minute powered soak with **no pedal
   input** — uptime and cumulative braking are confounded in every log on disk.
10. **A designed brake-event run** — 20–30 short applications varying depth, speed and
    hold time independently. This is the single capture that would close the most:
    items 7, 8 and most of what is marked "lead" in the burst section.
