"""
GameSir Cyclone 2 - shared helpers for the vendor interface (hidraw)
===================================================================
The vendor protocol is only live in XInput/Xbox mode (hold green ~2s); in PS4
mode it's inert.

When the controller is wired into the PC, it exposes TWO vendor (VID 0x3537)
interfaces: one streams an EMPTY 0x12 report, the other (with a heartbeat)
streams the real, populated enhanced report. So we don't just take the first
match -- we probe and pick the interface that actually carries live data.
"""

import glob
import os
import time
import hid

VENDOR_VID = 0x3537   # GameSir native vendor interface
REPORT_LEN = 64       # 0x0F output report = report ID + 63 payload bytes


def pad(*payload):
    """Pad a command payload to the fixed 64-byte output report length."""
    return list(payload) + [0x00] * (REPORT_LEN - len(payload))


def read_firmware_version():
    """Return the controller firmware version string (e.g. '3.52'), or None.

    The official Windows app's Info button makes NO network or USB-command
    traffic (captures 22/24): the version comes straight from the USB device
    descriptor's bcdDevice field, which the OS already has from enumeration.
    hidapi exposes it as `release_number`; bcdDevice is BCD-encoded as JJ.MN
    (high byte = major, low byte = minor), so 0x0352 -> '3.52'."""
    try:
        rel = next((d.get('release_number', 0) for d in hid.enumerate()
                    if d.get('vendor_id') == VENDOR_VID), None)
    except Exception:
        return None
    if not rel:
        return None
    return f'{rel >> 8:x}.{rel & 0xff:02x}'


def find_vendor_nodes():
    """Return list of (devnode, hidraw_name, hid_name) for all GameSir vendor
    interfaces (matched by USB vendor id, so it survives mode/node changes)."""
    nodes = []
    for path in sorted(glob.glob('/sys/class/hidraw/hidraw*'),
                       key=lambda p: int(os.path.basename(p)[6:])):
        name = os.path.basename(path)
        try:
            with open(os.path.join(path, 'device', 'uevent')) as f:
                uevent = f.read()
        except OSError:
            continue
        hid_id = hid_name = ''
        for line in uevent.splitlines():
            if line.startswith('HID_ID='):
                hid_id = line.split('=', 1)[1]
            elif line.startswith('HID_NAME='):
                hid_name = line.split('=', 1)[1]
        parts = hid_id.split(':')
        if len(parts) == 3:
            try:
                vid = int(parts[1], 16)
            except ValueError:
                vid = 0
            if vid == VENDOR_VID:
                nodes.append((f'/dev/{name}', name, hid_name))
    return nodes


def _streams_live_data(devnode, secs=1.0):
    """Open devnode, send heartbeats, and report whether it yields a POPULATED
    0x12 report (sticks rest at 128 / battery non-zero, so an empty all-zero
    stream is rejected)."""
    try:
        d = hid.device()
        d.open_path(devnode.encode())
        d.set_nonblocking(True)
    except Exception:
        return False
    live = False
    last_hb = 0.0
    t0 = time.time()
    try:
        while time.time() - t0 < secs:
            now = time.time()
            if now - last_hb > 0.4:
                try:
                    d.write(pad(0x0F, 0xF2))
                except Exception:
                    pass
                last_hb = now
            try:
                data = d.read(64, timeout_ms=50)
            except OSError:
                break
            if data and data[0] == 0x12 and (data[1] or data[2] or data[3] or
                                             data[4] or data[36]):
                live = True
                break
    finally:
        try:
            d.close()
        except Exception:
            pass
    return live


def find_vendor_hidraw():
    """Return (devnode, name, hid_name) for the GameSir vendor interface that
    carries live enhanced data, or (None, None, None) if not found.

    With a single match we return it directly (fast path). With several (e.g.
    wired: empty + real interfaces) we probe and prefer the one streaming a
    populated 0x12 report, falling back to the first match.
    """
    nodes = find_vendor_nodes()
    if not nodes:
        return (None, None, None)
    if len(nodes) == 1:
        return nodes[0]
    for node in nodes:
        if _streams_live_data(node[0]):
            return node
    return nodes[0]
