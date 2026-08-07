# ibooster

Read-only CAN reverse-engineering of a **Tesla Model S/X Bosch iBooster**
(PN `1037123-00-B`, 2020 Model S LR) for the 1987 Porsche 944S restomod.

The 944 uses the iBooster as a self-contained brake booster. This project only
**listens** — the goal is brake pedal position and booster status on the car's
private CAN bus, nothing more.

## Read these in order

1. **[VERIFY_FIRST.md](VERIFY_FIRST.md)** — every pin number and CAN ID here is a
   hypothesis from community work on *other* iBooster variants. Nothing has been
   measured on this unit yet.
2. **[BENCH_PLAN.md](BENCH_PLAN.md)** — Phase 0 → 7, with exit criteria.
3. **[docs/PINOUT.md](docs/PINOUT.md)** — hypothesis table + bench wiring.
4. **[CLAUDE.md](CLAUDE.md)** — conventions, toolchain, the rules that matter.

## The firmware cannot transmit

`ibooster_sniffer` has no transmit path. `twai_transmit()` is never called, the
TWAI TX queue is length 0, and the slcan `t`/`T`/`r`/`R` commands answer BEL and
count as refusals. The device under test is a brake actuator; keep it that way.

Link-layer **ACK** is a different thing and is required — see below.

## Quick start

Build (isolated v3 toolchain, esp32 core 3.3.10):

```bash
export ARDUINO_DIRECTORIES_DATA=~/.arduino-cli-esp32v3/data \
       ARDUINO_DIRECTORIES_USER=~/.arduino-cli-esp32v3/user \
       ARDUINO_DIRECTORIES_DOWNLOADS=~/.arduino-cli-esp32v3/downloads
arduino-cli compile --warnings all \
  --fqbn esp32:esp32:esp32s3:USBMode=hwcdc,CDCOnBoot=cdc,FlashSize=16M,PSRAM=opi \
  ibooster_sniffer
```

Then open a terminal on the board and send `h` for human-readable mode, `?` for help.

## The ACK trap — the thing that will waste your afternoon

A CAN node whose frames are never ACKed retransmits forever, climbs its TX error
counter, goes error-passive, then bus-off. On a 2-node bus a listen-only sniffer
never ACKs, so **the iBooster talks once and then goes quiet — which looks exactly
like dead hardware.**

| Cmd | Mode | Use it for |
|---|---|---|
| `L` | LISTEN_ONLY — fully passive, no ACK | Confirming the bitrate, once |
| `O` | NORMAL — ACKs, sends no application frames | Every real capture |

Open `L` first. A sniffer at the wrong bitrate in NORMAL mode emits error frames
and does genuinely disturb the bus.

This applies **in the car too**. The 944 is pre-CAN, so the booster and the
monitoring ESP32 are the only two nodes — the ESP32 must stay in ACK mode
permanently, and 120R is required at both ends.

## Serial commands

```
S6      500 kbps (only rate accepted)   O   open NORMAL (ACK, no app TX)
C       close                           L   open LISTEN-ONLY (fully passive)
Z0/Z1   timestamps off/on               F   status flags
V v N   version / hw / serial           h   toggle HUMAN mode
?       help                            t T r R   REFUSED — no transmit path
```

HUMAN mode prints a bus-health line every second even when no frames arrive, so
bus-off and error-passive are visible instead of looking like silence. It is not
valid slcan — turn it off before attaching a host tool.

## Host tools

The sniffer speaks slcan, so it drops straight into:

```bash
# canclaude (python-can, bustype='slcan')
./.venv/bin/python canclaude.py capture --interface slcan --channel /dev/ibooster
```

...as well as can-utils (`slcand`/`candump`) and SavvyCAN for frame diffing and
graphing a candidate signal against a pedal-position log.

This also closes the long-open "ESP32 slcan firmware" TODO in the canclaude project.

## Status

Firmware v1.0.0 compiles clean (323426 bytes flash, 22716 bytes RAM, zero warnings).
**Not yet run against hardware** — the booster and the 26-pin connector are still
inbound. Phase 0 begins when the unit lands.
