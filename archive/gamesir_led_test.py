"""
GameSir Cyclone 2 - LED live experiment  [Xbox mode]
====================================================
Confirms the bank-0x20 LED model interactively, with you watching the LED:
  0x0000           = active effect selector (00 = off, M = preset M)
  0x0001 + M*0x7c  = 124-byte record for preset M
  record +3        = brightness (0..0x64)
  record +5..      = RGB triplet palette

It only overwrites preset M=1 for the color/brightness tests and RESTORES it
(and the original selector) at the end. Watch the LED and answer the prompts.

Usage:  sudo python3 gamesir_led_test.py
"""

import threading
import time
import hid
from gs_common import find_vendor_hidraw, pad

REC = 0x7c                      # record stride
TEST_SLOT = 1                   # preset we overwrite for the color test
TEST_ADDR = 0x0001 + TEST_SLOT * REC   # 0x007d


def rec_addr(m):
    return 0x0001 + m * REC


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


def write_reg(d, bank, addr, data):
    """Write bytes to bank/addr, chunked to fit the 64-byte report."""
    i = 0
    while i < len(data):
        chunk = data[i:i + 48]
        a = addr + i
        d.write(pad(0x0F, 0x03, bank, (a >> 8) & 0xFF, a & 0xFF,
                    len(chunk), *chunk))
        time.sleep(0.03)
        i += 48


def set_selector(d, m):
    write_reg(d, 0x20, 0x0000, [m])


def solid(d, slot, r, g, b, bright=0x64, etype=0x01):
    """Overwrite preset `slot` with a solid color and select it.
    Header is 4 bytes [type, 0x05, 0x14, brightness]; palette triplets start
    at record offset +4."""
    palette = [r, g, b] * 40            # 120 bytes -> fills the 124B record
    record = [etype, 0x05, 0x14, bright] + palette
    write_reg(d, 0x20, rec_addr(slot), record[:0x7c])
    set_selector(d, slot)


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

    # --- snapshot what we will touch, so we can restore exactly ---
    orig_sel = read_reg(d, 0x20, 0x0000, 1)
    orig_rec = read_reg(d, 0x20, TEST_ADDR, 0x7c)
    print(f"original selector = {orig_sel}")
    if orig_rec is None:
        print("Could not read preset record; aborting to stay safe.")
        alive[0] = False
        d.close()
        return

    try:
        # 1) SOLID COLOR CONFIRM (alignment fix: palette at +4) --------------
        print(f"\n=== solid color confirm (overwrites preset {TEST_SLOT}) ===")
        for name, (r, g, b) in [("RED", (255, 0, 0)),
                                ("GREEN", (0, 255, 0)),
                                ("BLUE", (0, 0, 255)),
                                ("WHITE", (255, 255, 255))]:
            solid(d, TEST_SLOT, r, g, b)
            input(f"  wrote SOLID {name}  ->  is the WHOLE LED {name}? Enter... ")

        # 2) OFF PROBE: does brightness 0 turn the LED fully off? ------------
        print("\n=== off probe ===")
        solid(d, TEST_SLOT, 255, 255, 255, bright=0x00)
        input("  brightness = 0  ->  is the LED fully OFF? Enter... ")

    finally:
        # --- restore exactly what we changed ---
        print("\nRestoring your original preset + selector...")
        write_reg(d, 0x20, TEST_ADDR, orig_rec)
        if orig_sel is not None:
            set_selector(d, orig_sel[0])
        time.sleep(0.3)
        alive[0] = False
        time.sleep(0.2)
        d.close()
        print("Done.")


if __name__ == '__main__':
    main()
