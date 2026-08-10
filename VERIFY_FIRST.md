# VERIFY_FIRST.md

Everything below is **unconfirmed against this actual unit** (Tesla PN
`1037123-00-B`, 2020 Model S LR). The sources are EV-conversion community work on
*other* iBooster variants — Golf MK8, Yaris, Citroën, Honda CR-V, generic Gen1/Gen2.
Bosch sells this ECU into many platforms with different firmware and, plausibly,
different pin assignments.

Do not write any of it into firmware, a DBC, or a wiring harness until the
corresponding box is ticked with a measurement on the bench.

Ticking a box = replacing the claim with what you actually measured, dated.

---

## Bench tooling

- [x] **CONFIRMED 2026-08-06 — `candleLight`/`gs_usb` (`1d50:606f`), not slcan.**
      No serial port. Driven on macOS via `tools/sniff.py` over libusb. Feature
      bitmap `0x000000F3`: LISTEN_ONLY, LOOP_BACK, HW_TIMESTAMP supported;
      ONE_SHOT not.

- [ ] **Is `R120` a solder jumper or a switch, and which state is it in?**
      *Method:* meter across the screw terminals with nothing attached — 120R means
      terminated. **Label it.** The iBooster bus wants it ON (2 nodes, booster
      terminates neither end); the iDrive bus in Phase -1 wants it OFF (already
      terminated both ends). Both are 500 kbps 2-node buses, which is exactly why
      this gets mixed up.

---

## Connector and pinout

- [ ] **Connector is a 26-pin EuCon.** Confirm by part marking and cavity count.
      *Method:* photograph the housing, count cavities, read the molded pin
      numbering. Do not infer numbering from position — the ignition-display
      project already cost 3 boards partly to that class of assumption.

- [ ] **Pin 1 = permanent 12V, pin 9 = GND.** These are the large (4.8 spade)
      terminals. *Method:* identify the two heaviest terminals, confirm continuity
      from pin 9 to the booster housing/ground stud.

- [ ] **Pin 20 = ignition / wake, 12V.** *Method:* small 1.5 terminal; confirm by
      behaviour in Phase 4 (assist only appears once it is energised).

- [x] **CONFIRMED 2026-08-06 — pin 25 = CAN-H, pin 16 = CAN-L.** Not just the
      pairing: this exact polarity produced clean frames, so H/L are assigned.
      Carries `0x39D` stroke — the community's "Vehicle CAN".
- [x] **CONFIRMED 2026-08-06 — pins 18/10 are the second CAN pair**, biased at 2.5V.
      Pairing confirmed; **H/L polarity NOT yet established** and nothing captured
      from it. Try CAN-H → 18, CAN-L → 10 first, matching the convention that
      worked on 25/16.
      ⚠️ Contact at these pins is the failure mode that cost six rounds of
      debugging: verify continuity from the adapter's **screw terminal** through to
      the pin, not just that a clip is sitting on it.

- [~] **Which bus is which.** Pins 25/16 carry the stroke signal, consistent with
      the community's "Vehicle CAN" label. The 18/10 pair is uncaptured, so its
      identity rests on community naming alone — treat "YAW" as a label, not a fact,
      until something is decoded off it.

- [ ] **Pedal travel sensor pins (2, 8, 22, 23).** Gen1 and Gen2 swap which sensor
      sits on which pin, so even the community sources disagree. *Also unresolved:*
      whether the Tesla unit's travel sensor is integrated in the pushrod assembly
      or arrives on a separate connector. Establish this before Phase 5 — without
      a valid sensor the booster will fault and the stroke sweep is meaningless.

---

## Electrical

- [ ] **No internal termination on either bus.** *Method:* unpowered, measure H-to-L
      on each pair. Expect open / very high. If it reads 120R, the unit *is*
      terminated and the bench wiring changes.

- [x] **CONFIRMED 2026-08-06 — 500 kbps.** Clean decode. A passive sweep of
      250k/125k/1M/800k/100k/50k found nothing, so 500k is not a coincidence.
      ⚠️ **Listen-only is UNUSABLE on this bus** — no ACK means a retransmission
      storm (1006 fps of one ID) that *hides* three of the four IDs. ACK mode gives
      37 fps across four. Always capture in ACK mode.

- [ ] **Peak current draw during assist.** Community reports are "tens of amps" and
      the fuse spec is 40A. *Method:* clamp meter on the 12V lead during a full
      apply in Phase 4. This number decides whether a bench supply is usable at all
      or a battery is mandatory. **Assume battery until measured.**

- [ ] **Does it transmit on pins 1+9 alone, with no ignition?** Unknown. Phase 2
      answers it. This matters: if yes, the whole decode can be done without the
      motor ever being able to move.

- [x] **CONFIRMED 2026-08-06 — 37 fps at rest, 37 fps under pedal activity** (4 IDs
      at rest, 11 under activity). Modest, so the **Phase 7 decision resolves to
      option A**: CANable straight onto the Pi, no extra ESP32, no ESP-NOW hop.
      Not yet measured on the second bus.

---

## Behaviour

- [ ] **Does it assist standalone**, with no vehicle CAN traffic present, ignition
      energised? Community says yes for other platforms. If the Tesla firmware
      instead demands specific vehicle messages before it will assist, the
      read-only end state in the 944 is not viable as designed and the whole plan
      needs revisiting. **This is the single highest-value question in the project.**

- [ ] **What does it report with no vehicle present?** Expect fault/degraded flags.
      Capture them — they identify the status byte for free.

- [ ] **Does it emit a power-up self-test that moves the pushrod?** Assume yes until
      proven otherwise. Clamp the unit and keep the pushrod path clear.

---

## CAN decode hypotheses (nothing here is established)

- [x] **KILLED 2026-08-06.** No `0x38E` on this unit. Stroke is **`0x39D` bytes 2:3,
      uint16 little-endian** — see `docs/DECODE.md`. The community hypothesis was
      from other platforms and did not transfer.

- [ ] **YAW `0x38F`** is transmitted; purpose unknown.

- [ ] **Vehicle CAN carries brake input stroke in mm**, reportedly decodable with a
      community Tesla DBC. Identify the ID on this unit before trusting any DBC.

- [ ] **Byte order and scaling** for any signal found. Do not assume big-endian,
      and do not assume the raw byte is millimetres.

---

## Known-good facts (measured here, safe to rely on)

- **2026-08-06** — `ibooster_sniffer` v1.0.0 compiles clean on the v3 toolchain
  (core 3.3.10): 323426 bytes flash (24%), 22716 bytes RAM (6%), zero warnings.
  Not yet run against hardware, and now unlikely to be needed — the CANable path
  works and Phase 7 resolved to option A.

- **2026-08-06** — capture chain proven end to end: `tools/selftest.py` 20/20 between
  two RH02s. The adapter is no longer a candidate explanation for a silent bus.

- **2026-08-06** — **`0x39D` fully decoded**: `b0` = checksum `(b1+b2+b3+0xA0)&0xFF`
  validating on 100% of 2250 frames, `b1` = 4-bit alive counter, `b2:b3` = stroke
  uint16 LE, rest ~262, max observed 14070. See `docs/DECODE.md`.
