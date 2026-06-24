"""
GameSir Cyclone 2 - Guided Button Capture (0x12 enhanced report, Xbox mode)
==========================================================================
Maps the buttons the standard report can't see, robustly, despite the very
noisy always-on IMU bytes.

Method: you hold ONE button at a time when prompted. A byte is reported as that
button only if it is STEADY while held AND steady at rest, with a DIFFERENT
value between the two. The gyro/accel bytes are never steady, so they are
automatically ignored -- no fragile noise threshold needed.

Run in XInput/Xbox mode (hold green ~2s):
  sudo python3 gamesir_capture_buttons.py
"""

import hid
import threading
import time
from collections import Counter
from gs_common import find_vendor_hidraw, pad

TARGETS = ["L4", "R4", "M (logo)", "Home", "Share/Capture", "Profile",
           "A (anchor)", "RB (anchor)"]
STEADY_FRAC = 0.85   # a byte counts as "steady" if its top value covers >=85% of frames
_running = True


def heartbeat_loop(device):
    while _running:
        try:
            device.write(pad(0x0F, 0xF2))
        except Exception:
            return
        time.sleep(0.5)


def flush(device):
    """Drop buffered/stale frames."""
    t0 = time.time()
    while time.time() - t0 < 0.15:
        device.read(64, timeout_ms=10)


def capture(device, secs):
    """Collect 0x12 frames for `secs`; return list of 64-int frames."""
    frames = []
    t0 = time.time()
    while time.time() - t0 < secs:
        try:
            data = device.read(64, timeout_ms=50)
        except OSError:
            continue
        if data and data[0] == 0x12:
            frames.append(data)
    return frames


def steady(frames, i):
    """Return (value, fraction) of the most common value of byte i across frames."""
    vals = Counter(f[i] for f in frames)
    val, n = vals.most_common(1)[0]
    return val, n / len(frames)


def main():
    global _running
    devnode, name, hid_name = find_vendor_hidraw()
    if not devnode:
        print("Could not find GameSir vendor interface. In XInput/Xbox mode (green)?")
        return
    print(f"Found vendor interface: {devnode} ({hid_name})")
    device = hid.device()
    try:
        device.open_path(devnode.encode())
    except Exception as e:
        print(f"FAILED to open {devnode}: {e}")
        return
    device.set_nonblocking(True)

    threading.Thread(target=heartbeat_loop, args=(device,), daemon=True).start()

    # wait for stream
    t0 = time.time()
    while time.time() - t0 < 2.0:
        d = device.read(64, timeout_ms=100)
        if d and d[0] == 0x12:
            break
    else:
        print("No 0x12 stream seen. Is the controller in Xbox mode and awake?")
        _running = False
        device.close()
        return

    # rest baseline
    input("\nSet the controller DOWN and don't touch it, then press Enter...")
    flush(device)
    rest = capture(device, 1.5)
    rest_steady = {i: steady(rest, i) for i in range(64)}
    # candidate bytes: steady at rest (excludes IMU)
    candidates = [i for i in range(64) if rest_steady[i][1] >= STEADY_FRAC]
    print(f"Rest captured. {len(candidates)} steady byte(s) to watch.\n")

    results = {}
    for label in TARGETS:
        input(f"Press and HOLD [{label}] firmly, then press Enter (keep holding)...")
        flush(device)
        held = capture(device, 1.0)
        if not held:
            print("  (no frames captured, skipping)\n")
            continue
        hits = []
        for i in candidates:
            hval, hfrac = steady(held, i)
            rval, _ = rest_steady[i]
            if hfrac >= STEADY_FRAC and hval != rval:
                hits.append((i, rval, hval))
        if hits:
            desc = ", ".join(
                f"byte[{i}] {rv:#04x}->{hv:#04x} (bits {rv:08b}->{hv:08b})"
                for i, rv, hv in hits)
            print(f"  {label}: {desc}\n")
            results[label] = hits
        else:
            print(f"  {label}: no steady change detected (try pressing more firmly)\n")

    _running = False
    time.sleep(0.2)
    device.close()

    print("\n===== SUMMARY =====")
    for label in TARGETS:
        if label in results:
            for i, rv, hv in results[label]:
                changed = rv ^ hv
                print(f"{label:16s} byte[{i}]  value {rv:#04x}->{hv:#04x}  changed bits {changed:08b}")
        else:
            print(f"{label:16s} (unmapped)")


if __name__ == '__main__':
    main()
