"""
GameSir Cyclone 2 - Command Channel Diagnostic (hidraw6)
========================================================
Figures out, definitively, whether the device processes our output commands.

Uses Get Profile as the test: its reply arrives on report ID 0x10 (a separate
input report per the HID descriptor), so receiving 0x10 0x0C <profile> PROVES
the command was understood -- unlike rumble, whose magic bytes are uncertain.

It also answers two open questions:
  - Does the 0x12 enhanced stream require a heartbeat, or is it always on?
  - Does the command need to be padded to the full 64-byte report length?

Run with: sudo python3 gamesir_cmd_test.py
"""

import hid
import time
from collections import Counter

VENDOR_PATH = b'/dev/hidraw6'
REPORT_LEN = 64


def pad(*payload):
    return list(payload) + [0x00] * (REPORT_LEN - len(payload))


def listen(device, secs, label):
    """Read for `secs`; return Counter of report IDs and the first 0x10 report."""
    ids = Counter()
    first_10 = None
    t0 = time.time()
    while time.time() - t0 < secs:
        data = device.read(64, timeout_ms=100)
        if not data:
            continue
        ids[data[0]] += 1
        if data[0] == 0x10 and first_10 is None:
            first_10 = data
    pretty = {hex(k): v for k, v in ids.items()}
    print(f"  [{label}] report IDs seen: {pretty}")
    return ids, first_10


def main():
    device = hid.device()
    try:
        device.open_path(VENDOR_PATH)
    except Exception as e:
        print(f"FAILED to open {VENDOR_PATH.decode()}: {e}")
        return
    device.set_nonblocking(True)

    # 1. Baseline: what streams with NO command sent?
    print("1. Listening 1.2s with NO write at all...")
    listen(device, 1.2, "baseline")

    # 2. Heartbeat (padded), then listen.
    print("2. Sending PADDED heartbeat [0x0F 0xF2 ...64], then listening...")
    n = device.write(pad(0x0F, 0xF2))
    print(f"   write() returned {n}")
    listen(device, 1.0, "after-heartbeat")

    # 3. Get-profile PADDED, watch for 0x10 reply.
    print("3. Sending PADDED get-profile [0x0F 0x0B ...64]...")
    n = device.write(pad(0x0F, 0x0B))
    print(f"   write() returned {n}")
    _, reply = listen(device, 1.2, "after-getprofile-padded")
    if reply:
        print(f"   >>> GOT 0x10 REPLY: {bytes(reply[:6]).hex(' ')}  "
              f"(profile byte = {reply[2]})")
        device.close()
        print("\nCommand channel WORKS. Padding required = yes.")
        return

    # 4. Get-profile UNPADDED, watch for 0x10 reply.
    print("4. No padded reply. Trying UNPADDED get-profile [0x0F 0x0B]...")
    try:
        n = device.write([0x0F, 0x0B])
        print(f"   write() returned {n}")
    except Exception as e:
        print(f"   unpadded write failed: {e}")
    _, reply = listen(device, 1.2, "after-getprofile-unpadded")
    if reply:
        print(f"   >>> GOT 0x10 REPLY: {bytes(reply[:6]).hex(' ')}  "
              f"(profile byte = {reply[2]})")
        print("\nCommand channel WORKS. Padding required = no.")
    else:
        print("\nNo 0x10 reply either way. The command channel / report ID needs"
              " more investigation (maybe the 0x41 output report, or a feature report).")

    device.close()


if __name__ == '__main__':
    main()
