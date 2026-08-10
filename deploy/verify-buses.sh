#!/bin/bash
# Confirm can-veh / can-yaw actually carry the buses their names claim.
#
# The udev names follow the ADAPTER, not the wire. Moving a CAN lead between
# adapters silently makes them wrong. This checks by content instead, which is the
# only thing that cannot be fooled: whichever bus carries 0x39D is the vehicle bus.
#
# Run after any rewiring, and after any reboot you want to trust.
set -u
FAIL=0
check() {
    local iface=$1 want=$2 label=$3
    if [ ! -e "/sys/class/net/$iface" ]; then
        echo "  $iface: MISSING — adapter unplugged, or udev rule did not apply"
        FAIL=1; return
    fi
    if ! ip link show "$iface" | grep -q "UP"; then
        echo "  $iface: DOWN — run 'sudo systemctl restart ibooster-can'"
        FAIL=1; return
    fi
    local n
    n=$(timeout 5 candump -n 250 "$iface" 2>/dev/null | awk '{print $2}' | grep -c "^$want$" || true)
    if [ "${n:-0}" -gt 0 ]; then
        echo "  $iface: OK — carries $want ($label)"
    else
        echo "  $iface: WRONG — no $want seen. Names are swapped, or the booster is off."
        FAIL=1
    fi
}
echo "Verifying CAN bus naming by content:"
check can-veh 39D "vehicle bus"
check can-yaw 38E "YAW bus"
echo
if [ $FAIL -eq 0 ]; then
    echo "Both correct."
else
    echo "Something is off. Do NOT trust captures until this passes —"
    echo "a swapped name mislabels every frame and nothing else will warn you."
fi
exit $FAIL
