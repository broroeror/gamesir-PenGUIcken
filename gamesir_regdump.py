"""
GameSir Cyclone 2 - Register Dump + Diff  [Xbox mode, READ-ONLY/safe]
====================================================================
Dumps a range of config registers and auto-diffs against the previous run, so
you can find what controls a setting by changing it and re-dumping.

Reply format (learned): 10 05 <profile> <addrHi> <addrLo> <len> <data...>

Workflow to find the LED color register:
  1. Run it once          -> baseline saved
  2. Change the LED color  (however your controller lets you)
  3. Run it again          -> it prints exactly which bytes changed

Usage:  sudo python3 gamesir_regdump.py [profile] [start_hex] [end_hex]
        (defaults: profile 1, 0x0000..0x0100)
"""

import os
import sys
import threading
import time
import hid
from gs_common import find_vendor_hidraw, pad

SNAP = '/tmp/claude-1000/-home-esives-Documents-Programming/ae1ee04f-385f-48d9-9ee2-73d6184106e6/scratchpad/reg_snapshot.txt'
CHUNK = 16


def read_register(d, profile, addr, length):
    # flush stale
    t0 = time.time()
    while time.time() - t0 < 0.05:
        d.read(64, timeout_ms=5)
    d.write(pad(0x0F, 0x04, profile, (addr >> 8) & 0xFF, addr & 0xFF, length))
    t0 = time.time()
    while time.time() - t0 < 0.4:
        try:
            data = d.read(64, timeout_ms=50)
        except OSError:
            break
        if (data and data[0] == 0x10 and data[1] == 0x05
                and data[3] == ((addr >> 8) & 0xFF) and data[4] == (addr & 0xFF)):
            return list(data[6:6 + length])
    return None


def dump_range(d, profile, start, end):
    reg = {}
    addr = start
    while addr < end:
        n = min(CHUNK, end - addr)
        vals = read_register(d, profile, addr, n)
        if vals is not None:
            for i, v in enumerate(vals):
                reg[addr + i] = v
        addr += n
    return reg


def load_snap():
    if not os.path.exists(SNAP):
        return None
    reg = {}
    with open(SNAP) as f:
        for line in f:
            a, v = line.split()
            reg[int(a, 16)] = int(v, 16)
    return reg


def save_snap(reg):
    os.makedirs(os.path.dirname(SNAP), exist_ok=True)
    with open(SNAP, 'w') as f:
        for a in sorted(reg):
            f.write(f"{a:04x} {reg[a]:02x}\n")


def main():
    profile = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    start = int(sys.argv[2], 16) if len(sys.argv) > 2 else 0x0000
    end = int(sys.argv[3], 16) if len(sys.argv) > 3 else 0x0100

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

    old = load_snap()
    reg = dump_range(d, profile, start, end)
    alive[0] = False
    time.sleep(0.2)
    d.close()

    # print dump
    print(f"\nRegisters profile {profile}  {start:#06x}..{end:#06x}:")
    for row in range(start, end, 16):
        cells = ' '.join(f"{reg.get(row + i, 0):02x}" for i in range(16))
        print(f"  {row:04x}: {cells}")

    # diff vs previous run
    if old is not None:
        diffs = [(a, old.get(a), reg.get(a)) for a in sorted(reg)
                 if old.get(a) != reg.get(a)]
        print("\n=== CHANGED since last run ===")
        if diffs:
            for a, ov, nv in diffs:
                os_ = f"{ov:#04x}" if ov is not None else "--"
                ns_ = f"{nv:#04x}" if nv is not None else "--"
                print(f"  addr {a:#06x}: {os_} -> {ns_}")
        else:
            print("  (no changes)")
    else:
        print("\n(baseline saved - change a setting and run again to see the diff)")

    save_snap(reg)


if __name__ == '__main__':
    main()
