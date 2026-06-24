"""
GameSir Cyclone 2 - Mode-Agnostic Vendor Probe
==============================================
Auto-finds the GameSir vendor HID interface (VID 0x3537) regardless of which
platform mode the controller is in, then runs every test in one pass:

  PHASE A: sustained heartbeat, then dump 0x12 reports that change (press
           L4/R4/M/A/LB, move sticks) -> does enhanced input populate?
  PHASE B: get-profile, watch for a 0x10 reply -> does the command channel
           respond?
  PHASE C: rumble pattern -> does the write path act? (hold the controller)

Use this to compare PS4 mode vs XInput/Xbox mode (hold green button ~2s).

Run with: sudo python3 gamesir_probe_auto.py
"""

import glob
import os
import threading
import time
import hid

VENDOR_VID = 0x3537   # GameSir native vendor interface
REPORT_LEN = 64
_running = True


def find_vendor_hidraw():
    """Return (devnode, hidraw_name) for the GameSir vendor interface, or (None, None)."""
    for path in sorted(glob.glob('/sys/class/hidraw/hidraw*')):
        name = os.path.basename(path)
        try:
            with open(os.path.join(path, 'device', 'uevent')) as f:
                uevent = f.read()
        except OSError:
            continue
        hid_id = ''
        hid_name = ''
        for line in uevent.splitlines():
            if line.startswith('HID_ID='):
                hid_id = line.split('=', 1)[1]
            elif line.startswith('HID_NAME='):
                hid_name = line.split('=', 1)[1]
        # HID_ID looks like 0003:00003537:00000575
        parts = hid_id.split(':')
        if len(parts) == 3:
            try:
                vid = int(parts[1], 16)
            except ValueError:
                vid = 0
            if vid == VENDOR_VID:
                return f'/dev/{name}', name, hid_name
    return None, None, None


def pad(*payload):
    return list(payload) + [0x00] * (REPORT_LEN - len(payload))


def heartbeat_loop(device):
    while _running:
        try:
            device.write(pad(0x0F, 0xF2))
        except Exception:
            return
        time.sleep(0.5)


def main():
    global _running
    devnode, name, hid_name = find_vendor_hidraw()
    if not devnode:
        print(f"Could not find GameSir vendor interface (VID {VENDOR_VID:#06x}).")
        print("Is the controller connected? In some modes the VID may differ -- "
              "run the hidraw scan and tell me what GameSir nodes appear.")
        return
    print(f"Found vendor interface: {devnode} ({name}) - {hid_name}")

    device = hid.device()
    try:
        device.open_path(devnode.encode())
    except Exception as e:
        print(f"FAILED to open {devnode}: {e}")
        return
    device.set_nonblocking(True)

    hb = threading.Thread(target=heartbeat_loop, args=(device,), daemon=True)
    hb.start()
    print("Sustained heartbeat running.\n")

    # PHASE A: does 0x12 populate?
    print("PHASE A (4s): press L4, R4, M, A, LB and move sticks NOW...")
    prev = None
    t0 = time.time()
    changes = 0
    while time.time() - t0 < 4.0:
        try:
            data = device.read(64, timeout_ms=100)
        except OSError:
            continue
        if not data or data[0] != 0x12:
            continue
        body = tuple(data)
        if body != prev:
            prev = body
            nz = [(i, data[i]) for i in range(1, len(data)) if data[i] != 0]
            print(f"  0x12 changed -> non-zero: {nz}")
            changes += 1
    print(f"  ({changes} distinct 0x12 states seen)\n")

    # PHASE B: command reply?
    print("PHASE B: get-profile, watching 1.5s for 0x10 reply...")
    device.write(pad(0x0F, 0x0B))
    reply = None
    t0 = time.time()
    while time.time() - t0 < 1.5:
        try:
            data = device.read(64, timeout_ms=100)
        except OSError:
            continue
        if data and data[0] == 0x10:
            reply = data
            break
    if reply:
        print(f"  >>> 0x10 REPLY: {bytes(reply[:6]).hex(' ')} (profile = {reply[2]})\n")
    else:
        print("  no 0x10 reply\n")

    # PHASE C: rumble
    print("PHASE C: rumble (hold the controller) - long, then two short...")
    device.write(pad(0x0F, 0x20, 0x66, 0x55, 0xFF, 0xFF)); time.sleep(1.0)
    device.write(pad(0x0F, 0x20, 0x66, 0x55, 0x00, 0x00)); time.sleep(0.5)
    device.write(pad(0x0F, 0x20, 0x66, 0x55, 0xFF, 0xFF)); time.sleep(0.2)
    device.write(pad(0x0F, 0x20, 0x66, 0x55, 0x00, 0x00)); time.sleep(0.3)
    device.write(pad(0x0F, 0x20, 0x66, 0x55, 0xFF, 0xFF)); time.sleep(0.2)
    device.write(pad(0x0F, 0x20, 0x66, 0x55, 0x00, 0x00))

    _running = False
    time.sleep(0.2)
    device.close()
    print("\nDone. Summary: enhanced input "
          f"{'POPULATED' if changes else 'stayed empty'}; "
          f"command reply {'YES' if reply else 'no'}.")


if __name__ == '__main__':
    main()
