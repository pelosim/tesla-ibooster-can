# DECODE.md

Confirmed signal definitions for the Bosch iBooster **Gen1**, Tesla PN `1037123-00-B`
(fitment 2016-2020 Model S).

Everything here is **measured on this unit**, not inherited from community sources.
Anything unverified belongs in `VERIFY_FIRST.md`, not here.

---

## `0x39D` — brake pedal stroke — CONFIRMED 2026-08-06

500 kbps · DLC 4 · **25.0 Hz**

**Bus: pin 25 = CAN-H, pin 16 = CAN-L.** Confirmed by capture, not just by pairing —
this exact polarity produced clean frames, so H/L are assigned, not merely paired.
Under the community naming this is the **"Vehicle CAN"**, and it is consistent with
their claim that the vehicle bus carries brake input stroke.

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
  message with an *additive* checksum would settle it. **The YAW pair is not that
  second message** (2026-08-11): `0x38E`/`0x38F` use a CRC-8, not a sum, and share
  one parameter set between them rather than deriving anything from the ID. So the
  question stays open, and `0x39D` remains the only additive checksum on this unit.

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
| `b0` | **CRC-8 over `b1..b7`** | Not a data byte — see "Message integrity" below. CORRECTED 2026-08-11 |
| `b1` | alive counter | `0x20`..`0x2F` — low nibble counts, upper nibble fixed at 2 |
| `b2` | — | constant `00` |
| `b3` | position, **LOW byte** | `0x40` at settled rest; wraps, because it is not the whole field |
| `b4` | **low nibble** = position high bits · **high nibble** = STATUS | `0x11` at settled rest |
| `b5` | — | constant `00` |
| `b6` | **brake flag** | `0`/`1`. CORRECTED 2026-08-11 — was listed as constant |
| `b7` | — | constant `00` |

### position = 12-bit, and `b4`'s high nibble is STATUS — CORRECTED 2026-08-10

    position = b3 | ((b4 & 0x0F) << 8)     12-bit, rest 320, full travel ~3052
    status   = b4 >> 4                     0 = initialising, 1 = healthy, 2 = fault

`b3` alone wraps because it is the low byte. Visible directly in the boot trace:
across a fast push the low nibble climbs `1->2->...->B` and walks back down on
release, once per `b3` wrap.

**The high nibble was previously read as part of the position.** It is not. An
induced sensor fault moved it 1 -> 2 while `b3` did not change at all, shifting the
old 16-bit reading by exactly `0x1000`. During healthy operation it is pinned at 1,
so the two interpretations differ only by a constant — which is why the earlier
16-bit model fitted every healthy capture and still correlated at r=0.9999.

**Status 0 = initialising**, and the boot trace confirms the split independently.
`b4` reads `0x01` before the sensor comes up at ~1.47 s and `0x11` after — so the
12-bit position is **320 both sides of that transition** and only the nibble moves.
The old 16-bit reading called this "position jumps 320 -> 4416", which was never a
position change at all. Three states seen so far:

| `b4 >> 4` | Meaning |
|---|---|
| `0` | initialising — first ~1.47 s after power-up, position not yet valid |
| `1` | healthy, assisting |
| `2` | fault, latched — assist off until a power cycle |

**Validated against the calibrated `0x39D`** on two independent runs:

| Run | matched samples | fit | r |
|---|---|---|---|
| 1 | 15296 | `39D = 4.8797 * X - 21290.3` | **0.999627** |
| 2 | 12116 | `39D = 4.8736 * X - 21264.2` | **0.999853** |

The two runs agree to **0.13% on slope and 0.12% on intercept** — far tighter than
either agrees with the ruler, which independently confirms that the run-to-run
calibration conflict was measurement error and not the sensor.

    mm = 0.015207 * (b3 | ((b4 & 0x0F) << 8)) - 4.072

Sanity check: rest 320 -> 0.79 mm, and 3052 -> 42.34 mm. Both consistent with the
`0x39D` calibration.

⚠️ **The offset is negative.** Masking the status nibble subtracts a constant 4096
counts, so the 16-bit form's `- 66.36` becomes `0.015207 * 4096 - 66.36 = -4.072`.
This file briefly published `+ 1.94`, which is what a consumer of it then shipped:
the dashboard read **6.8 mm at rest** against `0x39D`'s 0.8 mm. The two sanity values
above are the check — any edit that does not reproduce 0.79 and 42.34 is wrong.

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

### `b6` — brake flag — CONFIRMED 2026-08-11

`b6` was recorded above as part of a constant `b5:b7` block. It is not constant: it
is a **1-bit brake-applied flag with real hysteresis**, and it was missed because
every earlier pass judged bytes by smoothness, which ranks a two-value flag as
noise.

| Edge | 12-bit position | mm | Runs |
|---|---|---|---|
| `0` → `1` | 411 – 427 | **2.18 – 2.42** | 4 |
| `1` → `0` | 381 – 383 | **1.72 – 1.75** | 4 |

**~0.55 mm of hysteresis**, and the off-threshold repeats to within 2 counts across
four independent power cycles. The spread on the on-threshold is run-to-run
variation in how fast the pedal was moved, not sensor noise.

This is the cleanest brake signal on either bus: one bit, at 99.7 Hz, in the same
message as the position and status it belongs with.

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
6.9 s in one run and 56.7 s in the other, always as a group within ~100 ms. **Trigger
found 2026-08-11: a brake release.** Those two timestamps were the first brake
application in each run. See "The post-brake burst".

## `0x38F` — YAW bus — MOSTLY DECODED 2026-08-11

500 kbps · DLC 8 · **49.8 Hz** · at rest `3F 2D E2 53 02 00 00 00`

The earlier note said "nothing moved at rest — needs a pedal sweep". The pedal sweeps
were already on disk; nobody had looked at this ID in them.

| Byte | Field | Notes |
|---|---|---|
| `b0` | **CRC-8 over `b1..b7`** | Same parameters as `0x38E`. Carries no data |
| `b1` | alive counter | `0x20`..`0x2F` |
| `b2` | **state byte** | bit 0 = brake, bits 5:3 = travel/health state. See below |
| `b3` | — | `0x53`/`0x55`. Moves, but not with anything — see below |
| `b4:b7` | — | constant `02 00 00 00` |

### `b2` — the state byte

Only six values were ever seen across four power cycles:

| `b2` | Meaning | When |
|---|---|---|
| `0x40` `0x42` `0x62` | booting | first ~2 s, in that order, one bit at a time |
| **`0xE2`** | ready, brake released | idle |
| **`0xE3`** | **brake applied** | bit 0 set |
| **`0xDB`** | **near end of travel** | bit 0 still set; bits 5:3 change together |
| `0xCC` | fault | from the induced-fault run, 2026-08-10 |

**`bit 0` is a second brake flag, and it trips *earlier* than `0x38E b6`:**

| Flag | on at | off at |
|---|---|---|
| `0x38F b2` bit 0 | **1.45 – 1.66 mm** | not resolved — see below |
| `0x38E b6` | 2.18 – 2.42 mm | 1.72 – 1.75 mm |

Two brake signals at two thresholds is the shape of the redundant switch pair an ESP
module expects. ⚠️ **`0x38F`'s release edge is rate-limited, not measured**: at 49.8 Hz
during a fast pedal return only one or two frames land in the transition, so the
observed off positions scatter from 1.45 to 4.11 mm. Do not quote a number for it.
`0x38E b6` at 99.7 Hz resolves its own release edge to 2 counts, which is why it is
the flag to use.

**`0xE3` → `0xDB` is a third threshold, near the end of travel:**

| Edge | mm | Runs |
|---|---|---|
| `0xE3` → `0xDB` | **39.75 – 40.16** | 4 |
| `0xDB` → `0xE3` | 38.77 – 39.51 | 4 |

The end stop is 43.4 mm, so this flags roughly the last 3.5 mm. Whether it means
"end of travel", "maximum assist" or something else cannot be told apart on a bench
with no hydraulics — all three coincide here.

Read `bits 5:3` as the field: `110` ready · `011` near end of travel · `001` fault ·
`000`/`100` booting. Bits 3 and 4 always move together and bit 5 opposes them, which
is why they read as one field rather than three flags.

### `b3` is not a signal

`b3` takes `0x53` and `0x55` and changes often, but it correlates with **nothing** —
r = 0.009 against position, 0.000 against pedal velocity. It is not a position, not a
brake state, and not a counter (it does not increment). Left undecoded deliberately:
a byte that moves is not automatically a measurement.

---

## Message integrity — CONFIRMED 2026-08-11

Two different schemes, one per bus, and the difference matters to a consumer.

| Bus | ID | Scheme |
|---|---|---|
| Vehicle | `0x39D` | additive — `(b1+b2+b3+0xA0) & 0xFF` |
| YAW | `0x38E`, `0x38F` | **CRC-8/SAE-J1850** over `b1..b7` |
| Vehicle | everything else | **none** |

    poly 0x1D · init 0x00 · xorout 0x0A · no reflection, in or out

**Validates on 100% of 46,960 `0x38E` frames and 23,478 `0x38F` frames** across four
power cycles — 70,438 frames, zero failures. Both IDs use the same parameters, so the
CRC is *not* seeded from the message ID.

Two consequences worth keeping:

1. **`0x38E b0` and `0x38F b0` contain no data.** They looked random and scored as
   "active" on every ranking pass. They are a checksum, and the question of whether
   something was hiding in them is closed.
2. **The burst IDs have no checksum at all**, which is exactly why their `b0` is free
   to carry a payload — and it does, in several of them.

---

## Fault signalling — CONFIRMED 2026-08-10 by induced fault

Provoked by **disconnecting the travel sensor** with the booster running. Assist
drops and all three of these change within ~10 ms of each other:

| Signal | Healthy | Fault |
|---|---|---|
| **`0x38E` `b4 >> 4`** | `1` | **`2`** |
| `0x39D` stroke (`b2:b3`) | live, 264..13606 | **pinned to 16354 (`0x3FE2`)** — one single value |
| `0x38F` `b2` | `0xE2` | `0xCC` |

**`0x39D`'s fault value carries a valid checksum**, so this is deliberate sentinel
signalling, not corruption. `16354` is also unreachable physically — the end stop is
13606 — so a consumer can reject it on range alone without knowing the sentinel.

### There is no status *message*

This is why one was never found: **status is a field inside the position messages**,
not a message of its own. Anything waiting for a dedicated fault frame will wait
forever.

### Use `0x38E b4 >> 4`

It is the cleanest of the three — a two-value enum at 99.7 Hz, in the same byte as
the position it qualifies, so a reading and its validity can never be split across
frames. Belt-and-braces: also reject `0x39D` stroke > 13700.

### It LATCHES — and assist stays off until a power cycle — CONFIRMED

Sequence, confirmed on the bench:

| Step | Status nibble | `0x38E` position | `0x39D` stroke | Assist |
|---|---|---|---|---|
| healthy | `1` | live | live | **on** |
| sensor disconnected | `2` | — | pinned 16354 | **off** |
| **sensor reconnected** | **still `2`** | **live again** (320 -> 401) | **still pinned** | **still off** |
| power cycled | `1` | live | live | **on** |

**Reconnecting the sensor does not clear the fault.** The booster latches into
no-assist and only a power cycle restores it.

### The two buses disagree after a reconnect

Worth knowing before choosing a source. Once the sensor is restored but the fault is
still latched, `0x38E` reports **real position again** while `0x39D` stays **pinned
at the sentinel**. So during a latched fault, `0x38E` is the only source of live
position.

### `status == 2` means "assist unavailable", not "position invalid"

The reconnect step proves these are different things: position was valid and updating
while status stayed `2` and assist stayed off. **Do not treat the status nibble as a
data-validity flag** — it is an assist-availability flag. Judge position validity
separately, on range.

### ⚠️ Implication for the car

A **momentary** sensor-connector interruption — vibration, corrosion, a marginal
crimp — latches the booster into **no assist until the ignition is cycled**. The
pedal becomes very hard, and stays that way, with nothing on a stock dash to explain
why. In a 40-year-old car with a retrofit harness this is a realistic failure mode,
not a theoretical one.

Two consequences: the travel-sensor connector deserves better strain relief and
weatherproofing than convenience suggests, and the panel-B indicator is the only
thing that would tell the driver what happened — which makes it a real safety
affordance rather than a nice-to-have. Brakes still work unassisted; they just need
far more pedal effort.

---

## Other IDs seen — NOT yet decoded

**Vehicle bus (25/16).** At rest with ignition on, four IDs. Under pedal activity,
**eleven**.

| ID | rate | at-rest bytes | note |
|---|---|---|---|
| `0x39D` | 25.0 Hz | `B5 0C 08 01` | decoded above |
| `0x33D` | 9.5 Hz | `00 00 FF FF FF FF FF FF` | **event message** — see below |
| `0x35D` | 1.0 Hz | `05 55 55 55 55 55 55 55` | `0x55` fill — placeholder. `b0` counts `00`..`07` at boot then sticks |
| `0x32D` | 0.5 Hz | `0D 00 00 00 8D 79 20 21` | **static identity, multiplexed** — decoded below 2026-08-11 |
| `0x3AD` | 0.2 Hz | — | `b0:b1` = uptime counter, below |
| `0x31D` `0x34D` `0x36D` `0x37D` `0x38D` | event | — | **the post-brake burst** — trigger found 2026-08-11, below |
| `0x5BD` | one-shot | `CF 40 01 00 00 00 00 00` | seen once |

⚠️ `0x33D`'s bytes rank as "smooth" in `analyze.py` but are a **false positive**: they
sit at `FF` and jump rarely, so mean delta stays low. Judge by the plotted shape, not
the smoothness number alone.

---

## `0x33D` — post-brake event message — BEHAVIOUR CONFIRMED 2026-08-06

Transmits at 9.5 Hz but is **all-`FF` 99.8% of the time**. In a 150 s run it carried a
real payload **3 times, one frame each**:

    t= 6.93s   04 00 0A 00 53 53 55 55
    t=25.24s   16 00 00 00 55 52 57 53
    t=35.76s   16 00 00 00 58 53 5A 55

**Trigger: ~0.8 s after a brake release.** Two pedal applications in the run, two
events, at +0.82 s and +0.84 s after release. The third fired at rest shortly after
boot, coincident with the `0x31D/34D/36D/37D/38D` burst group.

**Earlier guess corrected.** This was called "likely the fault/status message, the
signal your gauge panel actually wants". It is not periodic status — it is a rare
event, and a display polling it would see `FF` essentially always. If a status signal
exists it is elsewhere.

**Not decodable from 3 samples.** `b0` takes `04`/`16`/`16`, `b1` is always `00`,
`b2:b3` is small (`0A 00`, `0000`, `0000`), and `b4..b7` cluster tightly in
`0x52..0x5A`. Decoding this needs a run with many deliberate, varied brake
applications — vary force, depth and duration and see which field follows what.

### It is not alone — it is part of a burst — 2026-08-11

Pooling all six logs gives 10 payload-carrying `0x33D` frames instead of 3, and every
one of them arrives **inside the `0x31D/34D/36D/37D/38D` burst**, within ~120 ms.
`0x33D` is not a separate message with its own trigger; it is one member of the group
described in the next section, and its `b4:b7` cluster is analysed there.

---

## The post-brake burst — TRIGGER CONFIRMED 2026-08-11

`0x33D` `0x31D` `0x34D` `0x36D` `0x37D` `0x38D` transmit **one frame each, together,
inside ~120 ms**. The earlier entry called this group "event driven, trigger unknown",
having seen it at 6.9 s in one run and 56.7 s in another.

**The trigger is a brake release.** Across all six logs: 10 bursts, 10 preceding brake
applications, lag **0.6 – 2.2 s** after release. No burst occurs without one, and no
application over ~1.5 mm fails to produce one. The two timestamps that looked
arbitrary were simply the first brake application in each run.

That pairs each burst with an application whose peak, duration and shape are known
independently from `0x39D`, which is what makes the payload decodable at all.

### What decodes

| Field | Is | Scale | r |
|---|---|---|---|
| `0x38D b5:b6` uint16 LE | **peak rod travel of that application** | 129.8 counts/mm | **0.9997** |
| `0x37D b0:b1` uint16 LE | **how long the brake was applied** | 27.5 ticks/s | **0.9988** |
| `0x31D b2 >> 4` | the same duration, log-bucketed | 1..7, ~one step per doubling | 0.884 |
| `0x31D b0:b1`, `0x3AD b0:b1` | **uptime**, not event data | 9.99 ticks/s (100 ms) | — |

`0x38D b5:b6` tracks the calibrated stroke to within **±0.8 mm** over a 33 mm range —
tighter than the ±2 mm the ruler calibration itself is good to. Four separate
end-stop hits across three power cycles land within 8 counts of each other.

`0x37D b0:b1`'s **27.5 ticks/s is not a round number**, and that is the open part.
Either the tick is ~36 ms, or the booster starts and stops its timer at a threshold
slightly different from the 600-count threshold used to measure the applications.
Refitting against thresholds from 400 to 1000 counts moves the slope by less than
0.2%, so the booster's threshold is low — but that does not pin the tick.

**A logarithmic bucket is a diagnostic shape, not a control shape.** Taken with the
fact that the whole burst fires *after* the event is over, the sensible reading of
this group is **event-memory / statistics**, not a signal anything downstream is meant
to act on. Nothing in it is useful for live display.

### What does not decode, and why

⚠️ **`0x33D b4:b7`** — four bytes that always sit within a few counts of each other in
the range 76..90, all four drifting up with peak travel (r = 0.53 to 0.92) but far too
compressed to be a position. Four near-identical channels of one quantity is the shape
of a redundant sensor set or repeated supply samples. **Unresolved.**

⚠️ **`0x37D b5` and `0x34D b5` are confounded with uptime and must not be quoted.**
`0x37D b5` takes `0x58` on deep applications and `0x5C` on shallow ones (r = -0.90
with peak) — but every shallow application in the set also came late in the longest
run, and it correlates r = +0.82 with uptime. Peak and uptime split these ten events
identically, so the data cannot say which one drives it. Same for `0x34D b5`, which
steps `0x26` → `0x28` → `0x2A` monotonically with uptime (r = 0.88) and looks like a
slowly warming temperature — a 20-minute soak with **no pedal input** separates the
two completely, and nothing short of that will.

`0x31D b6` (r = -0.93 with peak, only 0.60 with uptime) is more likely real: it reads
`0` at full travel, `1` mid, `2` shallow — an inverse peak bucket. Still a lead.

### ⚠️ Ten events is not many

Every number in this section rests on **n = 10**, with far more candidate bytes than
events. The two 0.999 fits survive a 20,000-iteration permutation test and are safe.
Below |r| ≈ 0.9, treat anything here as a lead. Peak and duration are also partly
confounded in this set, because a deep application was usually also a long one —
these were calibration sweeps, not a designed experiment. **20–30 short applications
with depth, speed and hold time varied independently** would settle most of what is
left open above.

---

## `0x32D` — static identity — CONFIRMED 2026-08-11

500 kbps · DLC 8 · 0.5 Hz · **multiplexed on `b0`**

Five frames rotate on a 2-second cycle, selected by `b0`:

| mux `b0` | `b1..b7` |
|---|---|
| `0x0A` | `01 00 00 00 00 70 00` |
| `0x0B` | `00 02 01 01 00 00 00` |
| `0x0D` | `00 00 00 8D 79 20 21` |
| `0x14` | `05 00 00 60 FC B0 70` |
| `0x16` | `00 00 00 E4 AC A3 2F` |

**Byte-for-byte identical across all four independent power cycles**, and nothing in
it responds to the pedal. This is a part number, calibration ID or similar. Settled:
it was previously listed as "structured; identity or config?".

A monitor can read it once at boot and ignore the message afterwards. It is also the
only candidate left for a stored unit identity, which makes it worth logging once per
boot even though it never changes.

---

## `0x31D` / `0x3AD` `b0:b1` — uptime, and a correlation trap

A 16-bit little-endian counter at **9.99 ticks/s** — a 100 ms tick — running from
booster power-on. Both IDs carry the same counter, offset only by their position
within the burst. Confirmed across four runs including one where the capture started
long after the booster was powered (the counter was already at 442).

**It is the reason this section exists rather than a list of findings.** Later events
in a run had longer and deeper pedal applications than earlier ones, so an uptime
counter correlates with peak, duration and work done well enough to impersonate a
measurement. Any future analysis of this burst should carry uptime as a control
column and discount anything that tracks it as closely as it tracks the brake event.
