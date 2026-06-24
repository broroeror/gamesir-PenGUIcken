"""
GameSir Cyclone 2 - Command Channel Test #2: SUSTAINED heartbeat
================================================================
Finding so far: the 0x12 enhanced input stream is ALWAYS on, and single
commands (get-profile, rumble) get no response. Hypothesis: the command
channel only activates under a *continuous* heartbeat (handoff says "heartbeat
every second to activate enhanced mode"). Previous tests only sent one.

This script runs a heartbeat thread, warms up for 2s, THEN:
  - sends get-profile and watches for a 0x10 reply (proves commands processed)
  - plays a clear rumble pattern (hold the controller to feel it)

Run with: sudo python3 gamesir_cmd_test2.py   (hold the controller!)
"""

import hid
import threading
import time
from gs_common import find_vendor_hidraw, pad

_running = True


def heartbeat_loop(device):
    while _running:
        try:
            device.write(pad(0x0F, 0xF2))
        except Exception:
            return
        time.sleep(0.5)


def watch_for(device, report_id, secs):
    t0 = time.time()
    while time.time() - t0 < secs:
        data = device.read(64, timeout_ms=100)
        if data and data[0] == report_id:
            return data
    return None


def main():
    global _running
    devnode, name, hid_name = find_vendor_hidraw()
    if not devnode:
        print("Could not find GameSir vendor interface. Is it connected / in Xbox mode?")
        return
    print(f"Found vendor interface: {devnode} ({hid_name})")
    device = hid.device()
    try:
        device.open_path(devnode.encode())
    except Exception as e:
        print(f"FAILED to open {devnode}: {e}")
        return
    device.set_nonblocking(True)

    hb = threading.Thread(target=heartbeat_loop, args=(device,), daemon=True)
    hb.start()
    print("Sustained heartbeat running. Warming up 2s...")
    time.sleep(2.0)

    # --- get-profile read-back ---
    print("Sending get-profile, watching 1.5s for a 0x10 reply...")
    device.write(pad(0x0F, 0x0B))
    reply = watch_for(device, 0x10, 1.5)
    if reply:
        print(f"  >>> 0x10 REPLY: {bytes(reply[:6]).hex(' ')}  (profile = {reply[2]})")
        print("  COMMAND CHANNEL WORKS under sustained heartbeat!")
    else:
        print("  No 0x10 reply.")

    # --- rumble feel test ---
    print("Rumble: long buzz, pause, two short buzzes (hold the controller)...")
    device.write(pad(0x0F, 0x20, 0x66, 0x55, 0xFF, 0xFF)); time.sleep(1.0)
    device.write(pad(0x0F, 0x20, 0x66, 0x55, 0x00, 0x00)); time.sleep(0.6)
    device.write(pad(0x0F, 0x20, 0x66, 0x55, 0xFF, 0xFF)); time.sleep(0.2)
    device.write(pad(0x0F, 0x20, 0x66, 0x55, 0x00, 0x00)); time.sleep(0.3)
    device.write(pad(0x0F, 0x20, 0x66, 0x55, 0xFF, 0xFF)); time.sleep(0.2)
    device.write(pad(0x0F, 0x20, 0x66, 0x55, 0x00, 0x00))

    _running = False
    time.sleep(0.2)
    device.close()
    print("Done.")


if __name__ == '__main__':
    main()
