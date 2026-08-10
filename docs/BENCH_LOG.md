# BENCH_LOG.md

Dated findings, measured only. Hypotheses live in `VERIFY_FIRST.md`.

---

## 2026-08-06 — First power-up. Booster silent; tooling proven good.

### Adapter

- RH02s carry **candleLight/gs_usb** firmware (`1d50:606f`), **not slcan**. No serial
  port, and macOS has no SocketCAN, so the path is python-can's gs_usb backend over
  libusb. `tools/sniff.py` drives it directly.
- **Positive control PASSED 20/20** (`tools/selftest.py`, two adapters wired to each
  other, R120 on at both, ground shared via the Mac's USB). USB path, driver,
  controller, transceivers, termination, wiring technique and read loop all good.

### Booster — CONFIRMED

- **Both candidate CAN pairs biased at 2.5V**: pins **25/16** and **18/10**. This is
  the first corroboration of the community pinout on a *Tesla* unit — but see the
  caveat below on what 2.5V does and does not prove.

### Booster — NEGATIVE RESULTS

With 12V on pin 1, ground on pin 9, **ignition on pin 20**, common ground to the
adapter, R120 on:

| Tried | Result |
|---|---|
| 500k listen-only, 10s | 0 frames |
| Bitrate sweep — 500k/250k/125k/1M/800k/100k/50k, passive | 0 frames at every rate |
| H/L swapped, 500k listen-only, 10s | 0 frames |
| **ACK mode**, 75s window | 0 frames |

**The booster did not transmit anything, on either bus, under any of the above.**

### ✅ RESOLVED — bad contact at the booster CAN pins

The entire silence chapter was **a bad connection at the booster end**. Once the
leads were re-seated (verified 2.5V at the leads themselves, not just at the pins),
frames appeared immediately. Nothing was wrong with the pinout, the bitrate, the
polarity, the adapter, the host, or the unit.

**Lesson:** verify continuity from the *adapter's screw terminal through to the
booster pin* before trusting any negative result. Clipping onto exposed pins looks
connected and often is not. Six rounds of debugging went into a wiring fault.

### ✅ CONFIRMED — pins 25/16 and 18/10 carry CAN at 500 kbps

Community pinout corroborated on a Tesla `1037123-00-B`.

### ✅ CONFIRMED — listen-only is UNUSABLE on this bus

Same booster, same 12s window, only the mode differs:

| Mode | Total | Unique IDs | 0x39D rate |
|---|---|---|---|
| listen-only | 1006 fps | **1** | 1006 Hz |
| ACK | **37 fps** | **4** | 25.7 Hz |

Listen-only produces a **retransmission storm** — no ACK, so TEC climbs 8 per
attempt, bus-off at 32 attempts (~32 ms), automatic bus-off recovery (~3 ms), repeat.
The 1006 fps is that cycle, not a real signal rate. Worse, **it hid three of the four
IDs** behind the noise.

`GS_CAN_MODE_LISTEN_ONLY` is genuinely supported by the adapter (feature bitmap
`0x000000F3`), so this is real passive behaviour and not a masked-off flag. This
makes the ACK-mode requirement a demonstrated fact rather than a paper argument.

### First ID inventory — ignition on, nothing touched

| ID | rate | bytes | note |
|---|---|---|---|
| `0x39D` | 25.7 Hz | `B5 0C 08 01` | fastest; prime candidate for pedal/stroke |
| `0x33D` | 9.9 Hz | `00 00 FF FF FF FF FF FF` | trailing FF — likely "signal unavailable" |
| `0x35D` | 1.0 Hz | `05 55 55 55 55 55 55 55` | 0x55 fill — placeholder/unused |
| `0x32D` | 0.5 Hz | `0D 00 00 00 8D 79 20 21` | structured; counter or identity? |

The FF and 0x55 fills are consistent with a booster running without vehicle context
and marking those signals invalid.

### ✅ Phase 7 decision criterion MET — 37 fps

Modest by any measure, so **option A (CANable straight onto the Pi) is viable**. The
extra ESP32 and the ESP-NOW hop can be dropped. Re-check if the other bus, or
activity under braking, changes the number materially.

### ✅ IT ASSISTS STANDALONE — the project's central question, answered YES

With 12V, ground and ignition only, and **nothing ever transmitted to it**, the motor
assists. Unpowered the rod is very hard to move by hand; powered it is obviously
boosted.

No vehicle CAN, no wake frame, no keep-alive. **The read-only design is viable in the
944** and the risk of having to transmit to a brake actuator is permanently closed.

### Host-power theory RULED OUT (superseded — the real cause was contact)

Re-ran 500k listen-only for 12s with the MacBook on mains, booster powered, ignition
on, CAN connected: **still 0 frames.** The dying battery was not the explanation and
the negatives below stand.

Further: the adapter left connected is USB Address 004, which was index **[1]** in
the 20/20 selftest — the **receiving** adapter. Its receive path is therefore proven
good on this exact unit, not merely on "an RH02".

Remaining suspects, in order: **contact quality at the exposed pins**, **the ECU not
running at all**, **wrong pins / wrong numbering**.

### ⚠️ Historical note — host power was failing during the first round

**The MacBook's battery died during the live booster testing.** The adapter is USB
bus-powered and USB ground-referenced (150 mA per its descriptor), so a declining
battery can brown out the USB rail long before the machine shuts down. A
marginally-powered CAN adapter fails in exactly the observed way: enumerates,
accepts a bitrate, receives nothing.

The 20/20 positive control was run afterwards, with the Mac back on power. It proves
the adapter is good; it does **not** validate the captures taken while the battery
was dying.

**Every negative above needs repeating with the host on mains** before it means
anything. Better still, run bench captures from the Pi: mains-powered, and
candleLight gives it native SocketCAN and `can-utils`.

### What 2.5V does not prove

A CAN transceiver with power but a host controller held in reset, uninitialised or
faulted still idles recessive at 2.5V. The reading proves the transceivers are
powered. It does **not** prove the ECU is running.

### Correction to earlier reasoning

"Zero frames rules out the ACK trap, because you would see the retransmissions" was
wrong on timing. The retry burst happens within milliseconds of power-up; a capture
started afterwards sees an already-bus-off node. This is why the ACK-mode run must
straddle a power cycle. **Whether that power cycle actually happened during the 75s
window is unconfirmed** — repeat it deliberately before treating it as settled.

### Open, in priority order

0. **Repeat everything with the host on mains.** The negatives above were taken while
   the MacBook battery was failing. Do not reason from them until they are re-taken.
1. **Current draw on the 12V rail.** Free, immediate, independent of the host, and
   splits "ECU not running" from "ECU running but mute". Near-zero means it never
   booted.
2. **Repeat the ACK capture across a deliberate power cycle**, now that the tooling
   is proven.
3. **Re-verify connector pin numbering from the moulded numbers**, not from position
   in the row. If the numbering is off, everything above is measuring wrong pins.
4. **Does it need to see CAN traffic before transmitting?** Same pattern as the
   iDrive controller, which sleeps without its 20 ms keep-alive. If so, passive
   monitoring of this unit is impossible in principle — see CLAUDE.md.
