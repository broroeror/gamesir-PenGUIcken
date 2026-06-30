#!/usr/bin/env python3
"""Enter the JieLi uboot/U-disk loader from Linux and identify it.

Sends the vendor command `0f 17 55 88` -- captured from GameSir Connect's
firmware update (USB captures 25/27/28) -- which reboots a Cyclone 2 into its
JieLi BR23/BR27 loader. The loader comes up as a USB mass-storage device with a
different VID/PID. This tool fires that command, then diffs the USB device tree
to report the loader's identity (VID/PID + descriptor strings) -- the info we
need to point a JieLi uboot tool / driver at it next.

SAFE: entering the loader is non-destructive -- nothing is written to flash here.
If the controller looks dead afterwards it is just PARKED in the loader: press
and HOLD the reset button (back center, under the MFG sticker) ~6s to return to
normal mode.

Usage: python3 gamesir_loader.py [--yes]
       --yes   skip the confirmation prompt
"""
import glob
import os
import sys
import time

import hid

from gs_common import find_vendor_hidraw, read_firmware_version, pad

ENTER_LOADER = (0x0F, 0x17, 0x55, 0x88)   # cap 25/27/28: triggers loader re-enum
RESET_HELP = ("If the pad now looks dead, it is just parked in the loader -- "
              "hold the reset button (back center, under the MFG sticker) ~6s.")


def _read(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return None


def snapshot_usb():
    """Map of sysfs-name -> descriptor info for every USB *device* (not iface).

    Interface dirs contain ':' (e.g. 1-2:1.0); real devices don't (1-2, 1-2.3).
    """
    out = {}
    for path in glob.glob('/sys/bus/usb/devices/*'):
        name = os.path.basename(path)
        if ':' in name or name.startswith('usb'):
            continue
        vid = _read(os.path.join(path, 'idVendor'))
        if vid is None:
            continue
        out[name] = {
            'vid': vid,
            'pid': _read(os.path.join(path, 'idProduct')),
            'mfr': _read(os.path.join(path, 'manufacturer')),
            'prod': _read(os.path.join(path, 'product')),
            'serial': _read(os.path.join(path, 'serial')),
            'rev': _read(os.path.join(path, 'bcdDevice')),
            'busdev': f"{_read(os.path.join(path, 'busnum'))}:"
                      f"{_read(os.path.join(path, 'devnum'))}",
        }
    return out


def describe(name, d):
    bits = [f"{d['vid']}:{d['pid']}", f"bus {d['busdev']}"]
    for k in ('mfr', 'prod', 'serial', 'rev'):
        if d.get(k):
            bits.append(f"{k}={d[k]}")
    return f"  [{name}] " + "  ".join(bits)


def main():
    yes = '--yes' in sys.argv[1:]

    devnode, hidname, _ = find_vendor_hidraw()
    if not devnode:
        sys.exit("No GameSir vendor interface found. Plug in the controller in "
                 "Xbox/XInput mode (hold the green button ~2s).")
    fw = read_firmware_version()
    print(f"Vendor node: {devnode} ({hidname})   firmware: {fw or '?'}")
    print(f"Will send ENTER-LOADER: "
          f"{' '.join(f'{b:02x}' for b in ENTER_LOADER)}")
    print("This reboots the controller into the JieLi loader (safe; no flash "
          "write).")
    if not yes:
        if input("Proceed? [y/N] ").strip().lower() not in ('y', 'yes'):
            sys.exit("Aborted.")

    before = snapshot_usb()

    try:
        dev = hid.device()
        dev.open_path(devnode.encode())
    except Exception as e:
        sys.exit(f"Could not open {devnode}: {e}")
    try:
        dev.write(pad(*ENTER_LOADER))
        print("Sent. Waiting for re-enumeration...")
    except Exception as e:
        # a write error can be normal if it drops off instantly
        print(f"(write returned: {e} -- continuing to watch USB)")
    finally:
        try:
            dev.close()
        except Exception:
            pass

    # Watch the USB tree for ~10s: the controller should vanish and the loader
    # should appear (or an existing node's VID/PID/product should change).
    appeared, vanished = {}, {}
    deadline = time.time() + 10
    while time.time() < deadline:
        time.sleep(0.4)
        now = snapshot_usb()
        appeared = {n: d for n, d in now.items() if n not in before}
        vanished = {n: d for n, d in before.items() if n not in now}
        # also catch in-place identity changes (same port, new descriptors)
        changed = {n: (before[n], now[n]) for n in now.keys() & before.keys()
                   if (now[n]['vid'], now[n]['pid']) != (before[n]['vid'],
                                                         before[n]['pid'])}
        if appeared or changed:
            break

    print("\n=== USB change after ENTER-LOADER ===")
    if vanished:
        print("Disappeared (was the controller):")
        for n, d in vanished.items():
            print(describe(n, d))
    if appeared:
        print("Appeared (LOADER candidate):")
        for n, d in appeared.items():
            print(describe(n, d))
    if 'changed' in dir() and changed:
        print("Changed identity in place (LOADER):")
        for n, (b, a) in changed.items():
            print("  was:" + describe(n, b))
            print("  now:" + describe(n, a))
    if not (appeared or vanished or ('changed' in dir() and changed)):
        print("No USB change detected. Either the command isn't the right "
              "trigger on this firmware, or it re-enumerated outside the watch "
              "window. Check `lsusb` manually.")

    print("\n" + RESET_HELP)
    print("Loader present? Next: `lsusb -v -d <vid>:<pid>` for full descriptors, "
          "and check for a new /dev/sg* (SCSI generic) node to talk to it.")


if __name__ == '__main__':
    main()
