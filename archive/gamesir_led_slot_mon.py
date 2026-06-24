"""
GameSir Cyclone 2 - lighting selector monitor  [Xbox mode]
==========================================================
Continuously reads register bank 0x20 / addr 0x0000 (the lighting "selector")
and prints it, flagging changes. Use it to answer one question: does this
register actually track the ACTIVE lighting preset when you switch via the
M + right-stick gesture (or the official app)?

Run it, then switch presets a few different ways and watch the printed value.

Usage:  sudo python3 gamesir_led_slot_mon.py
"""

import threading
import time
import hid
from gs_common import find_vendor_hidraw, pad


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

    print("\nMonitoring 0x20/0x0000. Switch lighting presets (M + right stick "
          "up/down, and/or the official app) and watch.\nCtrl-C to stop.\n")
    last = object()
    t0 = time.time()
    try:
        while True:
            v = read_reg(d, 0x20, 0x0000, 1)
            val = v[0] if v else None
            tag = "CHANGED" if val != last else "       "
            if val != last:
                print(f"  [{time.time()-t0:6.1f}s] {tag} selector = "
                      f"{val if val is not None else 'no-reply'}")
                last = val
            time.sleep(0.25)
    except KeyboardInterrupt:
        pass
    finally:
        alive[0] = False
        time.sleep(0.2)
        d.close()
        print("\nDone.")


if __name__ == '__main__':
    main()
