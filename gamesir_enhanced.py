"""
GameSir Cyclone 2 - Enhanced (0x12) Report Parser  [Xbox/XInput mode]
====================================================================
The single input source for the app when the controller is in Xbox mode.
The 0x12 report (vendor interface, hidraw, VID 0x3537) carries EVERYTHING:
sticks, all buttons, triggers, IMU, the extra buttons (L4/R4/M/Home/Share),
and a fine-grained battery percentage.

Byte map (byte 0 = report ID 0x12), DS4-style early bytes + GameSir extras:
  1-4   LX, LY, RX, RY        (center 128)
  5     dpad (low nibble) + face buttons (high nibble)
  6     L1/R1/L2/R2/View/Menu/L3/R3  (DS4 button byte 2)
  7     report counter (ignore)
  8,9   LT, RT analog                (to confirm on your unit)
  14-24 IMU (gyro/accel), noisy
  36    battery percentage (0-100)   <-- candidate, verify with --watch
  37    battery/charge status flag   <-- candidate
  58,59 RAW copies of byte 5/6 (pre-binding)
  60    extra buttons: Home 0x01, Share 0x02, L4 0x08, R4 0x10, M 0x20

Run a live decode to verify:  sudo python3 gamesir_enhanced.py
"""

import time
from gs_common import find_vendor_hidraw, pad

DPAD = {
    15: 'neutral', 8: 'neutral',
    0: 'up', 1: 'up-right', 2: 'right', 3: 'down-right',
    4: 'down', 5: 'down-left', 6: 'left', 7: 'up-left',
}


def parse_enhanced(d):
    """Parse a 64-byte 0x12 report into a state dict."""
    b5, b6, b60 = d[5], d[6], d[60]
    return {
        'lx': d[1], 'ly': d[2], 'rx': d[3], 'ry': d[4],
        'lt': d[8], 'rt': d[9],
        'dpad': DPAD.get(b5 & 0x0F, 'unknown'),
        # face buttons (DS4 high nibble): square/cross/circle/triangle
        'x': bool(b5 & 0x10),   # square
        'a': bool(b5 & 0x20),   # cross
        'b': bool(b5 & 0x40),   # circle
        'y': bool(b5 & 0x80),   # triangle
        # byte 6 (DS4 button byte 2)
        'lb':   bool(b6 & 0x01),
        'rb':   bool(b6 & 0x02),
        'lt_d': bool(b6 & 0x04),
        'rt_d': bool(b6 & 0x08),
        'view': bool(b6 & 0x10),
        'menu': bool(b6 & 0x20),
        'ls':   bool(b6 & 0x40),
        'rs':   bool(b6 & 0x80),
        # extra buttons (byte 60)
        'home':  bool(b60 & 0x01),
        'share': bool(b60 & 0x02),
        'l4':    bool(b60 & 0x08),
        'r4':    bool(b60 & 0x10),
        'm':     bool(b60 & 0x20),
        # battery: byte 36 = percent (confirmed), byte 35 bit 0 = charging/cable
        'battery': d[36],
        'charging': bool(d[35] & 0x01),
        # raw IMU bytes for display/debug
        'imu': list(d[14:25]),
    }


def _heartbeat(device, running):
    while running[0]:
        try:
            device.write(pad(0x0F, 0xF2))
        except Exception:
            return
        time.sleep(0.5)


def main():
    import hid
    import threading

    devnode, name, hid_name = find_vendor_hidraw()
    if not devnode:
        print("Vendor interface not found. Controller in Xbox/green mode and connected?")
        return
    print(f"Found {devnode} ({hid_name})")
    device = hid.device()
    device.open_path(devnode.encode())
    device.set_nonblocking(True)

    running = [True]
    threading.Thread(target=_heartbeat, args=(device, running), daemon=True).start()

    print("Live decode @1Hz. Press L4/R4/M/Home/Share to see them. Ctrl+C to stop.")
    print("VERIFY: does 'battery' match your controller's real charge level?\n")
    last = 0
    try:
        while True:
            try:
                d = device.read(64, timeout_ms=100)
            except OSError:
                continue
            if not d or d[0] != 0x12:
                continue
            now = time.time()
            if now - last < 1.0:
                continue
            last = now
            s = parse_enhanced(d)
            pressed = [k.upper() for k in
                       ('a','b','x','y','lb','rb','view','menu','ls','rs',
                        'home','share','l4','r4','m') if s[k]]
            print(f"batt={s['battery']:3d}%{' (charging)' if s['charging'] else '':12s} | "
                  f"L({s['lx']:3d},{s['ly']:3d}) R({s['rx']:3d},{s['ry']:3d}) | "
                  f"LT={s['lt']:3d} RT={s['rt']:3d} | dpad={s['dpad']:<10} | "
                  f"{' '.join(pressed) if pressed else '-'}")
    except KeyboardInterrupt:
        pass
    finally:
        running[0] = False
        time.sleep(0.2)
        try:
            device.close()
        except Exception:
            pass


if __name__ == '__main__':
    main()
