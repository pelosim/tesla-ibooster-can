# CLAUDE.md — ibooster

## Why
Reverse-engineer the CAN output of a **Tesla Model S/X Bosch iBooster**
(PN `1037123-00-B`, off a 2020 Model S LR) so the 1987 Porsche 944S restomod can
read brake pedal position and booster status. Same car as the HVAC, lighting,
gauge, ignition-display and iDrive projects.

**Scope is read-only, permanently.** The goal is to *monitor* the booster, not
command it. The 944 uses the iBooster as a self-contained brake booster; the
ESP32 only listens.

## The one rule
**No firmware in this repo transmits an application CAN frame to the iBooster.**
`ibooster_sniffer` has no transmit path: `twai_transmit()` is never called, the
TWAI TX queue is length 0, and the slcan `t`/`T`/`r`/`R` commands answer BEL and
increment a refusal counter. Do not add a transmit path to this sketch. If
commanding the booster ever becomes a goal, that is a separate, differently
named sketch with its own interlocks — and a separate conversation about whether
it belongs anywhere near a road car.

Link-layer **ACK is not a command** and is required — see below.

## Key design decision: display and logging only
**Nothing actuates on this data.** Decided 2026-08-06. Brake lights stay on the
mechanical pedal switch — they are not driven from decoded pedal position.

This is what makes the rest of the architecture safe to keep simple. Because no
output depends on a frame arriving, best-effort transport is fine everywhere: a
dropped ESP-NOW packet costs a stale pixel, not a dark brake light.

If that ever changes, the topology below is **not** adequate and must be redesigned
— an actuating path would have to be a direct wired output from the sniffer ESP32,
never via ESP-NOW or the Pi, with the mechanical switch left in place as a parallel
hardware fallback. Do not incrementally grow into that.

## Data topology

Settled: **the Pi is the primary sink** — it is already the state hub for this car,
and logging is what actually pays off. The useful question in service is "what did
the booster report just before that pedal felt wrong", not "what is it doing this
instant". The display leg is secondary.

The *transport* is an open decision, deferred to Phase 7 and gated on the frame rate
measured in Phase 3:

    A  iBooster ──CAN── CANable ──USB── Pi ──existing USB link── panel B
    B  iBooster ──CAN── ESP32 ──USB CDC── Pi
                           └──ESP-NOW── panel B

**A** deletes a board and an ESP-NOW hop and gets SocketCAN's tooling. **B** keeps an
isolated MCU that boots in under a second and filters a firehose down to two signals,
which matters if the booster turns out to be chatty — the Pi already carries HVAC,
iDrive, lighting, dashboard and kiosk. Do not pick until Phase 3 has a number.

ESP-NOW is a different radio from CAN and does not touch the read-only story.

**Display content:** the booster's fault/status state is what earns permanent
screen space, as an indicator rather than a needle. Live stroke is a bench and
datalog-replay signal — the driver is pressing the pedal and already knows where
it is. Panel B is a 180x640 strip already carrying AFR and BATTERY, so space, not
bandwidth, is the binding constraint.

## Two sketches, kept separate
| Sketch | Role |
|---|---|
| `ibooster_sniffer` | Bench. Dumb auditable pipe, slcan, no decode, no transmit path |
| `ibooster_monitor` | Car. Decodes confirmed signals, publishes to Pi + panel B. **Not yet written** |

Same split as `ir_capture` vs `idrive_controller`. Do not merge them — the bench
sketch's value is that it is small enough to audit at a glance.

`ibooster_monitor` cannot be written until Phase 6 confirms actual signal
locations. Anything earlier would be encoding guesses.

## What
| Path | Contents |
|---|---|
| `ibooster_sniffer/` | Read-only slcan sniffer, ESP32-S3 + SN65HVD230 |
| `BENCH_PLAN.md` | Phased bench procedure, Phase 0 → 7 |
| `VERIFY_FIRST.md` | Gate list — unverified hardware facts, and how to settle each |
| `docs/PINOUT.md` | Community pinout **hypotheses** with confidence + test method |
| `tools/99-ibooster.rules` | udev rule pinning the sniffer to `/dev/ibooster` |
| `logs/` | Captures (gitignored) |

## Hardware
| Part | Detail |
|---|---|
| DUT | Bosch iBooster Gen2 family, Tesla PN `1037123-00-B` (2020 Model S LR) |
| Bench interface | **CANable clone (Jhoinrch RH02) USB-CAN dongle** — owned, primary |
| Fallback interface | ESP32-S3 + **SN65HVD230** (3.3V native) running `ibooster_sniffer` |
| Bus | 500 kbps, two independent buses, **no internal termination** |

**The MCP2551 in the parts drawer is unusable with an ESP32-S3** — and the reason is
worth keeping, because "it mostly works" is the trap. It is 5V-only: RXD swings to
5V into a GPIO whose absolute max is ~3.6V (the S3 is not 5V tolerant), and TXD's
high threshold is 0.7 × VDD = 3.5V, above the 3.3V the S3 drives. A marginal TXD
read as dominant **jams the bus** — active failure, not passive, and
temperature-dependent, so it passes on the bench and misbehaves hot. SN65HVD230 or
TJA1051T/3 (VIO pin) only.

Pins: CTX=GPIO4, CRX=GPIO8, NeoPixel=GPIO48 — identical to idrive-controller,
so the same bench board and transceiver wiring drops straight in.

**Use a spare board, not `/dev/idrive`.** `D0:CF:13:24:DB:B8` is the in-car iDrive
board — its 20 ms keep-alive is load-bearing and it is doing a job in the car. This
project needs its own ESP32-S3 + SN65HVD230; record its MAC in
`tools/99-ibooster.rules` once you pick one.

## Constraint: one bus at a time
The ESP32-S3 has a **single TWAI controller**. Vehicle CAN and YAW CAN cannot be
captured simultaneously on one board. Either run the two buses sequentially
against the same repeatable pedal sweep, or build a second sniffer and let the Pi
timestamp both USB streams (ms resolution is ample here).

## Termination
The iBooster terminates neither bus. On the bench — and in the 944, where the
sniffer is the only other node — **120R is required at both ends**: one on the
transceiver breakout (the blue SN65HVD230 boards have one), one across H/L at the
booster connector. Unpowered, H-to-L reads ~60R.

Same 2-node rule as idrive-controller. Opposite of the canclaude rule about never
terminating when tapping a live vehicle bus.

## The ACK trap
A CAN node whose frames are never ACKed retransmits forever, climbs its TX error
counter, goes error-passive, then bus-off. On a 2-node bus a listen-only sniffer
never ACKs, so **the iBooster talks once and then goes silent — which reads
exactly like dead hardware.**

- `L` opens LISTEN_ONLY — fully passive. Use it once, to confirm the bitrate.
- `O` opens NORMAL — ACKs, sends no application frames. Use it for real captures.

Open `L` first: a sniffer at the wrong bitrate in NORMAL mode emits error frames
and does genuinely disturb the bus.

This applies to the **final in-car install too**, not just the bench. The 944 has
no other CAN node, so the monitoring ESP32 must stay in ACK mode permanently.

## Build / verify
Isolated v3 toolchain (esp32 core **3.3.10**), same as idrive-controller:

    export ARDUINO_DIRECTORIES_DATA=~/.arduino-cli-esp32v3/data \
           ARDUINO_DIRECTORIES_USER=~/.arduino-cli-esp32v3/user \
           ARDUINO_DIRECTORIES_DOWNLOADS=~/.arduino-cli-esp32v3/downloads
    arduino-cli compile --warnings all \
      --fqbn esp32:esp32:esp32s3:USBMode=hwcdc,CDCOnBoot=cdc,FlashSize=16M,PSRAM=opi \
      ibooster_sniffer

Baseline v1.0.0: **323426 bytes flash (24%), 22716 bytes RAM (6%), zero warnings.**

Do not build this with the v2 toolchain (`~/.arduino-cli-esp32v2`, core 2.0.14) —
that one belongs to the gauges and the lighting board. `rgbLedWrite()` is a
core 3.x name.

## Host side
The sniffer speaks slcan, so it works directly with:

    python-can    bustype='slcan'          (canclaude capture)
    can-utils     slcand / candump
    SavvyCAN      frame diffing + graphing a candidate signal

This closes the "ESP32 slcan firmware" TODO that has been open in the canclaude
project's CLAUDE.md.

## Gotcha: USB CDC blocks when nothing is listening
`Serial.setTxTimeoutMs(0)` in `setup()` is load-bearing — do not drop it.
Hardware USB CDC blocks on write when no host drains the FIFO, stalling `loop()`
for ~2 s. On a sniffer that prints every frame, that is fatal and looks like
flaky hardware. See the esp32s3-usb-cdc-write-stall note.

## Conventions
- **Full deployable `.ino` files, never diffs or snippets** — Mark flashes whole files.
- **Unverified hardware facts get gated, not guessed.** Every pin number in
  `docs/PINOUT.md` carries a confidence level and a way to settle it. Nothing
  moves out of `VERIFY_FIRST.md` until it has been measured on this actual unit.
- Nothing blocking in `loop()`.
- Git is local-only unless Mark asks to publish; if published, private by default.
