"""
GameSir Cyclone 2 - Rumble Write-Path Test (hidraw6)
====================================================
Plays an unmistakable pattern so you can confirm the controller acts on our
commands: ONE long strong buzz, pause, then TWO short buzzes.

If you feel this pattern, the vendor write path is fully confirmed and every
config command (set profile, register writes for remapping, RGB) will work.

Run with: sudo python3 gamesir_rumble_test.py  (hold the controller!)
"""

import hid
import time

VENDOR_PATH = b'/dev/hidraw6'

# The 0x0F output report is fixed-size: report ID + 63 payload bytes = 64 total.
# Short writes are silently ignored by the firmware, so always pad to 64.
REPORT_LEN = 64


def send(device, *payload):
    buf = list(payload) + [0x00] * (REPORT_LEN - len(payload))
    device.write(buf)


def rumble(device, left, right):
    send(device, 0x0F, 0x20, 0x66, 0x55, left, right)


def buzz(device, left, right, secs):
    rumble(device, left, right)
    time.sleep(secs)
    rumble(device, 0, 0)


def main():
    device = hid.device()
    try:
        device.open_path(VENDOR_PATH)
    except Exception as e:
        print(f"FAILED to open {VENDOR_PATH.decode()}: {e}")
        return

    send(device, 0x0F, 0xF2)  # heartbeat first, in case rumble needs enhanced mode
    time.sleep(0.1)

    print("Pattern: one LONG strong buzz, pause, then TWO short buzzes...")
    print("  -> long buzz (1.0s)")
    buzz(device, 0xFF, 0xFF, 1.0)
    time.sleep(0.6)
    print("  -> short buzz")
    buzz(device, 0xFF, 0xFF, 0.2)
    time.sleep(0.3)
    print("  -> short buzz")
    buzz(device, 0xFF, 0xFF, 0.2)

    rumble(device, 0, 0)  # ensure off
    device.close()
    print("Done.")


if __name__ == '__main__':
    main()
