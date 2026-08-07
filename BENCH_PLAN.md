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

## Bench tooling

**Primary: the CANable-clone USB-CAN dongle** (Jhoinrch RH02, already owned).
Purpose-built, known-good, screw terminals for CANH/GND/CANL. A second one is ~$19
and lets you capture both booster buses on one timeline instead of stitching two
sweeps together — worth it before Phase 5.

**Fallback: `ibooster_sniffer`** on an ESP32-S3 + SN65HVD230. Written and compiling,
but nothing needs ordering for it unless the dongle disappoints.

⚠️ **The MCP2551 in the parts drawer will not work with an ESP32-S3.** It is 5V-only:
its RXD swings to 5V into a GPIO whose absolute max is ~3.6V (the S3 is not 5V
tolerant), and its TXD high threshold is 0.7 × VDD = 3.5V, above the 3.3V the S3
drives. A marginal TXD can be read as dominant and **jam the bus** — active failure,
not passive, on a brake actuator's wire. Use SN65HVD230 (3.3V native) or TJA1051T/3
(VIO pin) if the ESP32 path is ever taken up.

### Termination — the rule inverts, so read carefully

The dongle has an `R120` option on the silkscreen. **Work out whether it is a solder
jumper or a switch, and label which state it is in**, because the two buses you will
touch want opposite settings:

| Bus | Termination | Why |
|---|---|---|
| iBooster bench/car bus | **R120 ON** | 2 nodes, iBooster terminates neither end |
| iDrive bus (Phase -1 tap) | **R120 OFF** | Already terminated both ends — you would be a third |

Both are 500 kbps 2-node buses, which is exactly why this is easy to mix up.

### Host setup

Check which firmware the dongle carries — it decides everything downstream:

```bash
ls /dev/cu.usbmodem*
```

- **Serial device appears** → `slcan` firmware. Works on the Mac today via
  python-can `bustype='slcan'`, and with canclaude.
- **Nothing appears** → `candleLight`/`gs_usb`. That is a native USB protocol with
  no serial port, and macOS has no SocketCAN — it will only work on the Pi.

**Prefer running it on the Pi either way.** candleLight gives a real `can0` SocketCAN
interface, which unlocks `can-utils` — and `cansniffer` in particular, which
highlights changing bytes live and in place. For the Phase 5 stroke sweep that is
close to the ideal tool: you will likely *see* the pedal byte move as you push the
rod, before writing any analysis code.

---

## Phase -1 — Validate the toolchain (no booster required)

Do this while the booster and connector are still in transit. The point is that when
the booster arrives and something looks wrong, you already know it is the booster or
the wiring — not your tooling.

Target: **the iDrive bus.** It is a known-good 500 kbps 2-node bus with known traffic
on `0x25B`, already in the car.

1. **R120 OFF.** That bus is already terminated at both ends; adding a third
   terminator is the mistake this step exists to not make.
2. Tap CANH/CANL with as short a stub as you can manage.
3. Capture. You should see `0x25B` plus the iDrive wake/keep-alive frames.
4. Turn the knob. `b1` should change with rotation.

**Exit criteria:** frames decoded end to end — dongle → host → canclaude/candump —
with timestamps that make sense. Toolchain trusted.

**Note:** the iDrive board transmits a 20 ms keep-alive, so unlike the booster bench
there are already two ACKing nodes here. The ACK trap will not show up in this phase.
Do not conclude from a clean run that it will not bite you in Phase 2.

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

- **R120 ON** at the dongle, plus a loose 120R across H/L at the booster connector.
- Common ground between the dongle and the booster.
- Unpowered, H-to-L should now read **~60R**. Check this before applying power.

Then:

1. Powered, check the candidate CAN pins idle near **2.5V DC**. If you have a
   scope, one look at the differential pair confirms 500 kbps immediately.
2. Open the bus **listen-only** — fully passive, no ACK:

   ```bash
   # SocketCAN (Pi, candleLight firmware)
   sudo ip link set can0 type can bitrate 500000 listen-only on && sudo ip link set can0 up
   candump -td can0
   ```

   With slcan firmware, or `ibooster_sniffer` as the fallback, the equivalent is the
   `L` command (`h` first for human-readable mode).
3. Watch for frames.
4. Repeat for the second bus.

**Reading the result:**

| What you see | What it means |
|---|---|
| Clean frames flowing | Bitrate is right. Move on. |
| One frame, then silence | The ACK trap, not dead hardware. Expected on a 2-node bus in listen-only. Proceed to Phase 3. |
| Garbage / bus errors climbing | Wrong bitrate, or H/L swapped. Do **not** open in ACK mode until this is clean. |
| Nothing at all, ever | Either it needs ignition (Phase 4) or you are on the wrong pins. |

Watch the error counters, not just the frame stream — `ip -details -statistics link
show can0` on SocketCAN, or the 1 Hz health line in `ibooster_sniffer`'s HUMAN mode.
Error-passive and bus-off are the difference between "wrong pins" and "the ACK trap",
and both look like silence if you only watch for frames.

**Exit criteria:** at least one well-formed frame decoded at 500k, on at least one
bus — or a confident conclusion that ignition is required first.

---

## Phase 3 — Baseline capture (ACK mode)

Reopen the bus **without** listen-only. Normal mode ACKs but transmits no
application frames — that is what "read-only" means in practice, and it is what
stops the booster from giving up and going bus-off.

```bash
# SocketCAN — note: no 'listen-only on' this time
sudo ip link set can0 down
sudo ip link set can0 type can bitrate 500000 && sudo ip link set can0 up
candump -l can0                       # writes candump-*.log
```

With `ibooster_sniffer` the equivalent is `C` then `O`.

1. Capture **5 minutes idle, nothing touched**, per bus. Save to `logs/`.
2. This is your reference. Every decode later is a diff against it.
3. Note which IDs are periodic and at what rate, and which appear only once.

```bash
# frame rate per ID — feeds the Phase 7 decision below
candump -n 10000 can0 | awk '{print $3}' | sort | uniq -c | sort -rn
```

**Record the total frame rate.** It is the criterion that decides the car-side
architecture in Phase 7, and this is the only phase that measures it.

**Exit criteria:** a clean idle baseline log per bus, an ID inventory, and a
frames-per-second figure.

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

1. `cansniffer can0` first — it highlights changing bytes live and in place, and on
   a signal this obvious it may well identify the byte before you write any analysis
   code. SavvyCAN afterwards for graphing the candidate against your position log.
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

The bench bus **is** the car bus. The 944 is pre-CAN, so the iBooster and whatever
monitors it form a private 2-node bus — exactly like the iDrive bus already there.

Settled already:

- **Display and logging only, nothing actuates** (2026-08-06). Brake lights stay on
  the mechanical pedal switch. Because no output depends on a frame arriving,
  best-effort transport is acceptable throughout — and Pi flakiness costs a stale
  pixel, nothing more.
- **120R at both ends stays required**, in the car as much as on the bench.
- **ACK mode permanently.** Listen-only in service would drive the booster bus-off.
  This is not a bench-only concern.
- **Show fault/status, not a live stroke needle.** The driver is pressing the pedal
  and already knows where it is. Stroke stays a logging and replay signal.
- Panel B's firmware does not exist yet — `slave_app.h` was never assembled into a
  `gauges_slave` sketch, which is why `/dev/gauges2` refuses to flash. Fold the
  brake indicator in while writing it. Fitting a third element beside AFR and
  BATTERY on a 180x640 strip is the real constraint.

### Open decision: dongle-on-Pi vs dedicated ESP32

Deferred deliberately — it depends on the frame rate measured in **Phase 3**.

| | **A — CANable on the Pi** | **B — ESP32 + transceiver** |
|---|---|---|
| Path | dongle → Pi USB → SocketCAN → backend → panel B over its existing USB link | ESP32 → USB CDC to Pi, → ESP-NOW to panel B |
| Boards added | none | one, plus firmware to maintain |
| ESP-NOW hop | not needed | yes |
| Cost | Pi backend chews every frame, alongside HVAC, iDrive, lighting, dashboard and kiosk | isolated MCU, boots in <1s, filters to the 2 signals that matter |

**Criterion:** if the booster's traffic is modest, take **A** — it deletes a board
and an ESP-NOW hop, and SocketCAN is far better tooled. If it emits hundreds of
frames a second, take **B**; the Pi is already the busiest thing in the car and
should not be parsing a firehose to extract two signals.

If **B**: write `ibooster_monitor` (leave `ibooster_sniffer` as the bench tool), and
add the udev rule in `tools/99-ibooster.rules` to pin the board to `/dev/ibooster`
alongside `/dev/idrive`, `/dev/lighting` and the two gauge panels. Pin by MAC —
adding the hub already reshuffled enumeration once on that Pi.

Either way, `ibooster_monitor` cannot be written before Phase 6 confirms where the
signals actually live.

---

## Open questions carried forward

- Which firmware is on the dongle — slcan or candleLight? (Phase -1)
- Is `R120` a solder jumper or a switch, and which state is it in? (Phase -1)
- Travel sensor: integrated or separate connector? (Phase 0)
- Does it transmit at all on pins 1+9 alone? (Phase 2)
- **Total frame rate** — decides the Phase 7 architecture. (Phase 3)
- Does it assist with no vehicle CAN present? (Phase 4)
- Peak current during a full apply? (Phase 4)
- Which physical bus carries the useful stroke signal on the Tesla firmware? (Phase 5)
- Dongle-on-Pi or dedicated ESP32 in the car? (Phase 7, gated on Phase 3)

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
