"""
GameSir Cyclone 2 - Interface Scanner
=====================================
Lists every GameSir vendor interface (VID 0x3537) and checks which one actually
streams a POPULATED 0x12 enhanced report. Useful when wired + dongle are both
present and we need to pick the right node.

Run with the cable plugged in (the case where the GUI shows "No Xbox-mode data"):
  sudo python3 gamesir_scan.py
"""

import glob
import os
import time
import hid
from gs_common import pad

VENDOR_VID = 0x3537


def list_vendor_nodes():
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
                nodes.append((f'/dev/{name}', name, hid_name, hid_id))
    return nodes


def probe(devnode):
    """Open, send heartbeats, read ~1.2s; report report IDs and if 0x12 is populated."""
    try:
        d = hid.device()
        d.open_path(devnode.encode())
        d.set_nonblocking(True)
    except Exception as e:
        return f"open failed: {e}"
    ids = set()
    populated = False
    last_hb = 0
    t0 = time.time()
    while time.time() - t0 < 1.2:
        now = time.time()
        if now - last_hb > 0.4:           # keep a heartbeat going
            try:
                d.write(pad(0x0F, 0xF2))
            except Exception:
                pass
            last_hb = now
        try:
            data = d.read(64, timeout_ms=50)
        except OSError:
            break
        if not data:
            continue
        ids.add(data[0])
        if data[0] == 0x12 and (data[1] or data[2] or data[3] or data[4] or data[36]):
            populated = True
    d.close()
    rid = ','.join(hex(i) for i in sorted(ids)) or 'none'
    verdict = "  <-- POPULATED 0x12 (use this one)" if populated else ""
    return f"report IDs: {rid}{verdict}"


def main():
    nodes = list_vendor_nodes()
    if not nodes:
        print("No GameSir vendor (VID 0x3537) interfaces found.")
        return
    print(f"Found {len(nodes)} GameSir vendor interface(s):\n")
    for devnode, name, hid_name, hid_id in nodes:
        print(f"{devnode}  [{hid_id}]  {hid_name}")
        print(f"   {probe(devnode)}\n")


if __name__ == '__main__':
    main()
