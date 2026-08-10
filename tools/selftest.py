#!/usr/bin/env python3
"""
Positive control for the capture chain: adapter 0 sends known frames, adapter 1
receives them. Proves libusb, gs_usb, bitrate, termination and your wiring
technique all work -- so that a later "0 frames" on the booster means the booster.

  ############################################################################
  #  THIS TOOL TRANSMITS. It is the ONLY file in this repo that does.        #
  #  NEVER run it with either adapter connected to the iBooster.             #
  #  Wire the two adapters to EACH OTHER ONLY: H-H, L-L, GND-GND.            #
  #  R120 ON at both ends (this is a 2-node bus).                            #
  ############################################################################

sniff.py has no send path and never will. This file exists solely so that a
silent bus can be diagnosed as silent rather than as broken tooling.

Usage:
    python3 selftest.py
"""
import platform
import sys
import time

import usb.core

if platform.system() == "Darwin":
    usb.core.Device.is_kernel_driver_active = lambda self, interface: False
    usb.core.Device.reset = lambda self: None

from gs_usb.gs_usb import GsUsb
from gs_usb.gs_usb_frame import GsUsbFrame
from gs_usb.constants import GS_CAN_MODE_NORMAL

BITRATE = 500000
TEST_ID = 0x7AA
PAYLOAD = [0xDE, 0xAD, 0xBE, 0xEF, 0x01, 0x02, 0x03, 0x04]


def main():
    devs = GsUsb.scan()
    print(f"Found {len(devs)} adapter(s).")
    for i, d in enumerate(devs):
        print(f"  [{i}] {d}")

    if len(devs) < 2:
        print("\nNeed both RH02s plugged in for this test.", file=sys.stderr)
        print("Wire them to each other only -- H-H, L-L, GND-GND, R120 ON at both.",
              file=sys.stderr)
        return 1

    print("\n*** Both adapters must be wired to EACH OTHER, not the booster. ***")
    print("Sending 20 frames on adapter 0, listening on adapter 1...\n")

    tx, rx = devs[0], devs[1]
    for d in (tx, rx):
        if not d.set_bitrate(BITRATE):
            print("Failed to set bitrate.", file=sys.stderr)
            return 1
    # Both in NORMAL mode: the receiver must ACK or the sender goes bus-off --
    # the same trap the booster bench will hit.
    rx.start(GS_CAN_MODE_NORMAL)
    tx.start(GS_CAN_MODE_NORMAL)

    got, frame = 0, GsUsbFrame()
    for n in range(20):
        tx.send(GsUsbFrame(can_id=TEST_ID, data=[n] + PAYLOAD[1:]))
        deadline = time.time() + 0.2
        while time.time() < deadline:
            if rx.read(frame, 50) and frame.arbitration_id == TEST_ID:
                got += 1
                break

    tx.stop()
    rx.stop()

    print(f"=== received {got}/20 frames ===\n")
    if got >= 18:
        print("PASS. The capture chain works end to end.")
        print("A silent booster bus is now a real result, not a tooling failure.")
        return 0
    if got == 0:
        print("FAIL, nothing received. Check in this order:")
        print("  1. GND joined between the two adapters -- the usual culprit")
        print("  2. H-H and L-L, not crossed")
        print("  3. R120 ON at both ends (meter should read ~60R across H/L)")
        return 1
    print("PARTIAL -- wiring works but the link is marginal.")
    print("Suspect termination or long unshielded stubs.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
