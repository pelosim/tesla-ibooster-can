#!/usr/bin/env python3
"""
Read-only CAN sniffer for the iBooster.

THIS TOOL NEVER TRANSMITS AN APPLICATION FRAME. There is no send path in it.
See CLAUDE.md for why that matters when the device under test is a brake actuator.

Two backends, picked automatically:

  SocketCAN (Linux)   --channel can0. Zero dependencies -- Python's socket module
                      speaks AF_CAN natively. This is the path on the Pi.
  gs_usb   (macOS)    --index 0. Drives a CANable/candleLight adapter over libusb,
                      because macOS has no SocketCAN. Needs gs_usb + pyusb.

Mode differs between the two, and it matters:

  SocketCAN   listen-only is a property of the *interface*, set with `ip link`,
              not by this program. It reports whichever mode the link is in.
  gs_usb      --mode listen|ack is set here, per capture.

Either way: on a 2-node bus, listen-only produces a retransmission storm that hides
most of the traffic. Capture in ACK mode. ACK is a link-layer bit, not a command.

Usage:
    python3 sniff.py --channel can0 --seconds 30 --log logs/yaw.log
    python3 sniff.py --mode ack --seconds 30 --log logs/veh.log     # macOS
    python3 sniff.py --list
"""
import argparse
import os
import platform
import struct
import sys
import time
from collections import Counter

CAN_EFF_FLAG = 0x80000000
CAN_RTR_FLAG = 0x40000000
CAN_ERR_FLAG = 0x20000000
CAN_SFF_MASK = 0x000007FF
CAN_EFF_MASK = 0x1FFFFFFF


# ── SocketCAN backend (Linux, no dependencies) ────────────────────────────────
class SocketCanReader:
    name = "socketcan"

    def __init__(self, channel):
        import socket
        self.channel = channel
        self.sock = socket.socket(socket.PF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
        try:
            self.sock.bind((channel,))
        except OSError as e:
            raise SystemExit(
                f"Cannot bind {channel}: {e}\n"
                f"Bring it up first:\n"
                f"  sudo ip link set {channel} type can bitrate 500000\n"
                f"  sudo ip link set {channel} up")
        self.sock.settimeout(0.2)

    def link_mode(self):
        """Report the interface's real mode -- this program cannot change it."""
        try:
            import subprocess
            out = subprocess.run(["ip", "-details", "link", "show", self.channel],
                                 capture_output=True, text=True, timeout=4).stdout
        except Exception:
            return "unknown"
        if "listen-only" in out:
            return "LISTEN-ONLY (set on the interface)"
        return "normal — ACKs, transmits nothing"

    def read(self):
        """-> (arbitration_id, data) or None on timeout."""
        import socket as _s
        try:
            frame = self.sock.recv(16)
        except (_s.timeout, TimeoutError):
            return None
        can_id, dlc = struct.unpack("=IB3x", frame[:8])
        if can_id & CAN_ERR_FLAG:
            return None
        mask = CAN_EFF_MASK if can_id & CAN_EFF_FLAG else CAN_SFF_MASK
        return can_id & mask, frame[8:8 + min(dlc, 8)]

    def close(self):
        self.sock.close()


# ── gs_usb backend (macOS, over libusb) ───────────────────────────────────────
class GsUsbReader:
    name = "gs_usb"

    def __init__(self, index, bitrate, listen_only):
        import usb.core
        if platform.system() == "Darwin":
            # macOS reports a kernel driver as active on this device and then refuses
            # to detach it (EACCES), and gs_usb's start() does a USB-level reset that
            # re-enumerates the adapter, invalidating every handle including the one
            # scan() hands back next. Without both stubs the first capture in a
            # process works and every later one fails -- which reads as flaky hardware.
            usb.core.Device.is_kernel_driver_active = lambda self, i: False
            usb.core.Device.reset = lambda self: None
        from gs_usb.gs_usb import GsUsb
        from gs_usb.gs_usb_frame import GsUsbFrame
        from gs_usb.constants import GS_CAN_MODE_LISTEN_ONLY, GS_CAN_MODE_NORMAL
        self._Frame = GsUsbFrame
        devs = GsUsb.scan()
        if not devs:
            raise SystemExit("No gs_usb adapter found.")
        if index >= len(devs):
            raise SystemExit(f"--index {index} but only {len(devs)} adapter(s).")
        self.dev = devs[index]
        if not self.dev.set_bitrate(bitrate):
            raise SystemExit("Failed to set bitrate.")
        self.listen_only = listen_only
        self.dev.start(GS_CAN_MODE_LISTEN_ONLY if listen_only else GS_CAN_MODE_NORMAL)
        self.frame = GsUsbFrame()

    def link_mode(self):
        return ("LISTEN-ONLY (passive, no ACK)" if self.listen_only
                else "normal — ACKs, transmits nothing")

    def read(self):
        if self.dev.read(self.frame, 100):
            return self.frame.arbitration_id, bytes(self.frame.data[:self.frame.can_dlc])
        return None

    def close(self):
        self.dev.stop()


def list_adapters():
    if platform.system() == "Linux":
        import glob
        found = [os.path.basename(p) for p in sorted(glob.glob("/sys/class/net/can*"))]
        print("SocketCAN interfaces:", ", ".join(found) if found else "none")
        print("\nBring one up with:")
        print("  sudo ip link set can0 type can bitrate 500000 && sudo ip link set can0 up")
        return 0
    try:
        from gs_usb.gs_usb import GsUsb
        for i, d in enumerate(GsUsb.scan()):
            print(f"[{i}] {d}")
    except ImportError:
        print("gs_usb not installed: pip install gs_usb pyusb", file=sys.stderr)
        return 1
    return 0


def main():
    ap = argparse.ArgumentParser(description="Read-only iBooster CAN sniffer")
    ap.add_argument("--channel", help="SocketCAN interface, e.g. can0 (Linux)")
    ap.add_argument("--index", type=int, default=0, help="gs_usb adapter index (macOS)")
    ap.add_argument("--mode", choices=["listen", "ack"], default="ack",
                    help="gs_usb only; on SocketCAN the interface decides")
    ap.add_argument("--bitrate", type=int, default=500000)
    ap.add_argument("--seconds", type=float, default=0, help="0 = until Ctrl-C")
    ap.add_argument("--log", help="candump-format log (SavvyCAN reads it)")
    ap.add_argument("--quiet", action="store_true", help="stats line only")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    if args.list:
        return list_adapters()

    if args.channel:
        rdr = SocketCanReader(args.channel)
        src = args.channel
    else:
        if platform.system() == "Linux":
            print("On Linux, pass --channel can0 (SocketCAN). "
                  "Run --list to see interfaces.", file=sys.stderr)
            return 1
        rdr = GsUsbReader(args.index, args.bitrate, args.mode == "listen")
        src = f"adapter {args.index}"

    logf = None
    if args.log:
        d = os.path.dirname(os.path.abspath(args.log))
        if d:
            os.makedirs(d, exist_ok=True)
        logf = open(args.log, "w")

    print(f"# {rdr.name} on {src} @ {args.bitrate} bps")
    print(f"# mode: {rdr.link_mode()}")
    print("# Ctrl-C to stop and print the ID inventory.\n")

    counts, first_seen, last_data = Counter(), {}, {}
    byte_min, byte_max = {}, {}
    total, prev_total = 0, 0
    t0 = t_stat = time.time()

    try:
        while True:
            now = time.time()
            if args.seconds and now - t0 >= args.seconds:
                break
            got = rdr.read()
            if got:
                cid, data = got
                total += 1
                counts[cid] += 1
                first_seen.setdefault(cid, now - t0)
                changed = last_data.get(cid) is not None and last_data[cid] != data
                last_data[cid] = data
                if cid not in byte_min:
                    byte_min[cid], byte_max[cid] = list(data), list(data)
                else:
                    lo, hi = byte_min[cid], byte_max[cid]
                    for i, b in enumerate(data):
                        if i < len(lo):
                            if b < lo[i]:
                                lo[i] = b
                            if b > hi[i]:
                                hi[i] = b
                if not args.quiet:
                    print(f"{now - t0:9.4f} {cid:03X}{'*' if changed else ' '} "
                          f"[{len(data)}] {data.hex(' ').upper()}")
                if logf:
                    logf.write(f"({now:.6f}) {src} {cid:03X}#{data.hex().upper()}\n")

            if now - t_stat >= 1.0:
                print(f"--- {now - t0:6.1f}s  frames={total}  ids={len(counts)}  "
                      f"{(total - prev_total) / (now - t_stat):6.1f} fps", flush=True)
                prev_total, t_stat = total, now
    except KeyboardInterrupt:
        print()
    finally:
        rdr.close()
        if logf:
            logf.close()

    elapsed = time.time() - t0
    print(f"\n=== {total} frames, {len(counts)} unique IDs, {elapsed:.1f}s, "
          f"{total / elapsed if elapsed else 0:.1f} fps total ===")
    if not total:
        print("\nNo frames. Check, in this order:")
        print("  1. continuity from the adapter's SCREW TERMINAL through to the pin")
        print("     -- a clip resting on an exposed pin looks connected and often isn't")
        print("  2. polarity: swap CANH/CANL")
        print("  3. that the interface is up at 500000 and NOT listen-only")
        return 0

    print(f"\n{'ID':>6} {'count':>8} {'rate/s':>8}  first@   last bytes")
    for cid, n in counts.most_common():
        print(f"{cid:6X} {n:8d} {n / elapsed:8.1f}  {first_seen[cid]:6.2f}  "
              f"{last_data[cid].hex(' ').upper()}")

    # During a stroke sweep the byte tracking the pushrod shows a wide span while
    # everything else stays fixed -- that is the whole decode.
    print("\nPer-byte range (min..max). '.' = never changed:")
    for cid, _ in counts.most_common():
        lo, hi = byte_min[cid], byte_max[cid]
        cells = [f"  .{lo[i]:02X} " if lo[i] == hi[i] else f"{lo[i]:02X}-{hi[i]:02X}"
                 for i in range(len(lo))]
        movers = sum(1 for i in range(len(lo)) if lo[i] != hi[i])
        print(f"  {cid:03X}  {' '.join(cells)}{'  <-- MOVING' if movers else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
