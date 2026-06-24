"""
GameSir Cyclone 2 - Register Read probe  [Xbox mode]
====================================================
Foundation for RGB / remap / deadzone work: all of that is stored in registers,
read via Read Register (0x0F 0x04 profile addrHi addrLo len) and written via
Write Register (0x0F 0x03 ...). This is READ-ONLY (safe) and just learns the
reply format: it fires a few reads and prints every reply report it sees.

Run in Xbox mode:  sudo python3 gamesir_regread.py
"""

import threading
import time
import hid
from gs_common import find_vendor_hidraw, pad

PROFILE = 1


def main():
    devnode, _n, hid_name = find_vendor_hidraw()
    if not devnode:
        print("Vendor interface not found (Xbox mode + connected?).")
        return
    print(f"Found {devnode} ({hid_name})")
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
    time.sleep(1.0)  # let the command channel warm up

    def read_register(profile, addr, length):
        print(f"\n--- Read Register: profile={profile} addr={addr:#06x} len={length} ---")
        # flush stale input
        t0 = time.time()
        while time.time() - t0 < 0.1:
            d.read(64, timeout_ms=10)
        d.write(pad(0x0F, 0x04, profile, (addr >> 8) & 0xFF, addr & 0xFF, length))
        # collect replies that are NOT the 0x12 input stream
        t0 = time.time()
        seen = 0
        while time.time() - t0 < 0.6 and seen < 8:
            try:
                data = d.read(64, timeout_ms=50)
            except OSError:
                break
            if not data or data[0] == 0x12:
                continue
            print(f"  reply: {bytes(data[:20]).hex(' ')}")
            seen += 1
        if seen == 0:
            print("  (no non-0x12 reply)")

    # Probe a few addresses / lengths to learn the format.
    read_register(PROFILE, 0x0000, 0x10)
    read_register(PROFILE, 0x0010, 0x10)
    read_register(PROFILE, 0x0000, 0x01)
    read_register(PROFILE, 0x0020, 0x10)

    alive[0] = False
    time.sleep(0.2)
    d.close()
    print("\nDone.")


if __name__ == '__main__':
    main()
