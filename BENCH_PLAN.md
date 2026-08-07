# BENCH_PLAN.md — Tesla iBooster read-only CAN bring-up

DUT: Bosch iBooster Gen2 family, Tesla PN `1037123-00-B`, 2020 Model S LR.
Goal: decode brake pedal position and booster status from CAN, **read-only**.

Read `VERIFY_FIRST.md` before touching anything. Every pin number in this document
is a hypothesis from community sources on *other* iBooster variants.

---

## Safety, briefly

This is a brake actuator with an electric motor that can move the pushrod with
real force.

- **Clamp it to the bench by its mounting studs.** Not held in a hand, not resting
  loose. Assume a power-up self-test will move the rod.
- **Nothing in the pushrod path** — no hands, no fingers, no thin sheet metal.
- **Leave the outlet ports plugged and the reservoir dry.** Avoid repeated
  full-force dry strokes; MC seals do not enjoy them.
- **No firmware in this repo can command it.** The sniffer has no transmit path.

---

## Phase 0 — Intake, no power

1. Photograph the connector face and the housing markings.
2. Count cavities; read the **molded** pin numbering. Do not infer numbering from
   position in the row.
3. Establish whether the pedal travel sensor is integrated in the pushrod assembly
   or on a separate connector. Photograph it either way.
4. Note the casting/label part numbers and the date code.

**Exit criteria:** a labelled photo of the connector with your own pin numbering
overlaid, and a decision on the travel sensor.

**Blocker:** the mating connector (26-pin EuCon, hypothesis) and terminals are the
long-lead item. Back-probing a sealed housing is a poor fallback — order the
pigtail early.

---

## Phase 1 — Electrical identification, still no power

1. Identify the two heaviest terminals → candidate pin 1 (12V) and pin 9 (GND).
   Confirm the ground candidate by continuity to the housing.
2. Resistance-sweep plausible pin pairs looking for the CAN pairs.
   - Open / very high across a pair is **expected** — the iBooster terminates
     neither bus.
   - If any pair reads ~120R, the unit *is* internally terminated. Stop and update
     `VERIFY_FIRST.md`; the bench wiring changes.
3. Record everything in `docs/PINOUT.md` as measured-vs-hypothesis.

**Exit criteria:** 12V, GND and two candidate CAN pairs identified.

---

## Phase 2 — First listen (power on pins 1+9 only)

Power staging matters. In this phase the ignition pin is **not** energised, so the
booster should not be able to assist — nothing moves. Bench supply, current limit
~3A, is fine here.

Wiring:

- 120R across H/L at the booster connector, 120R on the transceiver breakout.
- Common ground between the ESP32, the transceiver and the booster.
- Unpowered, H-to-L should now read **~60R**. Check this before applying power.

Then:

1. Powered, check the candidate CAN pins idle near **2.5V DC**. If you have a
   scope, one look at the differential pair confirms 500 kbps immediately.
2. Flash `ibooster_sniffer`, open a terminal, send `h` for HUMAN mode.
3. Send `L` — **listen-only**, fully passive. Watch for frames.
4. Repeat for the second bus.

**Reading the result:**

| What you see | What it means |
|---|---|
| Clean frames flowing | Bitrate is right. Move on. |
| One frame, then silence | The ACK trap, not dead hardware. Expected on a 2-node bus in listen-only. Proceed to Phase 3. |
| Garbage / bus errors climbing | Wrong bitrate, or H/L swapped. Do **not** open in ACK mode until this is clean. |
| Nothing at all, ever | Either it needs ignition (Phase 4) or you are on the wrong pins. |

The 1 Hz health line in HUMAN mode shows bus state and both error counters, so
error-passive and bus-off are visible instead of just looking like silence.

**Exit criteria:** at least one well-formed frame decoded at 500k, on at least one
bus — or a confident conclusion that ignition is required first.

---

## Phase 3 — Baseline capture (ACK mode)

Send `C` then `O`. NORMAL mode ACKs but transmits no application frames. This is
what "read-only" means in practice, and it stops the booster from giving up.

1. Capture **5 minutes idle, nothing touched**, per bus. Save to `logs/`.
2. This is your reference. Every decode later is a diff against it.
3. Note which IDs are periodic and at what rate, and which appear only once.

    # via canclaude (python-can slcan)
    ./.venv/bin/python canclaude.py capture --interface slcan --channel /dev/ibooster

**Exit criteria:** a clean idle baseline log per bus, and an ID inventory.

---

## Phase 4 — Ignition / wake

Now the motor can run. **Switch to a car battery with a proper fuse.** A
current-limited bench supply will sag during a motor apply and brown out the ECU,
which you will misread as a fault. Clamp meter on the 12V lead if you have one —
`VERIFY_FIRST.md` wants that number.

1. Start the capture *before* the transition.
2. Energise pin 20 (ignition, hypothesis).
3. Capture the wake sequence and whatever it emits with no vehicle present.
4. Diff against the Phase 3 baseline. New IDs and changed bytes are your fault and
   status candidates.

**The question this phase exists to answer:** does it assist standalone, with no
vehicle CAN traffic? If yes, read-only monitoring is viable as the end state in
the 944. If it demands specific vehicle messages before assisting, the plan needs
revisiting before any more effort goes into decoding.

**Exit criteria:** a documented answer to that question, plus a wake-sequence log.

---

## Phase 5 — Stroke sweep (the actual decode)

Do this **unassisted** — pins 1+9 only, ignition off — so the rod moves only when
you move it.

1. Mount a dial indicator or caliper depth rod against the pushrod.
2. Start the capture. Push slowly through full travel, **holding at marked
   positions** for a few seconds each: 0, 25%, 50%, 75%, full, then back down.
3. Log displacement against wall-clock time by hand as you go. The holds are what
   make the correlation trivial — a continuous sweep is much harder to align.
4. Repeat the sweep at least twice for repeatability.

Then correlate. You are looking for a byte, or a 16-bit pair, that moves
**monotonically** with displacement and holds steady during your holds.

Test the cheap hypothesis first: **YAW `0x38E`, byte 3** — idle `0x40` (64), fully
pressed `0xC0` (192). Confirming or killing it settles the method quickly.

**Exit criteria:** a byte offset and an ID that track the rod, reproducible across
two sweeps.

---

## Phase 6 — Decode and confirm

1. SavvyCAN for visual diffing and graphing the candidate signal against your
   position log.
2. Determine byte order and scaling properly. Do not assume big-endian; do not
   assume the raw value is millimetres. Two known displacement points give you
   scale and offset.
3. Try a community Tesla DBC against the vehicle-CAN log for the reported
   "brake input stroke in mm" signal — but identify the ID on *this* unit first
   rather than trusting the DBC's mapping.
4. Write confirmed signals into `docs/PINOUT.md` and move the corresponding boxes
   out of `VERIFY_FIRST.md`.

**Exit criteria:** a small DBC covering the signals you actually need, validated
against a fresh capture.

---

## Phase 7 — Into the car

The bench configuration **is** the car configuration. The 944 is pre-CAN, so the
iBooster and the monitoring ESP32 form a private 2-node bus — exactly like the
iDrive bus already in the car.

- 120R at both ends stays required.
- The ESP32 must stay in **ACK mode permanently**, or the booster goes bus-off in
  service. This is not a bench-only concern.
- Add the udev rule in `tools/99-ibooster.rules` to pin the board to
  `/dev/ibooster` on the HVAC Pi's hub, alongside `/dev/idrive`, `/dev/lighting`
  and the two gauge panels. Pin by MAC — adding the hub already reshuffled
  enumeration once on that Pi.
- **Settled 2026-08-06 — display and logging only, nothing actuates.** Brake lights
  stay on the mechanical pedal switch. Because no output depends on a frame
  arriving, best-effort transport is acceptable throughout.
- Data goes to the **HVAC Pi over USB CDC as the primary sink** (logging is the
  payoff), and to **gauge panel B over ESP-NOW** as a status indicator. Show the
  fault/status state, not a live stroke needle.
- Panel B's firmware does not exist yet — `slave_app.h` was never assembled into a
  `gauges_slave` sketch, which is why `/dev/gauges2` refuses to flash. Fold the
  brake indicator in while writing it. Fitting a third element beside AFR and
  BATTERY on a 180x640 strip is the real constraint.
- Write `ibooster_monitor` for the car; leave `ibooster_sniffer` as the bench tool.
  It cannot be written before Phase 6 confirms where the signals actually live.

---

## Open questions carried forward

- Travel sensor: integrated or separate connector? (Phase 0)
- Does it transmit at all on pins 1+9 alone? (Phase 2)
- Does it assist with no vehicle CAN present? (Phase 4)
- Peak current during a full apply? (Phase 4)
- Which physical bus carries the useful stroke signal on the Tesla firmware? (Phase 5)

---

## Sources

Community reverse-engineering on other iBooster variants — useful starting points,
none confirmed against this Tesla unit:

- EVcreate — [iBooster CAN-BUS research](https://www.evcreate.com/ibooster-can-bus/)
- EVcreate — [Wiring the iBooster](https://www.evcreate.com/wiring-the-ibooster/)
- openinverter wiki — [Bosch iBooster](https://openinverter.org/wiki/Bosch_iBooster)
- openinverter forum — [Yaris Gen4 iBooster Gen2](https://openinverter.org/forum/viewtopic.php?t=5925)
- openinverter forum — [VAG iBooster info thread](https://openinverter.org/forum/viewtopic.php?p=82361)
- DIY Electric Car — [Wiring Tesla iBooster](https://www.diyelectriccar.com/threads/wiring-tesla-ibooster.195506/)
