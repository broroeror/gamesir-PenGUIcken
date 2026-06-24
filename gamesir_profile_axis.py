"""
GameSir Cyclone 2 - Profile axis probe  [Xbox mode, READ-ONLY/safe]
===================================================================
Settles one question before we map remap/deadzone fields: how are the 4 PROFILES
addressed? Byte 2 of the read/write command is a BANK selector (LED proved this:
lighting = bank 0x20). So the 4 profiles are probably the ADDRESS blocks within
bank 0x01 (~0x1f0 / 0x490 / 0x740 / 0x9e0, spacing ~0x2a0), NOT byte-2 values 1-4.

This does ZERO writes. It just reads and prints two comparisons:

  A) the SAME window at byte2 = 1,2,3,4  -> are 2/3/4 other banks or echoes?
  B) the four candidate profile blocks at byte2 = 1, side by side
     -> do they look like 4 parallel profile configs?

Then it reports the current active profile (get-profile) so you can, optionally,
switch profiles on the controller (hold M + right-stick up/down) and re-run to see
which block tracks "active".

Run in Xbox mode:  sudo python3 gamesir_profile_axis.py
"""

import threading
import time
import hid
from gs_common import find_vendor_hidraw, pad

WIN = 0x10                                  # bytes per window
PROFILE_BLOCKS = [0x01f0, 0x0490, 0x0740, 0x09e0]


def read_register(d, bank, addr, length):
    t0 = time.time()
    while time.time() - t0 < 0.05:          # flush stale input
        d.read(64, timeout_ms=5)
    d.write(pad(0x0F, 0x04, bank, (addr >> 8) & 0xFF, addr & 0xFF, length))
    t0 = time.time()
    while time.time() - t0 < 0.5:
        try:
            data = d.read(64, timeout_ms=50)
        except OSError:
            break
        if (data and data[0] == 0x10 and data[1] == 0x05
                and data[3] == ((addr >> 8) & 0xFF)
                and data[4] == (addr & 0xFF)):
            return list(data[6:6 + length])
    return None


def get_profile(d):
    t0 = time.time()
    while time.time() - t0 < 0.05:
        d.read(64, timeout_ms=5)
    d.write(pad(0x0F, 0x0B))
    t0 = time.time()
    while time.time() - t0 < 0.5:
        try:
            data = d.read(64, timeout_ms=50)
        except OSError:
            break
        if data and data[0] == 0x10 and data[1] == 0x0C:
            return data[2]
    return None


def hexrow(vals):
    return ' '.join(f"{b:02x}" for b in vals) if vals else "(no reply)"


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
    time.sleep(1.0)

    try:
        cur = get_profile(d)
        print(f"\nactive profile (get-profile 0x0B): "
              f"{cur if cur is None else cur}")

        print(f"\n=== A) SAME window {0x01f0:#06x} at byte2 = 1..4 "
              f"(is byte2 the profile, or a bank?) ===")
        for b2 in (1, 2, 3, 4):
            print(f"  byte2={b2}: {hexrow(read_register(d, b2, 0x01f0, WIN))}")

        print(f"\n=== B) candidate profile blocks at byte2 = 1 "
              f"(do they look like 4 parallel configs?) ===")
        for blk in PROFILE_BLOCKS:
            print(f"  {blk:#06x}: {hexrow(read_register(d, 1, blk, WIN))}")

        print("\nReading hints:")
        print("  - If A) rows 2/3/4 differ from row 1 and look like config, byte2 IS")
        print("    the profile. If they're zero / echo row 1 / look unrelated, byte2")
        print("    is a BANK and profiles live in the B) address blocks.")
        print("  - If the four B) blocks have the same SHAPE (same non-zero layout,")
        print("    different values), those are the 4 profiles.")
        print("  - To confirm which tracks 'active': switch profile on the pad")
        print("    (hold M + right-stick up/down) and re-run; watch what moved.")
    finally:
        alive[0] = False
        time.sleep(0.2)
        d.close()
        print("\nDone.")


if __name__ == '__main__':
    main()
