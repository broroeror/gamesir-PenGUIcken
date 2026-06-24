"""
GameSir Cyclone 2 - Linux Input Driver
=======================================
Reads input from the GameSir Cyclone 2 controller via hidraw0 (hid_playstation driver).

HID Device:
  - Vendor ID:  0x054C (Sony spoof)
  - Product ID: 0x09CC
  - Path:       /dev/hidraw0
  - Run with:   sudo python3 gamesir_cyclone2.py
    (or add udev rule to allow user access)

Report Format (64 bytes, Report ID: 0x01):
  Byte 0:   Report ID (always 1)
  Byte 1:   Left Stick X  (0-255, center=128)
  Byte 2:   Left Stick Y  (0-255, center=128)
  Byte 3:   Right Stick X (0-255, center=128)
  Byte 4:   Right Stick Y (0-255, center=128)
  Byte 5:   B1 - D-pad (lower 4 bits) + Face buttons (upper 4 bits)
  Byte 6:   B2 - Shoulder/trigger/stick buttons
  Byte 7:   B3 - Timestamp (increments by 4, wraps at 256) - IGNORE
  Byte 8:   Left Trigger  (0-255 analog)
  Byte 9:   Right Trigger (0-255 analog)
  Bytes 10+: Gyro, accelerometer, other data

B1 Button Map (byte 5):
  Bits 3-0: D-pad direction (lower nibble)
    15 = Neutral
     0 = Up (North)
     2 = Right (East)
     4 = Down (South)
     6 = Left (West)
     1 = Up-Right, 3 = Down-Right, 5 = Down-Left, 7 = Up-Left
  Bit 4: B button
  Bit 5: A button
  Bit 6: X button
  Bit 7: Y button

B2 Button Map (byte 6):
  Bit 0: LB  (Left Bumper)
  Bit 1: RB  (Right Bumper)
  Bit 2: LT  (Left Trigger  - digital, mirrors analog byte 8)
  Bit 3: RT  (Right Trigger - digital, mirrors analog byte 9)
  Bit 4: View  (Back/Select)
  Bit 5: Menu  (Start)
  Bit 6: LS   (Left Stick click)
  Bit 7: RS   (Right Stick click)

NOT YET MAPPED:
  - L4, R4 back buttons (likely require GameSir vendor HID interface on hidraw6)
  - Home button
  - Share/Capture button
"""

import hid
import time


HIDRAW_PATH = b'/dev/hidraw0'

# D-pad direction values (lower nibble of byte 5)
DPAD = {
    15: 'neutral',
     0: 'up',
     1: 'up-right',
     2: 'right',
     3: 'down-right',
     4: 'down',
     5: 'down-left',
     6: 'left',
     7: 'up-left',
}


def parse_report(data):
    """Parse a 64-byte HID report into a readable state dict."""
    b1 = data[5]
    b2 = data[6]
    return {
        'lx':    data[1],
        'ly':    data[2],
        'rx':    data[3],
        'ry':    data[4],
        'dpad':  DPAD.get(b1 & 0x0F, 'unknown'),
        'y':     bool(b1 & 0x80),
        'a':     bool(b1 & 0x20),
        'b':     bool(b1 & 0x40),
        'x':     bool(b1 & 0x10),
        'lb':    bool(b2 & 0x01),
        'rb':    bool(b2 & 0x02),
        'lt':    data[8],
        'rt':    data[9],
        'view':  bool(b2 & 0x10),
        'menu':  bool(b2 & 0x20),
        'ls':    bool(b2 & 0x40),
        'rs':    bool(b2 & 0x80),
    }


def main():
    device = hid.device()
    device.open_path(HIDRAW_PATH)
    device.set_nonblocking(False)

    print(f"Connected: {device.get_manufacturer_string()} {device.get_product_string()}")
    print("Reading input (Ctrl+C to stop):\n")

    try:
        prev = None
        while True:
            data = device.read(64)
            if not data:
                continue

            # Only update on meaningful changes (exclude timestamp byte 7)
            snapshot = (data[1], data[2], data[3], data[4], data[5], data[6], data[8], data[9])
            if snapshot == prev:
                continue
            prev = snapshot

            s = parse_report(data)

            # Only print if something interesting is happening
            buttons = [k for k in ('y','a','b','x','lb','rb','view','menu','ls','rs') if s[k]]
            sticks_moved = (
                abs(s['lx'] - 128) > 10 or abs(s['ly'] - 128) > 10 or
                abs(s['rx'] - 128) > 10 or abs(s['ry'] - 128) > 10
            )
            triggers = s['lt'] > 5 or s['rt'] > 5

            if buttons or sticks_moved or triggers or s['dpad'] != 'neutral':
                print(
                    f"LX:{s['lx']:3d} LY:{s['ly']:3d} RX:{s['rx']:3d} RY:{s['ry']:3d} | "
                    f"Dpad:{s['dpad']:<10} | "
                    f"LT:{s['lt']:3d} RT:{s['rt']:3d} | "
                    f"Btns: {' '.join(buttons) if buttons else '-'}"
                )

    except KeyboardInterrupt:
        pass
    finally:
        device.close()


if __name__ == '__main__':
    main()