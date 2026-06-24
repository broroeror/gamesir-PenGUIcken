"""
GameSir Cyclone 2 - LED Command Probe  [Xbox mode]  *** experimental ***
=======================================================================
The LED isn't in registers, so it's set by an undocumented command. This steps
through plausible command IDs under report 0x0F, each trying to set a bright
RED, ONE per keypress, so you can see exactly which one reacts.

Safety: payloads are short R/G/B values, unlikely to match reset/calibration
magic. If the LED (or anything) goes weird, power-cycle the controller.

When the LED changes, note the printed index # and tell Claude. Ctrl+C to stop.

Run in Xbox mode:  sudo python3 gamesir_led_probe.py
"""

import threading
import time
import hid
from gs_common import find_vendor_hidraw, pad

# Candidate command IDs (skipping known ones: 03,04,05,06,07,0b,10,20,f2).
CMD_IDS = [0x08, 0x09, 0x0A, 0x0C, 0x0D, 0x0E, 0x11, 0x12,
           0x21, 0x22, 0x23, 0x24, 0x30, 0x31, 0x40, 0x50]

RED = (0xFF, 0x00, 0x00)


def build_attempts():
    """(label, payload) pairs to try, in order."""
    out = []
    for c in CMD_IDS:
        out.append((f"cmd {c:#04x}  [cmd R G B]", (0x0F, c, *RED)))
    for c in CMD_IDS:
        out.append((f"cmd {c:#04x}  [cmd 01 R G B]", (0x0F, c, 0x01, *RED)))
    return out


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

    attempts = build_attempts()
    print(f"\n{len(attempts)} attempts. Press Enter to send each; watch the LED.")
    print("Note the # that changes the LED. Ctrl+C to stop.\n")
    try:
        for i, (label, payload) in enumerate(attempts):
            input(f"#{i:2d}  send: {label}  ({' '.join(f'{b:02x}' for b in payload)}) ...")
            d.write(pad(*payload))
    except KeyboardInterrupt:
        pass
    finally:
        alive[0] = False
        time.sleep(0.2)
        d.close()
        print("\nStopped.")


if __name__ == '__main__':
    main()
