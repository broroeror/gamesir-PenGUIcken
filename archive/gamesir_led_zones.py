"""
GameSir Cyclone 2 - LED zone discovery  [Xbox mode]
===================================================
Writes a DISTINCT color to each palette triplet index in a preset record, so we
can learn (a) how many individually-addressable lights exist and (b) which
triplet index maps to which physical LED. Watch the controller and describe what
you see; it restores your original preset on exit.

Palette lives at record offset +4 as consecutive RGB triplets:
    record = [type, 05, 14, brightness] + [r,g,b](index 0) + [r,g,b](index 1) ...

Usage:  sudo python3 gamesir_led_zones.py
"""

import threading
import time
import hid
from gs_common import find_vendor_hidraw, pad

REC = 0x7c
SLOT = 1
ADDR = 0x0001 + SLOT * REC

# Distinct, nameable colors per index. Index = position in this list.
LEGEND = [
    ("red",        (255, 0, 0)),
    ("green",      (0, 255, 0)),
    ("blue",       (0, 0, 255)),
    ("yellow",     (255, 255, 0)),
    ("cyan",       (0, 255, 255)),
    ("magenta",    (255, 0, 255)),
    ("white",      (255, 255, 255)),
    ("orange",     (255, 60, 0)),
    ("chartreuse", (128, 255, 0)),
    ("azure",      (0, 128, 255)),
    ("rose",       (255, 0, 128)),
    ("violet",     (128, 0, 255)),
    ("teal",       (0, 255, 128)),
    ("amber",      (255, 160, 0)),
    ("pink",       (255, 128, 255)),
    ("lime",       (180, 255, 60)),
]


def write_reg(d, bank, addr, data):
    i = 0
    while i < len(data):
        chunk = data[i:i + 48]
        a = addr + i
        d.write(pad(0x0F, 0x03, bank, (a >> 8) & 0xFF, a & 0xFF,
                    len(chunk), *chunk))
        time.sleep(0.03)
        i += 48


def read_reg(d, bank, addr, length, tries=3):
    for _ in range(tries):
        t0 = time.time()
        while time.time() - t0 < 0.05:
            d.read(64, timeout_ms=5)
        d.write(pad(0x0F, 0x04, bank, (addr >> 8) & 0xFF, addr & 0xFF, length))
        t0 = time.time()
        while time.time() - t0 < 0.4:
            try:
                data = d.read(64, timeout_ms=50)
            except OSError:
                break
            if (data and data[0] == 0x10 and data[1] == 0x05
                    and data[3] == ((addr >> 8) & 0xFF)
                    and data[4] == (addr & 0xFF)):
                return list(data[6:6 + length])
    return None


def main():
    devnode, _n, hid_name = find_vendor_hidraw()
    if not devnode:
        print("Vendor interface not found (Xbox/green mode + connected?).")
        return
    print(f"Found {devnode} ({hid_name})\n")
    d = hid.device()
    d.open_path(devnode.encode())
    d.set_nonblocking(True)

    alive = [True]

    def hb():
        while alive[0]:
            try:
                d.write(pad(0x0F, 0xF2))
            except Exception:
                return
            time.sleep(0.4)
    threading.Thread(target=hb, daemon=True).start()
    time.sleep(1.0)

    orig_sel = read_reg(d, 0x20, 0x0000, 1)
    orig_rec = read_reg(d, 0x20, ADDR, REC)
    if orig_rec is None:
        print("Could not read preset record; aborting.")
        alive[0] = False
        d.close()
        return

    # Build a record where each triplet index gets its distinct color.
    palette = []
    for _name, (r, g, b) in LEGEND:
        palette += [r, g, b]
    record = ([0x01, 0x05, 0x14, 0x64] + palette)[:REC]

    try:
        write_reg(d, 0x20, ADDR, record)
        write_reg(d, 0x20, 0x0000, [SLOT])
        print("Index -> color legend (each light should show ONE of these):")
        for i, (name, _rgb) in enumerate(LEGEND):
            print(f"  index {i:2d} = {name}")
        print("\nLook at the controller. Tell me:")
        print("  - how many lights are lit, and")
        print("  - reading them in a consistent spatial order (e.g. clockwise "
              "around each stick), what color is each?")
        input("\nPress Enter when done to restore your original preset... ")
    finally:
        print("Restoring original preset + selector...")
        write_reg(d, 0x20, ADDR, orig_rec)
        if orig_sel is not None:
            write_reg(d, 0x20, 0x0000, [orig_sel[0]])
        time.sleep(0.3)
        alive[0] = False
        time.sleep(0.2)
        d.close()
        print("Done.")


if __name__ == '__main__':
    main()
