#!/usr/bin/env python3
"""
Mouse-mode isolation diagnostic
===============================
Run this WHILE the controller is in "mouse mode" (cursor moving from the
sticks). It grabs the controller's evdev nodes ONE AT A TIME, holding each for a
few seconds, so you can watch which single node's grab makes the cursor stop.

The node whose window freezes the cursor is the real source of mouse mode - that
is the node gamesir_mousegrab.py needs to grab.

Run under sudo so it can open every node:

    sudo python3 gamesir_input_diag.py

The mouse is hijacked, so drive the terminal with the keyboard. During each
"GRABBING ..." window: move the sticks and watch whether the cursor stops.
"""

import fcntl
import os
import re
import time

VENDOR_VID = 0x3537
EVIOCGRAB = 0x40044590   # _IOW('E', 0x90, int)
HOLD = 5                 # seconds to hold each grab


def parse_devices():
    try:
        with open('/proc/bus/input/devices') as fh:
            blocks = fh.read().split('\n\n')
    except OSError as e:
        print('cannot read /proc/bus/input/devices:', e)
        return []
    out = []
    for blk in blocks:
        if not blk.strip():
            continue
        name = vendor = product = None
        handlers = ''
        for line in blk.splitlines():
            if line.startswith('I:'):
                mv = re.search(r'Vendor=([0-9a-fA-F]{4})', line)
                mp = re.search(r'Product=([0-9a-fA-F]{4})', line)
                if mv:
                    vendor = int(mv.group(1), 16)
                if mp:
                    product = int(mp.group(1), 16)
            elif line.startswith('N: Name='):
                name = line.split('=', 1)[1].strip().strip('"')
            elif line.startswith('H: Handlers='):
                handlers = line.split('=', 1)[1].strip()
        events = re.findall(r'\bevent(\d+)\b', handlers)
        out.append({
            'name': name, 'vendor': vendor, 'product': product,
            'handlers': handlers,
            'events': ['/dev/input/event' + e for e in events],
        })
    return out


def grab_window(path, name):
    print(f'\n=== GRABBING {path}  [{name}] ===')
    print('    move the sticks now - DOES THE CURSOR STOP?')
    try:
        fd = os.open(path, os.O_RDWR | os.O_NONBLOCK)
    except OSError as e:
        print(f'    (cannot open: {e.strerror} - run with sudo?)')
        return
    try:
        fcntl.ioctl(fd, EVIOCGRAB, 1)
    except OSError as e:
        print(f'    (EVIOCGRAB failed: {e.strerror})')
        os.close(fd)
        return
    end = time.time() + HOLD
    while time.time() < end:
        try:
            while os.read(fd, 4096):
                pass
        except (BlockingIOError, OSError):
            pass
        remaining = end - time.time()
        print(f'    grabbed... {remaining:0.0f}s ', end='\r', flush=True)
        time.sleep(0.25)
    try:
        fcntl.ioctl(fd, EVIOCGRAB, 0)
    except OSError:
        pass
    os.close(fd)
    print(f'\n    released {path} - cursor should resume if this was the source')


def main():
    devs = parse_devices()
    targets = []
    for d in devs:
        if d['vendor'] == VENDOR_VID:
            for ev in d['events']:
                targets.append((ev, d['name'], d['handlers']))

    if not targets:
        print('No vendor-3537 event nodes found. Is the controller connected '
              'in Xbox mode?')
        return

    print('Controller (vendor 3537) evdev nodes to test one-by-one:')
    for ev, name, handlers in targets:
        print(f'  {ev:22s} {name}   [{handlers}]')
    print(f'\nEach is grabbed for {HOLD}s. Watch which window stops the cursor.')

    # Sort lowest event number first; gamepad node (js) usually lowest.
    targets.sort(key=lambda t: int(re.search(r'\d+', t[0]).group()))
    for ev, name, _ in targets:
        grab_window(ev, name)
        time.sleep(1.5)   # gap so you can see the cursor resume between nodes

    print('\nDone. Tell me which node\'s window stopped the cursor.')


if __name__ == '__main__':
    main()
