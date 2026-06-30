#!/usr/bin/env python3
"""
Controller input mapper
=======================
Passively reads the GameSir's evdev nodes and decodes every button / stick /
trigger to a friendly name, so we can document exactly what each physical control
emits (and catch the non-standard extras like the L4/R4 paddles and the M button,
which may route through the keyboard or mouse interface instead of the gamepad).

Unlike gamesir_input_diag.py this does NOT grab the nodes — it just listens, so
the desktop keeps working and mouse mode is unaffected while you test.

    python3 gamesir_input_map.py [seconds]      # default 60s, Ctrl-C to stop early

Press each control one at a time when prompted; a summary table prints at the end.
Reads /dev/input/event* directly (the udev rule's uaccess ACL grants your user
access — no sudo needed). Reuses device discovery from gamesir_input_diag.
"""

import os
import re
import select
import struct
import sys
import time

from gamesir_input_diag import parse_devices, VENDOR_VID

# struct input_event { struct timeval time; __u16 type, code; __s32 value; }
# 64-bit timeval = 2*long (16 bytes) -> total 24 bytes.
EV_FMT = 'llHHi'
EV_SIZE = struct.calcsize(EV_FMT)

EV_SYN, EV_KEY, EV_REL, EV_ABS, EV_MSC = 0, 1, 2, 3, 4
TYPE_NAMES = {EV_SYN: 'SYN', EV_KEY: 'KEY', EV_REL: 'REL', EV_ABS: 'ABS', EV_MSC: 'MSC'}

# Linux gamepad button codes (input-event-codes.h). South/East/North/West are by
# position; the Xbox letter is added for convenience.
KEY_NAMES = {
    0x130: 'BTN_SOUTH (A)',  0x131: 'BTN_EAST (B)',   0x132: 'BTN_C',
    0x133: 'BTN_NORTH (Y)',  0x134: 'BTN_WEST (X)',   0x135: 'BTN_Z',
    0x136: 'BTN_TL (LB)',    0x137: 'BTN_TR (RB)',
    0x138: 'BTN_TL2 (LT-d)', 0x139: 'BTN_TR2 (RT-d)',
    0x13a: 'BTN_SELECT (View)', 0x13b: 'BTN_START (Menu)',
    0x13c: 'BTN_MODE (Guide)',  0x13d: 'BTN_THUMBL (L3)', 0x13e: 'BTN_THUMBR (R3)',
}
# Extra/paddle buttons commonly land in the BTN_TRIGGER_HAPPY block (0x2c0+).
# A few keyboard/media codes the keyboard interface might emit.
KEYBOARD_NAMES = {
    1: 'KEY_ESC', 28: 'KEY_ENTER', 29: 'KEY_LEFTCTRL', 42: 'KEY_LEFTSHIFT',
    56: 'KEY_LEFTALT', 97: 'KEY_RIGHTCTRL', 99: 'KEY_SYSRQ', 100: 'KEY_RIGHTALT',
    113: 'KEY_MUTE', 114: 'KEY_VOLUMEDOWN', 115: 'KEY_VOLUMEUP',
    125: 'KEY_LEFTMETA', 126: 'KEY_RIGHTMETA', 158: 'KEY_BACK',
    164: 'KEY_PLAYPAUSE', 172: 'KEY_HOMEPAGE',
}
ABS_NAMES = {
    0: 'ABS_X (LS-X)',  1: 'ABS_Y (LS-Y)',  2: 'ABS_Z (LT)',
    3: 'ABS_RX (RS-X)', 4: 'ABS_RY (RS-Y)', 5: 'ABS_RZ (RT)',
    16: 'ABS_HAT0X (D-pad L/R)', 17: 'ABS_HAT0Y (D-pad U/D)',
}
REL_NAMES = {0: 'REL_X', 1: 'REL_Y', 6: 'REL_HWHEEL', 8: 'REL_WHEEL'}


def code_name(etype, code):
    if etype == EV_KEY:
        if code in KEY_NAMES:
            return KEY_NAMES[code]
        if 0x2c0 <= code <= 0x2cf:
            return 'BTN_TRIGGER_HAPPY%d' % (code - 0x2c0 + 1)
        if code in KEYBOARD_NAMES:
            return KEYBOARD_NAMES[code]
        return 'KEY_0x%x' % code
    if etype == EV_ABS:
        return ABS_NAMES.get(code, 'ABS_0x%x' % code)
    if etype == EV_REL:
        return REL_NAMES.get(code, 'REL_0x%x' % code)
    return '0x%x' % code


def node_label(path, name):
    """Short tag like 'event2/joystick' from the node + its input class."""
    base = os.path.basename(path)
    cls = 'gamepad'
    try:
        import subprocess
        props = subprocess.run(['udevadm', 'info', '-q', 'property', '-n', path],
                               capture_output=True, text=True, timeout=3).stdout
        if 'ID_INPUT_JOYSTICK=1' in props:
            cls = 'joystick'
        elif 'ID_INPUT_MOUSE=1' in props:
            cls = 'mouse'
        elif 'ID_INPUT_KEYBOARD=1' in props:
            cls = 'keyboard'
    except (OSError, ValueError):
        pass
    return '%s/%s' % (base, cls)


def main():
    dur = int(sys.argv[1]) if len(sys.argv) > 1 else 60

    # fdinfo[fd] = (path, label); open_paths tracks which paths we already hold.
    # Switching profiles (M+A) re-enumerates the controller — its event nodes
    # vanish and reappear (sometimes with a new USB product id) — so we must be
    # able to drop dead fds and reopen nodes mid-session, not just open once.
    fdinfo = {}
    open_paths = set()

    def sync_nodes(announce):
        for d in parse_devices():
            if d['vendor'] != VENDOR_VID:
                continue
            for ev in d['events']:
                if ev in open_paths:
                    continue
                try:
                    fd = os.open(ev, os.O_RDONLY | os.O_NONBLOCK)
                except OSError:
                    continue
                open_paths.add(ev)
                fdinfo[fd] = (ev, node_label(ev, d['name']))
                if announce:
                    print('   + %-18s [%s] (re-attached)' % (ev, fdinfo[fd][1]))

    def drop(fd):
        path, _ = fdinfo.pop(fd, (None, None))
        open_paths.discard(path)
        try:
            os.close(fd)
        except OSError:
            pass

    sync_nodes(announce=False)
    if not fdinfo:
        print('No vendor-3537 nodes found. Controller connected in Xbox mode?')
        return

    print('Listening on:')
    for ev, label in sorted(fdinfo.values()):
        print('   %-22s [%s]' % (ev, label))
    print('\nPress each control ONE AT A TIME. Order suggestion:')
    print('   A B X Y, LB RB, LT RT, D-pad (U D L R), L3 R3,')
    print('   View(⧉) Menu(≡) Guide(◉), then the back paddles L4/R4 and the M button.')
    print('   (Profile-switching with M re-enumerates the pad; that is handled.)')
    print('   ...listening for %ds (Ctrl-C to stop early)\n' % dur)

    # summary[(label, type, code)] = {'name', 'press', 'lo', 'hi', 'n'}
    summary = {}
    timeline = []   # (t, label, name, value) for KEY/REL — order matters for combos
    end = time.time() + dur
    last_scan = time.time()
    try:
        while time.time() < end:
            r, _, _ = select.select(list(fdinfo), [], [], 0.3)
            for fd in r:
                try:
                    data = os.read(fd, EV_SIZE * 64)
                except BlockingIOError:
                    continue
                except OSError:
                    drop(fd)          # node went away (re-enumeration)
                    continue
                label = fdinfo[fd][1]
                for i in range(0, len(data) - EV_SIZE + 1, EV_SIZE):
                    _, _, etype, code, value = struct.unpack(EV_FMT, data[i:i + EV_SIZE])
                    # SYN is just a frame terminator; MSC_SCAN is the raw scancode
                    # that rides along with each keypress — neither is a control.
                    if etype in (EV_SYN, EV_MSC):
                        continue
                    name = code_name(etype, code)
                    key = (label, etype, code)
                    rec = summary.setdefault(
                        key, {'name': name, 'press': False, 'lo': value,
                              'hi': value, 'n': 0})
                    rec['n'] += 1
                    rec['lo'] = min(rec['lo'], value)
                    rec['hi'] = max(rec['hi'], value)
                    # Keep the ordered KEY/REL stream so overlapping combos and
                    # per-button isolation can be read back as grouped timeline.
                    if etype in (EV_KEY, EV_REL):
                        timeline.append((time.time(), label, name, value))
                    # Live echo: buttons on press; axes only on first move.
                    if etype == EV_KEY and value == 1:
                        rec['press'] = True
                        print('  [%-16s] %-22s pressed' % (label, name))
                    elif etype in (EV_ABS, EV_REL) and rec['n'] == 1:
                        print('  [%-16s] %-22s moving (first=%d)' % (label, name, value))
            # Periodically reopen nodes that re-appeared after a re-enumeration.
            if time.time() - last_scan > 1.0:
                last_scan = time.time()
                sync_nodes(announce=True)
    except KeyboardInterrupt:
        print('\n(stopped)')
    finally:
        for fd in list(fdinfo):
            drop(fd)

    # ------------------------------------------------------------- summary
    print('\n' + '=' * 60)
    print('INPUT MAP  (controls seen this session)')
    print('=' * 60)
    by_node = {}
    for (label, etype, code), rec in summary.items():
        by_node.setdefault(label, []).append((etype, code, rec))
    for label in sorted(by_node):
        print('\n%s' % label)
        rows = sorted(by_node[label], key=lambda x: (x[0], x[1]))
        for etype, code, rec in rows:
            kind = TYPE_NAMES.get(etype, '?')
            if etype == EV_KEY:
                detail = 'press/release' if rec['press'] else 'seen'
            else:
                detail = 'range %d..%d' % (rec['lo'], rec['hi'])
            print('   %-3s code %-5d  %-24s %s' % (kind, code, rec['name'], detail))

    # --------------------------------------------------- grouped timeline
    if timeline:
        print('\n' + '=' * 60)
        print('TIMELINE  (blank line = pause > 0.4s — i.e. a new button)')
        print('=' * 60)
        t0 = timeline[0][0]
        prev = None
        for t, label, name, value in timeline:
            if prev is not None and t - prev > 0.4:
                print('   ' + '-' * 30)
            act = {1: 'down', 0: 'up'}.get(value, '%+d' % value)
            print('   %6.2fs  [%-16s] %-22s %s' % (t - t0, label, name, act))
            prev = t
    print()


if __name__ == '__main__':
    main()
