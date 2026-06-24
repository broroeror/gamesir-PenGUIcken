"""
GameSir Cyclone 2 - "mouse mode" suppressor
===========================================
After the 2.4GHz dongle re-pairs/replugs, moving the sticks drives the desktop
cursor ("mouse mode"). We chased this all the way down (see the diagnostics in
gamesir_input_diag.py): it is NOT the controller's emulated interface-1
mouse/keyboard - those evdev nodes stay silent. The cursor is driven by **KDE's
KWin compositor (Plasma 6 Wayland) reading the gamepad's joystick evdev node
directly** via its built-in game-controller-to-pointer support. libinput would
normally ignore a joystick, but KWin opens it out-of-band, so a `LIBINPUT_IGNORE`
udev rule does NOT stop it. The one thing that does: take an exclusive EVIOCGRAB
on the gamepad's evdev node, so KWin can no longer read it and the cursor goes
quiet. (Confirmed by grabbing each of the controller's nodes one at a time - only
the joystick node `event2` stops the cursor.)

So this module EVIOCGRAB's the controller's JOYSTICK evdev node when suppression
is on. A background thread re-applies the grab across dongle replugs (which churn
the event-node numbers) and drains + detects dead nodes so a stale grab can't
linger.

TRADE-OFF: grabbing the gamepad node is exclusive, so while suppression is on,
evdev-based games (Steam / SDL2, which read /dev/input/event*) won't see the pad
either. The legacy joystick node (/dev/input/jsN) and our own hidraw vendor
channel are unaffected, so the app keeps reading inputs while suppressing. This
is a deliberate desktop-use toggle, not a gaming-time fix - a permanent,
gaming-safe fix would mean disabling KWin's game-controller pointer feature
system-wide (no GUI toggle exists in Plasma 6.7).

Needs read access to the controller's /dev/input/event* nodes - granted by the
udev rule (TAG+="uaccess" on SUBSYSTEM=="input" for vendor 3537).
"""

import fcntl
import os
import re
import threading
import time

VENDOR_VID = 0x3537
# EVIOCGRAB = _IOW('E', 0x90, int): take an exclusive grab on an evdev node.
EVIOCGRAB = 0x40044590

_lock = threading.Lock()
_suppress = [False]
_fds = {}              # /dev/input/eventN -> open fd (held open == grabbed)
_status = ['off']      # 'off' | 'active (n)' | 'no access' | 'not found'
_started = [False]


def set_suppressed(on):
    """Turn suppression on/off. When on, the controller's emulated mouse and
    keyboard are grabbed so they can't move the cursor or type."""
    _suppress[0] = bool(on)


def is_suppressed():
    return _suppress[0]


def status():
    """Short machine status for the GUI: 'off', 'active (n)', 'no access',
    'not found'."""
    return _status[0]


def _target_nodes():
    """The controller's JOYSTICK evdev node - the one KWin reads to drive the
    cursor. Parsed from /proc/bus/input/devices: the vendor-3537 block whose
    handlers include a 'jsN' device (the gamepad). Grabbing it is what actually
    stops mouse mode; the emulated mouse/keyboard nodes are NOT the source."""
    try:
        with open('/proc/bus/input/devices') as fh:
            blocks = fh.read().split('\n\n')
    except OSError:
        return []
    nodes = []
    for blk in blocks:
        vendor = None
        handlers = ''
        for line in blk.splitlines():
            if line.startswith('I:'):
                m = re.search(r'Vendor=([0-9a-fA-F]{4})', line)
                if m:
                    vendor = int(m.group(1), 16)
            elif line.startswith('H: Handlers='):
                handlers = line
        if vendor != VENDOR_VID:
            continue
        if re.search(r'\bjs\d+\b', handlers):
            m = re.search(r'\bevent(\d+)\b', handlers)
            if m:
                nodes.append('/dev/input/event' + m.group(1))
    return nodes


def _drain_alive(fd):
    """Drain queued events (so a grabbed node's kernel buffer can't fill) and
    report whether the device is still alive (False once it's unplugged)."""
    try:
        while os.read(fd, 4096):
            pass
    except BlockingIOError:
        return True          # alive, nothing pending
    except OSError:
        return False         # device gone
    return True


def _release(path):
    fd = _fds.pop(path, None)
    if fd is None:
        return
    try:
        fcntl.ioctl(fd, EVIOCGRAB, 0)
    except OSError:
        pass
    try:
        os.close(fd)
    except OSError:
        pass


def _grab(path):
    fd = os.open(path, os.O_RDWR | os.O_NONBLOCK)
    fcntl.ioctl(fd, EVIOCGRAB, 1)
    _fds[path] = fd


def _sync():
    """Reconcile held grabs with the desired state. Called periodically so a
    dongle replug (new event numbers) is picked up automatically."""
    if not _suppress[0]:
        for path in list(_fds):
            _release(path)
        _status[0] = 'off'
        return

    # Drop grabs whose device vanished or got reused under the same path.
    for path in list(_fds):
        if not _drain_alive(_fds[path]):
            _release(path)

    targets = _target_nodes()
    for path in list(_fds):
        if path not in targets:
            _release(path)

    denied = False
    for path in targets:
        if path not in _fds:
            try:
                _grab(path)
            except OSError:
                denied = True   # perms missing (no udev rule) or it just vanished

    if not targets:
        _status[0] = 'not found'
    elif not _fds and denied:
        _status[0] = 'no access'
    else:
        _status[0] = f'active ({len(_fds)})'


def _loop():
    while True:
        with _lock:
            try:
                _sync()
            except Exception:
                pass
        time.sleep(0.5)


def start():
    """Start the background grab-maintenance thread (idempotent)."""
    if _started[0]:
        return
    _started[0] = True
    threading.Thread(target=_loop, daemon=True).start()
