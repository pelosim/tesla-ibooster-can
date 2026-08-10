# Tesla iBooster — read-only CAN reverse engineering

Decoding the CAN output of a **Bosch iBooster Gen1** — Tesla PN **`1037123-00-B`**,
listing fitment **2016–2020 Model S** — so a 1987 Porsche 944S restomod can read
brake pedal position. **Nothing in this repo ever transmits to the booster.**

Bench bring-up completed 2026-08-06. Everything below is measured on this unit, not
inherited from other iBooster variants.

---

## Headline results

**It assists standalone.** 12 V, ground and ignition, with nothing ever transmitted
to it — no vehicle CAN, no wake frame, no keep-alive. A purely passive monitor is
viable, so commanding a brake actuator never has to enter the picture.

**Both CAN buses found and decoded:**

| Bus | Pins | Rate | Carries |
|---|---|---|---|
| Vehicle | **25 = CAN-H, 16 = CAN-L** | 500 kbps, 36 fps | `0x39D` — 16-bit stroke |
| YAW | **18 = CAN-H, 10 = CAN-L** | 500 kbps, 143 fps | `0x38E` @ 99.7 Hz, `0x38F` @ 49.8 Hz |

Power: **pin 1** = 12 V, **pin 9** = GND, **pin 20** = ignition. Neither bus is
internally terminated.

### `0x39D` — stroke, vehicle bus, 25 Hz, DLC 4

```
b0    = checksum, (b1 + b2 + b3 + 0xA0) & 0xFF   ← holds on 100% of 2250 frames
b1    = alive counter, +1 mod 16
b2:b3 = stroke, uint16 LITTLE-endian

mm = (counts − 3.3) / 320.68        rest ≈ 264 · end stop 13606 = 43.4 mm
```

### `0x38E` — position + status, YAW bus, 99.7 Hz, DLC 8

```
b1       = alive counter, 0x20..0x2F (low nibble counts)
position = b3 | ((b4 & 0x0F) << 8)     12-bit, rest 320, full ~3052
status   = b4 >> 4                     1 = healthy, 2 = fault
```

`b3` alone **wraps** — it is the low byte, not the whole field. Correlates with
`0x39D` at **r = 0.9999** over 15,296 matched samples.

### Fault signalling

Confirmed by disconnecting the travel sensor:

| Signal | Healthy | Fault |
|---|---|---|
| `0x38E` `b4 >> 4` | `1` | **`2`** |
| `0x39D` stroke | live | **pinned to 16354**, checksum still valid |
| `0x38F` `b2` | `0xE2` | `0xCC` |

**There is no status *message*** — status is a field inside the position messages.
That is why looking for a dedicated fault frame found nothing. Use `0x38E b4 >> 4`:
a two-value enum at 99.7 Hz, in the same byte as the position it qualifies.

**The fault latches.** Reconnecting the sensor does *not* clear it — the booster
stays in no-assist until a power cycle. And `status == 2` means **assist
unavailable**, not *position invalid*: after a reconnect, `0x38E` reports live
position again while status stays `2` and assist stays off. `0x39D`, meanwhile, stays
pinned at its sentinel, so `0x38E` is the only live position source during a latched
fault.

⚠️ **In a car this matters.** A momentary sensor-connector interruption latches the
booster into no assist until the ignition is cycled — the pedal goes hard and stays
hard. Brakes still work, they just need far more effort. Strain-relieve that
connector properly.

Full signal definitions: **[docs/DECODE.md](docs/DECODE.md)**.
Plotted data: **[report/index.html](report/index.html)** (self-contained, opens offline).

---

## Three traps that cost real bench time

**1 · Contact at the pins, not the pinout.** Six rounds of debugging — bitrate
sweeps, polarity swaps, host power, ACK modes — turned out to be a bad connection at
the booster end. Verify continuity from the adapter's **screw terminal** through to
the pin. A clip resting on an exposed pin looks connected and often is not.

**2 · Listen-only is unusable on a 2-node bus.** With no ACK the booster's error
counter climbs 8 per attempt, hits bus-off at ~32 ms, auto-recovers, and repeats.
Same 12-second window:

| Mode | Frames | Unique IDs |
|---|---|---|
| listen-only | 1006 fps | **1** |
| ACK | 37 fps | **4** |

The 1006 fps is a retransmission storm, not a signal — and it **hides three of the
four IDs**. ACK is a link-layer bit, not a command, so read-only capture still
acknowledges. **Always capture in ACK mode.** This applies in the car too, wherever
the booster and your monitor are the only two nodes.

**3 · A powered transceiver idles at 2.5 V even when the ECU is dead.** That reading
proves the transceivers have power. It proves nothing about the ECU running.

---

## Tools

Python, against a CANable-clone USB-CAN adapter (**candleLight/gs_usb**, `1d50:606f`).
Two backends, picked automatically:

- **SocketCAN** (Linux/Pi) — `--channel can-veh`. **No dependencies**; Python speaks
  `AF_CAN` natively. Preferred.
- **gs_usb over libusb** (macOS) — `--index 0`. Needed only because macOS has no
  SocketCAN and the adapter exposes no serial port.

```bash
pip install gs_usb pyusb          # macOS only; plus brew install libusb

python3 tools/sniff.py --mode ack --seconds 30 --log logs/capture.log
python3 tools/analyze.py logs/capture.log --id 39D
python3 tools/plateaus.py logs/capture.log --id 39D --field le23
```

| Tool | Does |
|---|---|
| `tools/sniff.py` | Capture, SocketCAN or gs_usb. candump-format logs, per-byte min/max |
| `tools/analyze.py` | Finds physical signals by **smoothness × activity**, not by range — a checksum spans 00..FF but jumps randomly; a real signal moves smoothly |
| `tools/plateaus.py` | Finds held positions for calibration, by spread rather than min/max |
| `tools/selftest.py` | Positive control between two adapters. **The only file that transmits** — adapter-to-adapter only |

**macOS gotcha, load-bearing:** `sniff.py` stubs `is_kernel_driver_active` to False
and `Device.reset` to a no-op. Without them the first capture in a process works and
every later one fails with "No such device", which reads convincingly as flaky
hardware.

`ibooster_sniffer/` is an ESP32-S3 slcan sniffer, written and compiling but never
needed — the USB adapter path won. Kept as a fallback.

---

## On the Raspberry Pi

The Pi's kernel binds CANable adapters natively, so SocketCAN is available and
`sniff.py` needs **no dependencies at all** there — Python speaks `AF_CAN` directly.

```bash
sudo apt install can-utils
git clone https://github.com/pelosim/tesla-ibooster-can.git ~/ibooster
cd ~/ibooster && ./deploy/install.sh          # persistent names + boot bring-up
./deploy/verify-buses.sh                      # confirm names match buses

python3 tools/sniff.py --channel can-veh --seconds 30 --log logs/veh.log
cansniffer can-veh                            # live changing-byte highlighting
```

`deploy/` pins the two adapters to **`can-veh`** and **`can-yaw`** by USB serial.
Without that, `can0`/`can1` are assigned in enumeration order and **can swap on
reboot**, silently mislabelling which bus a capture came from.

⚠️ Those names follow the **adapter**, not the wire. Move a CAN lead between
adapters and the names become wrong with no warning — hence `verify-buses.sh`, which
checks by content (whichever bus carries `0x39D` is the vehicle bus).

## Raw captures are committed

`logs/` holds the actual bench captures behind every claim in `docs/DECODE.md`, so
the decode can be re-derived rather than taken on trust. Bench frames only — no
vehicle-identifying data.

---

## Docs

| File | What |
|---|---|
| **[docs/DECODE.md](docs/DECODE.md)** | Confirmed signal definitions and calibration |
| **[docs/BENCH_LOG.md](docs/BENCH_LOG.md)** | Dated findings, plus a table of the reasoning errors made along the way |
| **[docs/PINOUT.md](docs/PINOUT.md)** | Measured pinout, and the unverified remainder |
| **[VERIFY_FIRST.md](VERIFY_FIRST.md)** | Gate list — what is confirmed vs still hypothesis |
| **[BENCH_PLAN.md](BENCH_PLAN.md)** | The phased procedure, Phase −1 → 7 |

---

## Still open

- Whether faults *other* than a lost travel sensor produce different status codes.
  Only `1` and `2` have ever been observed.
- `0x33D` — a post-brake event message, all-`FF` 99.8% of the time, fires ~0.8 s
  after release. Three samples is not enough to decode the payload.
- `0x31D` `0x34D` `0x36D` `0x37D` `0x38D` — fire together within ~100 ms, event
  driven, trigger unknown.
- `0x38F` (49.8 Hz, YAW) — `b2` and `b3` move; undecoded.
- Calibration is good to roughly ±2 mm, limited by the ruler rather than the data —
  the signal repeats to 0.06 mm within a hold. Better would need a dial indicator on
  a fixed datum and a *single* run across the whole range.

---

## Safety

This is a **brake actuator**. Everything here reads; nothing commands. On the bench,
clamp it by the mounting studs, keep the pushrod path clear, and use a fused battery
rather than a current-limited supply once ignition is live — the motor draws enough
to sag a bench PSU into a brownout that looks like a fault.

Prior art that got the buses and idle values right, on other variants:
[EVcreate](https://www.evcreate.com/ibooster-can-bus/) ·
[openinverter wiki](https://openinverter.org/wiki/Bosch_iBooster)

MIT licensed. No affiliation with Tesla or Bosch.
