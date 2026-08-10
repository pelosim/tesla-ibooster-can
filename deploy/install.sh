#!/bin/bash
# Install persistent CAN naming + boot bring-up on the HVAC Pi. Run on the Pi.
set -e
cd "$(dirname "$0")"
sudo install -m 644 70-ibooster-can.rules /etc/udev/rules.d/70-ibooster-can.rules
sudo install -m 755 ibooster-can-up       /usr/local/sbin/ibooster-can-up
sudo install -m 644 ibooster-can.service  /etc/systemd/system/ibooster-can.service
sudo udevadm control --reload-rules
sudo systemctl daemon-reload
sudo systemctl enable --now ibooster-can.service
echo
echo "Renaming needs the adapters to re-appear to udev. Either replug them, or:"
echo "  sudo modprobe -r gs_usb && sudo modprobe gs_usb"
echo "Then: ip -br link show type can"
