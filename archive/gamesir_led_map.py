"""
GameSir Cyclone 2 - frame-position map  [Xbox mode]
===================================================
Writes ONE 5-triplet frame of distinct colors, tiled across the record (so the
tail is filled -> no dark-LED bug, and identical frames -> no animation). Each
physical light then shows its frame-position color, giving an unambiguous
position -> light map.

Frame positions:  0=red  1=green  2=blue  3=yellow  4=magenta

Tell me which color each physical light shows. Restores your preset on exit.

Usage:  sudo python3 gamesir_led_map.py
"""

import threading
import time
import hid
from gs_common import find_vendor_hidraw, pad

REC = 0x7c
SLOT = 1
ADDR = 0x0001 + SLOT * REC

FRAME = [
    ("red",     (255, 0, 0)),
    ("green",   (0, 255, 0)),
    ("blue",    (0, 0, 255)),
    ("yellow",  (255, 255, 0)),
    ("magenta", (255, 0, 255)),
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


def read_reg(d, bank, addr, length, tries=4):
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
                    and data[2] == bank
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
        print("Could not read preset; aborting.")
        alive[0] = False
        d.close()
        return

    try:
        frame = []
        for _name, (r, g, b) in FRAME:
            frame += [r, g, b]
        palette = (frame * (40 // len(FRAME) + 1))[:40 * 3]
        record = ([0x01, 0x05, 0x14, 0x64] + palette)[:REC]
        write_reg(d, 0x20, ADDR, record)
        write_reg(d, 0x20, 0x0000, [SLOT])

        print("Frame colors written. Each physical light shows ONE of:")
        for i, (name, _rgb) in enumerate(FRAME):
            print(f"  position {i} = {name}")
        print("\nTell me the color of each light:")
        print("  Left grip = ?   Right grip = ?   Profile = ?   Home = ?")
        input("\nPress Enter to restore... ")
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
