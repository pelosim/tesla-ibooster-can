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

1. **Current draw on the 12V rail.** Free, immediate, and splits "ECU not running"
   from "ECU running but mute". Near-zero means it never booted.
2. **Repeat the ACK capture across a deliberate power cycle**, now that the tooling
   is proven.
3. **Re-verify connector pin numbering from the moulded numbers**, not from position
   in the row. If the numbering is off, everything above is measuring wrong pins.
4. **Does it need to see CAN traffic before transmitting?** Same pattern as the
   iDrive controller, which sleeps without its 20 ms keep-alive. If so, passive
   monitoring of this unit is impossible in principle — see CLAUDE.md.
