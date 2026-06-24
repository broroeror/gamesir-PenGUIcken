"""
GameSir Cyclone 2 - restore verifier  [Xbox mode]
=================================================
Reads a few representative registers straight off the controller and prints
them, so you can confirm Backup/Restore actually wrote what it should - WITHOUT
trusting the GUI's cached/auto-loaded view (which is what misled us before).

Usage: run it at three points and compare the printed lines:

    sudo python3 gamesir_verify.py        # (A) snapshot the current values, then Export a backup
    # ... change settings in the app + push ...
    sudo python3 gamesir_verify.py        # (B) confirm the values are now DIFFERENT
    # ... Restore from the backup ...
    sudo python3 gamesir_verify.py        # (C) should match (A) again

If (C) == (A) and (B) differs, Restore works. Covers the active profile (bank 1
config) AND lighting (bank 0x20: active slot + slot-0 record header/colors).
"""

import threading
import time
import hid
from gs_common import find_vendor_hidraw, pad

# (label, bank, addr, length) - a small representative spread. Slot record base
# is 0x0001 + slot*0x7c; we read each slot's header + first colour triplet so we
# can see which slot actually holds which colour on the device.
PROBES = [
    ('cfg  vibration L/R (b1 0x0020)', 0x01, 0x0020, 2),
    ('cfg  poll rate     (b1 0x002e)', 0x01, 0x002e, 1),
    ('cfg  LT trigger blk(b1 0x01f1)', 0x01, 0x01f1, 6),
    ('cfg  L-stick block (b1 0x0227)', 0x01, 0x0227, 8),
    ('led  active slot   (b32 0x0000)', 0x20, 0x0000, 1),
    ('led  slot0 record  (b32 0x0001)', 0x20, 0x0001, 8),
    ('led  slot1 record  (b32 0x007d)', 0x20, 0x007d, 8),
    ('led  slot2 record  (b32 0x00f9)', 0x20, 0x00f9, 8),
    ('led  slot3 record  (b32 0x0175)', 0x20, 0x0175, 8),
]


def main():
    devnode, _n, hid_name = find_vendor_hidraw()
    if not devnode:
        print('Vendor interface not found (Xbox mode + connected?).')
        return
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

    cmd_for = lambda bank, addr, length: pad(
        0x0F, 0x04, bank, (addr >> 8) & 0xFF, addr & 0xFF, length)

    def read_register(bank, addr, length):
        cmd = cmd_for(bank, addr, length)
        # The controller drops a command that lands right after another (e.g. the
        # heartbeat), so resend until a matching reply comes back.
        for _ in range(8):
            t0 = time.time()                       # flush stale input
            while time.time() - t0 < 0.05:
                d.read(64)
            d.write(cmd)
            t0 = time.time()
            while time.time() - t0 < 0.3:
                data = d.read(64)
                if not data or data[0] == 0x12:
                    continue
                # reply: 10 05 <bank> <hi> <lo> <len> <data...> - match ours
                if (data[0] == 0x10 and data[1] == 0x05 and data[2] == bank
                        and ((data[3] << 8) | data[4]) == addr):
                    ln = data[5]
                    return bytes(data[6:6 + ln])
        return None

    print(f'# {hid_name}')
    print(f'# {time.strftime("%H:%M:%S")}')
    for label, bank, addr, length in PROBES:
        val = read_register(bank, addr, length)
        shown = val.hex(' ') if val else '(no reply)'
        print(f'{label} = {shown}')
        time.sleep(0.15)   # the pad drops back-to-back commands

    alive[0] = False
    time.sleep(0.2)
    d.close()


if __name__ == '__main__':
    main()
