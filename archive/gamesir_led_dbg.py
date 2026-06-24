"""
GameSir Cyclone 2 - profile-LED solid-color debug  [Xbox mode]
==============================================================
Writes a SOLID white to a slot exactly the way the GUI does, then reads the
record back and prints every triplet, so we can see whether index 2 (the
Profile selector LED) actually stored the color or not.

  - If index 2 reads white but the LED is dark  -> firmware overrides that LED
  - If index 2 reads black/wrong                -> our write is the problem

Restores the original preset on exit.

Usage:  sudo python3 gamesir_led_dbg.py
"""

import threading
import time
import hid
from gs_common import find_vendor_hidraw, pad

REC = 0x7c
SLOT = 1
ADDR = 0x0001 + SLOT * REC


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


LIGHTS = ['Left grip', 'Right grip', 'Profile', 'Home']


def show_record(rec):
    print(f"  header (offset 0..3): {' '.join(f'{x:02x}' for x in rec[:4])}")
    for idx in range(6):
        off = 4 + idx * 3
        trip = rec[off:off + 3]
        name = LIGHTS[idx] if idx < len(LIGHTS) else ''
        print(f"  index {idx}  (rec+{off:2d}): "
              f"{' '.join(f'{x:02x}' for x in trip)}   {name}")


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
        # exactly what the GUI does for solid white on all 4 lights
        record = ([0x01, 0x05, 0x14, 0x64] + [255, 255, 255] * 40)[:REC]
        write_reg(d, 0x20, ADDR, record)
        write_reg(d, 0x20, 0x0000, [SLOT])
        time.sleep(0.2)

        print("Wrote SOLID WHITE to slot", SLOT, "- reading it back:\n")
        back = read_reg(d, 0x20, ADDR, REC)
        if back is None:
            print("  (readback failed)")
        else:
            show_record(back)
        input("\nLook at the controller: is the Profile LED dark or white? "
              "Press Enter to restore... ")
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
