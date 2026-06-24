"""
GameSir Cyclone 2 - Vendor Interface Probe (hidraw6)
====================================================
One-off diagnostic: proves whether we can talk to the GameSir vendor interface,
which gates ALL customization (remap, deadzones, trigger curves, RGB, profiles).

Tests, with safe/reversible commands only:
  - READ  path: Get Profile (0x0F 0x0B) -> expect reply report 0x10 0x0C <profile>
  - WRITE path: Rumble (0x0F 0x20 0x66 0x55 L R) -> controller physically buzzes

Command framing is ambiguous between two sources, so we try both:
  A) report-id framing:  [0x0F, cmd, ...]          (per reverse-eng gist)
  B) no-report-id framing:[0x00, 0x0F, cmd, ...]   (per handoff doc)

Run with: sudo python3 gamesir_vendor_probe.py
"""

import hid
import time

VENDOR_PATH = b'/dev/hidraw6'


def drain(device, ms, tag):
    """Read for `ms` milliseconds, print any non-zero report, return list of reports."""
    reports = []
    deadline = time.time() + ms / 1000
    while time.time() < deadline:
        data = device.read(64, timeout_ms=100)
        if data and any(b != 0 for b in data):
            reports.append(data)
            print(f"    [{tag}] <- {bytes(data[:8]).hex(' ')} ...")
    return reports


def send(device, payload, tag):
    """Write a payload, return True on apparent success."""
    try:
        n = device.write(payload)
        print(f"  [{tag}] -> {bytes(payload).hex(' ')}  (write returned {n})")
        return n is not None and n > 0
    except Exception as e:
        print(f"  [{tag}] -> write FAILED: {e}")
        return False


def main():
    device = hid.device()
    try:
        device.open_path(VENDOR_PATH)
    except Exception as e:
        print(f"FAILED to open {VENDOR_PATH.decode()}: {e}")
        print("If this is a permissions error, the udev rule (vendor 3537, not 3577!) "
              "would fix it; otherwise the interface may be claimed.")
        return

    device.set_nonblocking(True)
    print(f"Opened {VENDOR_PATH.decode()}")
    try:
        print(f"  Manufacturer: {device.get_manufacturer_string()}")
        print(f"  Product:      {device.get_product_string()}")
    except Exception as e:
        print(f"  (could not read strings: {e})")

    framings = {
        'A: [0x0F,...]':        lambda *b: [0x0F, *b],
        'B: [0x00,0x0F,...]':   lambda *b: [0x00, 0x0F, *b],
    }

    working = None

    # ---- READ test: Get Profile, in each framing ----
    print("\n=== READ TEST: Get Profile ===")
    for name, frame in framings.items():
        print(f"\n  Framing {name}")
        send(device, frame(0xF2), 'heartbeat')          # wake / enable enhanced mode
        time.sleep(0.05)
        send(device, frame(0x0B), 'get-profile')
        replies = drain(device, 500, 'reply')
        got = any(r[0] == 0x10 or 0x0C in r[:4] for r in replies)
        if got:
            print(f"  >>> Framing {name} got a profile-shaped reply!")
            working = frame
            break
        elif replies:
            print(f"  >>> Framing {name} got data, but not the expected 0x10/0x0C shape.")

    if working is None:
        print("\nNo clear get-profile reply. The write path test below still tells us "
              "if the device accepts output reports at all.")
        working = framings['A: [0x0F,...]']  # default for rumble attempt

    # ---- WRITE test: gentle rumble pulse, then stop ----
    print("\n=== WRITE TEST: Rumble (you should feel a short buzz) ===")
    send(device, working(0xF2), 'heartbeat')
    time.sleep(0.05)
    send(device, working(0x20, 0x66, 0x55, 0x80, 0x80), 'rumble-on')
    time.sleep(0.5)
    send(device, working(0x20, 0x66, 0x55, 0x00, 0x00), 'rumble-off')

    device.close()
    print("\nDone. Closed device.")


if __name__ == '__main__':
    main()
