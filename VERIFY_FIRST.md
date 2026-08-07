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

- [ ] **Which firmware is on the CANable clone (Jhoinrch RH02)?** `ls /dev/cu.usbmodem*`
      — a serial device means `slcan` (works on the Mac via python-can
      `bustype='slcan'`); nothing means `candleLight`/`gs_usb`, which has no serial
      port and needs the Pi, since macOS has no SocketCAN.

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

- [ ] **Vehicle CAN: pin 25 = CAN-H, pin 16 = CAN-L.**
      *Method:* unpowered resistance sweep for a plausible pair, then powered DC
      check — both should idle near 2.5V, H rising and L falling on traffic.
      Scope across the pair confirms 500 kbps instantly if one is available.

- [ ] **YAW CAN: pin 18 = CAN-H, pin 10 = CAN-L.** Same method.

- [ ] **Which bus is which.** The "vehicle" and "YAW" labels come from other
      platforms. On the Tesla unit, identify each bus by what it carries, not by
      the pin it arrived on.

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

- [ ] **Both buses are 500 kbps.** *Method:* Phase 2, listen-only. Clean decode at
      500k is the confirmation. Garbage or bus errors mean try another rate before
      ever opening in ACK mode.

- [ ] **Peak current draw during assist.** Community reports are "tens of amps" and
      the fuse spec is 40A. *Method:* clamp meter on the 12V lead during a full
      apply in Phase 4. This number decides whether a bench supply is usable at all
      or a battery is mandatory. **Assume battery until measured.**

- [ ] **Does it transmit on pins 1+9 alone, with no ignition?** Unknown. Phase 2
      answers it. This matters: if yes, the whole decode can be done without the
      motor ever being able to move.

- [ ] **Total frame rate, per bus.** Phase 3. Not a safety item — it is the criterion
      that decides the Phase 7 car-side architecture (dongle-on-Pi vs a dedicated
      ESP32 filtering the stream). Nothing else measures it, so do not skip past it.

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

- [ ] **YAW `0x38E`, byte 3 = pedal position**, idle `0x40` (64), fully pressed
      `0xC0` (192). Strongest starting hypothesis. Confirm or kill it first in
      Phase 5 — it is cheap to test and settles the method.

- [ ] **YAW `0x38F`** is transmitted; purpose unknown.

- [ ] **Vehicle CAN carries brake input stroke in mm**, reportedly decodable with a
      community Tesla DBC. Identify the ID on this unit before trusting any DBC.

- [ ] **Byte order and scaling** for any signal found. Do not assume big-endian,
      and do not assume the raw byte is millimetres.

---

## Known-good facts (measured here, safe to rely on)

- **2026-08-06** — `ibooster_sniffer` v1.0.0 compiles clean on the v3 toolchain
  (core 3.3.10): 323426 bytes flash (24%), 22716 bytes RAM (6%), zero warnings.
  Not yet run against hardware.
