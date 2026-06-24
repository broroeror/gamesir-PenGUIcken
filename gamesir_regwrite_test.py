"""
GameSir Cyclone 2 - Write Register validator  [Xbox mode]
=========================================================
First test of WRITE register (0x0F 0x03) in the per-profile CONFIG bank, where
remap / deadzones / trigger curves live (profile = 1..4, NOT the 0x20 lighting
bank). This is a SAFE read-modify-readback-restore on a SINGLE byte:

  1. read the target byte                (proves read works here)
  2. write it back FLIPPED (val ^ 0x01)  (proves write is accepted)
  3. read again, expect the flipped val  (proves the write actually TOOK)
  4. write the ORIGINAL value back       (undo)
  5. read again, expect the original     (proves we left it as we found it)

It prints PASS/FAIL at each stage and always tries to restore, even on error.
The byte only moves by its low bit, and it's put back -- nothing persists.

Usage:  sudo python3 gamesir_regwrite_test.py [profile] [addr_hex]
        defaults: profile 1, addr auto-picked (first non-zero byte in window)
"""

import sys
import threading
import time
import hid
from gs_common import find_vendor_hidraw, pad

WINDOW_START = 0x01F0   # show context around here; the 0x1f0 config block
WINDOW_LEN = 0x10


def read_register(d, profile, addr, length):
    """Return list of <length> bytes at addr, or None on no/!bad reply."""
    t0 = time.time()
    while time.time() - t0 < 0.05:          # flush stale input
        d.read(64, timeout_ms=5)
    d.write(pad(0x0F, 0x04, profile, (addr >> 8) & 0xFF, addr & 0xFF, length))
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


def write_register(d, profile, addr, values):
    """Write <values> at addr. Spaced after; caller reads back to confirm."""
    payload = [0x0F, 0x03, profile, (addr >> 8) & 0xFF, addr & 0xFF,
               len(values)] + list(values)
    d.write(pad(*payload))
    time.sleep(0.15)        # the controller drops a command sent too soon


def main():
    profile = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    target = int(sys.argv[2], 16) if len(sys.argv) > 2 else None

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
    time.sleep(1.0)  # warm up the command channel

    try:
        # --- context: show the window so we pick a sane byte -------------
        window = read_register(d, profile, WINDOW_START, WINDOW_LEN)
        if window is None:
            print(f"FAIL: could not read context window at {WINDOW_START:#06x} "
                  f"(profile {profile}). Is the controller in Xbox mode?")
            return
        cells = ' '.join(f"{b:02x}" for b in window)
        print(f"\nprofile {profile}  {WINDOW_START:#06x}: {cells}")

        # pick target: given addr, else first non-zero byte in the window
        if target is None:
            nz = next((i for i, b in enumerate(window) if b != 0), None)
            if nz is None:
                print("No non-zero byte in window to test on; pass an addr "
                      "explicitly: sudo python3 gamesir_regwrite_test.py 1 0x01f4")
                return
            target = WINDOW_START + nz
        print(f"target byte: addr {target:#06x}  profile {profile}")

        # --- 1. read original ------------------------------------------
        orig = read_register(d, profile, target, 1)
        if orig is None:
            print(f"FAIL (step 1 read): no reply at {target:#06x}")
            return
        orig = orig[0]
        flipped = orig ^ 0x01
        print(f"\nstep 1  read original : {orig:#04x}   PASS")
        print(f"        will write     : {flipped:#04x} (orig ^ 0x01), then restore")

        try:
            ans = input("\nproceed with write? [y/N] ").strip().lower()
        except EOFError:
            ans = ''
        if ans != 'y':
            print("aborted; nothing written.")
            return

        # --- 2 + 3. write flipped, read back ---------------------------
        write_register(d, profile, target, [flipped])
        rb = read_register(d, profile, target, 1)
        rb = rb[0] if rb else None
        if rb == flipped:
            print(f"step 2  write {flipped:#04x}      : readback {rb:#04x}   PASS "
                  f"(write is accepted here!)")
        else:
            print(f"step 2  write {flipped:#04x}      : readback "
                  f"{rb if rb is None else hex(rb)}   FAIL "
                  f"(write rejected / needs a commit / wrong bank)")

        # --- 4 + 5. restore, read back ---------------------------------
        write_register(d, profile, target, [orig])
        rb2 = read_register(d, profile, target, 1)
        rb2 = rb2[0] if rb2 else None
        if rb2 == orig:
            print(f"step 3  restore {orig:#04x}    : readback {rb2:#04x}   PASS "
                  f"(left as found)")
        else:
            print(f"step 3  restore {orig:#04x}    : readback "
                  f"{rb2 if rb2 is None else hex(rb2)}   *** WARNING: NOT restored! "
                  f"re-run to retry, or reset the profile in the official app ***")
    finally:
        alive[0] = False
        time.sleep(0.2)
        d.close()
        print("\nDone.")


if __name__ == '__main__':
    main()
