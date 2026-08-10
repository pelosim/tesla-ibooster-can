#!/usr/bin/env python3
"""
Read-only CAN sniffer for the iBooster bench, driving a CANable/gs_usb adapter
(Jhoinrch RH02) over libusb. Works on macOS, which has no SocketCAN.

THIS TOOL NEVER TRANSMITS AN APPLICATION FRAME. There is no send path in it --
GsUsb.send() is never called. See CLAUDE.md for why that matters here.

    listen  fully passive, does not even ACK. Confirms bitrate/polarity.
            On a 2-node bus the booster will retransmit unACKed and eventually
            go bus-off, so expect traffic to stop. That is the ACK trap, not
            dead hardware.
    ack     ACKs at the link layer, sends nothing. This is what "read-only"
            means in practice and what a sustained capture needs.

Usage:
    python3 sniff.py --mode listen --seconds 20
    python3 sniff.py --mode ack --log logs/vehicle-baseline.log
    python3 sniff.py --list
"""
import argparse
import os
import platform
import sys
import time
from collections import Counter

import usb.core

# macOS: libusb reports a kernel driver as active on this device and then refuses
# to detach it (EACCES), which makes gs_usb's start() blow up on every call after
# the first. There is no kernel driver to detach on Darwin, so skipping the check
# is correct rather than a workaround. Without this, the first run works and every
# subsequent one fails -- which reads like flaky hardware.
if platform.system() == "Darwin":
    usb.core.Device.is_kernel_driver_active = lambda self, interface: False

    # gs_usb's start() calls a USB-level reset() to allow restarting. On macOS that
    # re-enumerates the adapter and invalidates every existing handle, including the
    # one scan() hands back afterwards -- so the second start() in a process dies
    # with "No such device". stop() already issues a device-level CAN reset via
    # control transfer, which is the part that actually matters, so dropping the USB
    # reset is safe here and makes multiple start/stop cycles work.
    usb.core.Device.reset = lambda self: None

from gs_usb.gs_usb import GsUsb
from gs_usb.gs_usb_frame import GsUsbFrame
from gs_usb.constants import GS_CAN_MODE_LISTEN_ONLY, GS_CAN_MODE_NORMAL


def acquire(index=0, retries=8, delay=0.4):
    """Get a fresh device handle, retrying while the adapter re-enumerates."""
    for _ in range(retries):
        try:
            devs = GsUsb.scan()
            if devs and index < len(devs):
                return devs[index]
        except usb.core.USBError:
            pass
        time.sleep(delay)
    return None


def sweep(index, rates=(500000, 250000, 125000, 1000000, 800000, 100000, 50000)):
    """Passive bitrate sweep. Never transmits -- listen-only throughout, so a
    wrong guess cannot disturb the bus."""
    print("# passive bitrate sweep, listen-only throughout\n")
    hits = []
    frame = GsUsbFrame()
    for rate in rates:
        # Re-acquire every iteration: gs_usb's start() calls reset(), which
        # re-enumerates the adapter on macOS and invalidates the old handle.
        # Reusing it gives "No such device" on the second rate.
        dev = acquire(index)
        if dev is None:
            print("Lost the adapter mid-sweep. Unplug/replug and re-run.",
                  file=sys.stderr)
            return 1
        dev.set_bitrate(rate)
        dev.start(GS_CAN_MODE_LISTEN_ONLY)
        n, ids, end = 0, set(), time.time() + 3.0
        while time.time() < end:
            if dev.read(frame, 100):
                n += 1
                ids.add(frame.arbitration_id)
        dev.stop()
        flag = "  <-- TRAFFIC" if n else ""
        print(f"{rate:>8} bps: {n:5d} frames, {len(ids):3d} ids{flag}")
        if n:
            hits.append((rate, n, sorted(ids)))
    if hits:
        print("\nTraffic found:")
        for rate, n, ids in hits:
            print(f"  {rate} bps -> {n} frames, IDs "
                  f"{', '.join(f'{i:X}' for i in ids[:12])}")
    else:
        print("\nSilent at every standard bitrate. The bus is not being driven.")
        print("Check, in this order: common ground, polarity, then ignition.")
    return 0


def main():
    ap = argparse.ArgumentParser(description="Read-only iBooster CAN sniffer")
    ap.add_argument("--mode", choices=["listen", "ack"], default="listen")
    ap.add_argument("--bitrate", type=int, default=500000)
    ap.add_argument("--index", type=int, default=0,
                    help="which adapter, if both RH02s are plugged in")
    ap.add_argument("--seconds", type=float, default=0, help="0 = until Ctrl-C")
    ap.add_argument("--log", help="candump-format log (SavvyCAN can read it)")
    ap.add_argument("--quiet", action="store_true",
                    help="stats line only, no per-frame output")
    ap.add_argument("--list", action="store_true", help="list adapters and exit")
    ap.add_argument("--sweep", action="store_true",
                    help="try common bitrates, passively, ~3s each")
    args = ap.parse_args()

    if args.sweep:
        return sweep(args.index)

    devs = GsUsb.scan()
    if args.list or not devs:
        for i, d in enumerate(devs):
            print(f"[{i}] {d}")
        if not devs:
            print("No gs_usb adapter found. Check the cable, then re-run.",
                  file=sys.stderr)
            return 1
        return 0

    if args.index >= len(devs):
        print(f"--index {args.index} but only {len(devs)} adapter(s) found.",
              file=sys.stderr)
        return 1

    dev = devs[args.index]
    if not dev.set_bitrate(args.bitrate):
        print("Failed to set bitrate.", file=sys.stderr)
        return 1

    flags = GS_CAN_MODE_LISTEN_ONLY if args.mode == "listen" else GS_CAN_MODE_NORMAL
    dev.start(flags)

    logf = None
    if args.log:
        os.makedirs(os.path.dirname(os.path.abspath(args.log)), exist_ok=True)
        logf = open(args.log, "w")

    banner = "LISTEN-ONLY (passive, no ACK)" if args.mode == "listen" \
        else "ACK MODE (acknowledges, transmits nothing)"
    print(f"# {banner} @ {args.bitrate} bps, adapter {args.index}")
    print("# Ctrl-C to stop and print the ID inventory.\n")

    counts = Counter()
    first_seen = {}
    last_data = {}
    byte_min = {}   # id -> [min per byte position]
    byte_max = {}   # id -> [max per byte position]
    total = 0
    t0 = time.time()
    t_stat = t0
    prev_total = 0

    frame = GsUsbFrame()
    try:
        while True:
            now = time.time()
            if args.seconds and now - t0 >= args.seconds:
                break

            if dev.read(frame, 100):
                total += 1
                cid = frame.arbitration_id
                data = bytes(frame.data[:frame.can_dlc])
                counts[cid] += 1
                first_seen.setdefault(cid, now - t0)
                changed = last_data.get(cid) is not None and last_data[cid] != data
                last_data[cid] = data

                if cid not in byte_min:
                    byte_min[cid] = list(data)
                    byte_max[cid] = list(data)
                else:
                    lo, hi = byte_min[cid], byte_max[cid]
                    for i, b in enumerate(data):
                        if i < len(lo):
                            if b < lo[i]:
                                lo[i] = b
                            if b > hi[i]:
                                hi[i] = b

                if not args.quiet:
                    mark = "*" if changed else " "
                    print(f"{now - t0:9.4f} {cid:03X}{mark} [{frame.can_dlc}] "
                          f"{data.hex(' ').upper()}")
                if logf:
                    logf.write(f"({now:.6f}) can0 {cid:03X}#{data.hex().upper()}\n")

            if now - t_stat >= 1.0:
                fps = (total - prev_total) / (now - t_stat)
                print(f"--- {now - t0:6.1f}s  frames={total}  ids={len(counts)}  "
                      f"{fps:6.1f} fps", flush=True)
                prev_total, t_stat = total, now
    except KeyboardInterrupt:
        print()
    finally:
        dev.stop()
        if logf:
            logf.close()

    elapsed = time.time() - t0
    print(f"\n=== {total} frames, {len(counts)} unique IDs, {elapsed:.1f}s, "
          f"{total / elapsed if elapsed else 0:.1f} fps total ===")
    if not total:
        print("\nNo frames. Before assuming wrong pins, rule out:")
        print("  - polarity: swap CANH/CANL and retry (10 seconds, most likely cause)")
        print("  - the booster may need ignition (pin 20) before it talks -- Phase 4")
        print("  - in listen mode the ACK trap can stop traffic after one frame;")
        print("    re-run with --mode ack")
        return 0

    print(f"\n{'ID':>6} {'count':>8} {'rate/s':>8}  first@   last bytes")
    for cid, n in counts.most_common():
        print(f"{cid:6X} {n:8d} {n / elapsed:8.1f}  {first_seen[cid]:6.2f}  "
              f"{last_data[cid].hex(' ').upper()}")

    # Per-byte ranges. During a stroke sweep the byte tracking the pushrod shows a
    # wide span while everything else stays fixed -- that is the whole decode.
    print("\nPer-byte range (min..max). '.' = never changed:")
    for cid, _ in counts.most_common():
        lo, hi = byte_min[cid], byte_max[cid]
        cells = []
        for i in range(len(lo)):
            if lo[i] == hi[i]:
                cells.append(f"  .{lo[i]:02X} ")
            else:
                cells.append(f"{lo[i]:02X}-{hi[i]:02X}")
        movers = sum(1 for i in range(len(lo)) if lo[i] != hi[i])
        flag = "  <-- MOVING" if movers else ""
        print(f"  {cid:03X}  {' '.join(cells)}{flag}")

    print("\nRecord the total fps in VERIFY_FIRST.md -- it decides the Phase 7 "
          "car-side architecture.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
