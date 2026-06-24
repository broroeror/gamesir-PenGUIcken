"""
GameSir Cyclone 2 - Enhanced Report (0x12) Button Mapper
========================================================
Maps the buttons the standard PS4 report can't see (L4, R4, M, and possibly
Home / Share / Profile) by reading the enhanced 0x12 report from the vendor
interface (hidraw6), which only streams after a heartbeat.

The 0x12 report contains noisy IMU/sensor bytes that change constantly, so we
can't just diff raw reports. Instead:
  PHASE 1 (calibrate): hold the controller still for ~2s; we record each byte's
           min/max to learn which bytes are "noisy" (IMU) and which are stable.
  PHASE 2 (capture): we ignore noisy bytes and only report stable bytes that
           change from their resting value -- i.e. actual button presses.

Press ONE input at a time and watch which byte index lights up.

Run with: sudo python3 gamesir_map_buttons.py
"""

import hid
import threading
import time
from gs_common import find_vendor_hidraw, pad

CALIBRATE_SECS = 3.0   # longer = better change-frequency stats

_running = True


def heartbeat_loop(device):
    """Keep enhanced mode alive (heartbeat required ~every second)."""
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

    device.write(pad(0x0F, 0xF2))  # kick enhanced mode on
    hb = threading.Thread(target=heartbeat_loop, args=(device,), daemon=True)
    hb.start()

    # Wait for the 0x12 stream to actually start.
    print("Waiting for enhanced (0x12) stream...")
    t0 = time.time()
    while time.time() - t0 < 2.0:
        data = device.read(64, timeout_ms=200)
        if data and data[0] == 0x12:
            break
    else:
        print("Never saw a 0x12 report. Is the controller awake / in range?")
        _running = False
        device.close()
        return

    # ---- PHASE 1: calibrate rest baseline ----
    # Detect noise by CHANGE FREQUENCY, not range: gyro/accel bytes change almost
    # every frame (and drift slowly, defeating a range threshold), while button
    # bytes never change until pressed. Mark bytes that change in >10% of frames.
    print(f"\nCALIBRATING - hold the controller STILL for {CALIBRATE_SECS:.0f}s "
          "(don't touch any buttons)...")
    change_counts = [0] * 64
    frames = 0
    baseline = None
    prev = None
    t0 = time.time()
    while time.time() - t0 < CALIBRATE_SECS:
        data = device.read(64, timeout_ms=100)
        if not data or data[0] != 0x12:
            continue
        baseline = list(data)
        if prev is not None:
            for i in range(64):
                if data[i] != prev[i]:
                    change_counts[i] += 1
            frames += 1
        prev = list(data)

    if baseline is None or frames == 0:
        print("No 0x12 data captured during calibration.")
        _running = False
        device.close()
        return

    noisy = {i for i in range(64) if change_counts[i] / frames > 0.10}
    stable = [i for i in range(64) if i not in noisy]
    print(f"Done. Ignoring {len(noisy)} noisy (analog/IMU) byte(s): {sorted(noisy)}")
    print(f"Watching {len(stable)} button-candidate byte(s): {stable}")

    # ---- PHASE 2: capture button presses ----
    print("\nNow press inputs ONE AT A TIME: L4, R4, M, Home, Share, Profile,")
    print("plus a few known ones (A, LB, Menu) to anchor the layout. Ctrl+C to stop.\n")
    last = dict(baseline=baseline)
    try:
        while True:
            data = device.read(64, timeout_ms=200)
            if not data or data[0] != 0x12:
                continue
            changes = []
            for i in stable:
                if data[i] != baseline[i]:
                    changes.append(f"byte[{i}]: {baseline[i]:#04x} -> {data[i]:#04x} "
                                   f"({baseline[i]:08b}->{data[i]:08b})")
            sig = tuple((i, data[i]) for i in stable if data[i] != baseline[i])
            if changes and sig != last.get('sig'):
                last['sig'] = sig
                print(" | ".join(changes))
    except KeyboardInterrupt:
        pass
    finally:
        _running = False
        device.close()
        print("\nStopped. Closed device.")


if __name__ == '__main__':
    main()
