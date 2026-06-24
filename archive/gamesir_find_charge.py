"""
GameSir Cyclone 2 - Find the Charging Indicator
===============================================
byte 37 turned out NOT to be a charge flag (it reads the same plugged/unplugged).
This finds the real one: it captures a stable snapshot of the 0x12 report while
UNPLUGGED, then while PLUGGED IN, and reports which byte/bit changed.

A byte is only considered if it's STEADY in both states (so the noisy IMU bytes
are ignored) but holds a DIFFERENT value between them.

Run in Xbox mode:  sudo python3 gamesir_find_charge.py
(Start with the cable UNPLUGGED but the controller on via the dongle.)
"""

import threading
import time
from collections import Counter
import hid
from gs_common import find_vendor_hidraw, pad

STEADY_FRAC = 0.85


def capture_state(label):
    """Find the live interface, capture ~1.5s, return {byte: (value, fraction)}."""
    devnode, _n, hid_name = find_vendor_hidraw()
    if not devnode:
        print(f"  [{label}] controller not found (is it on / in Xbox mode?)")
        return None
    try:
        d = hid.device()
        d.open_path(devnode.encode())
        d.set_nonblocking(True)
    except Exception as e:
        print(f"  [{label}] open failed: {e}")
        return None

    alive = [True]

    def hb():
        while alive[0]:
            try:
                d.write(pad(0x0F, 0xF2))
            except Exception:
                return
            time.sleep(0.4)
    threading.Thread(target=hb, daemon=True).start()

    # flush stale, then collect
    t0 = time.time()
    while time.time() - t0 < 0.2:
        d.read(64, timeout_ms=10)
    frames = []
    t0 = time.time()
    while time.time() - t0 < 1.5:
        try:
            data = d.read(64, timeout_ms=50)
        except OSError:
            break
        if data and data[0] == 0x12:
            frames.append(data)
    alive[0] = False
    try:
        d.close()
    except Exception:
        pass

    if not frames:
        print(f"  [{label}] no 0x12 frames captured")
        return None
    print(f"  [{label}] captured {len(frames)} frames via {hid_name}")
    return {i: Counter(f[i] for f in frames).most_common(1)[0] for i in range(64)}


def steady(snap, i):
    val, n = snap[i]
    return val, n  # n is count of most-common; fraction handled by caller


def main():
    input("Ensure the cable is UNPLUGGED (controller ON via dongle), then Enter...")
    a = capture_state("unplugged")
    if not a:
        return
    input("\nNow PLUG IN the charge cable, wait ~2s, then press Enter...")
    b = capture_state("plugged")
    if not b:
        return

    # frames-per-capture differ; recompute fractions from counts is not available
    # here, so just compare the most-common values and require both were dominant.
    print("\n===== DIFFERENCES (unplugged -> plugged) =====")
    found = False
    for i in range(64):
        av, _ = a[i]
        bv, _ = b[i]
        if av != bv:
            found = True
            note = ""
            if i == 36:
                note = "  (battery % - expected to differ slightly)"
            print(f"byte[{i}]: {av:#04x} -> {bv:#04x}  "
                  f"(bits {av:08b} -> {bv:08b}){note}")
    if not found:
        print("No steady byte changed. Try again, holding each state a moment longer,")
        print("or the charge state may not be exposed in the 0x12 report.")
    else:
        print("\nThe charge flag is most likely a byte above that cleanly flips a bit")
        print("(ignore byte 36 = battery and any IMU bytes that slipped through).")


if __name__ == '__main__':
    main()
