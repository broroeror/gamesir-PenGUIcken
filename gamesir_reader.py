"""
GameSir Cyclone 2 - read / connection loop
==========================================
The background side: keep the controller open, maintain the heartbeat, poll the
profile + lighting slot, and parse the 0x12 enhanced stream into shared `state`.

Survives unplugging the cable (it keeps working over the 2.4GHz dongle), mode
switches, and hidraw node renumbering on re-enumeration.
"""

import fcntl
import os
import select
import struct
import threading
import time
import hid

from gs_common import (find_controllers, pick_live_node, read_firmware_version,
                       evdev_port)
from gamesir_enhanced import parse_enhanced
from gs_state import state
import gamesir_control as control
import controller_profile as profiles


def maintenance_loop(alive):
    """Sustained heartbeat (keeps Xbox-mode enhanced reports + command channel
    alive) plus periodic queries so the displayed gamepad profile AND lighting
    slot track reality, including changes made via the M + right-stick gesture.

    The two queries are ALTERNATED, never sent back-to-back: the controller
    drops the second command when they arrive too close together, which silently
    starves whichever query is sent second."""
    last_query = 0.0
    toggle = 0
    while alive[0]:
        control.send_cmd(0x0F, 0xF2)
        now = time.time()
        if now - last_query > 0.45:
            if toggle == 0:
                control.send_cmd(0x0F, 0x0B)                          # profile -> 0x10 0x0C
            else:
                control.send_cmd(0x0F, 0x04, 0x20, 0x00, 0x00, 0x01)  # lighting slot -> 0x10 0x05
            toggle ^= 1
            last_query = now
        time.sleep(0.5)


def _label(ctrl):
    """Public shape of a controller for the UI picker."""
    prof = profiles.by_product_id(ctrl['pid'])
    return {'id': ctrl['id'], 'name': prof.short if prof else 'Unknown',
            'port': ctrl['port'], 'pid': ctrl['pid']}


def _publish_controllers(controllers):
    state['controllers'] = [_label(c) for c in controllers]


def _pick_selected(controllers):
    """Drive the user's selected controller if it's still connected, otherwise
    default to the first one found."""
    sel = state.get('selected')
    for c in controllers:
        if c['id'] == sel:
            return c
    return controllers[0]


def read_session(device, driving_id):
    """Read one open controller until it errors, is unplugged, or the user
    selects a DIFFERENT controller. Returns so read_controller can reconnect.

    `driving_id` is the controller we opened; we rescan ~1 Hz to keep the picker
    list fresh and to notice an unplug / a selection change without blocking."""
    control.set_device(device)
    alive = [True]
    threading.Thread(target=maintenance_loop, args=(alive,), daemon=True).start()
    last_scan = 0.0
    try:
        while True:
            control.pump_reads()   # keep queued register reads moving
            now = time.time()
            if now - last_scan > 1.0:
                last_scan = now
                ids = [c['id'] for c in _rescan()]
                if driving_id not in ids:           # our controller unplugged
                    break
                sel = state.get('selected')
                if sel in ids and sel != driving_id:  # user switched controllers
                    break
            data = device.read(64, timeout_ms=200)
            if not data:
                continue
            if data[0] == 0x10 and data[1] == 0x0C:     # get-profile reply
                state['profile'] = data[2]
                continue
            if data[0] == 0x10 and data[1] == 0x05:     # read-register reply
                bank = data[2]
                addr = (data[3] << 8) | data[4]
                ln = data[5]
                control.store_reg_result(bank, addr, list(data[6:6 + ln]))
                if bank == 0x20 and addr == 0x0000:     # lighting selector
                    state['led_slot'] = data[6]
                continue
            if data[0] != 0x12:
                continue
            # Outside Xbox mode the 0x12 report streams all-zeros (sticks read 0,
            # not the 128 rest value). Treat that as "wrong mode".
            if data[1] == 0 and data[2] == 0 and data[3] == 0 and data[4] == 0:
                state['mode_ok'] = False
                continue
            state['mode_ok'] = True
            state.update(parse_enhanced(data))
    except Exception:
        pass
    finally:
        alive[0] = False
        control.clear_device()


def _rescan():
    """Re-enumerate controllers and publish the list; returns the controllers."""
    controllers = find_controllers()
    _publish_controllers(controllers)
    return controllers


def read_controller():
    """Continuously enumerate controllers, open the SELECTED one, and read it;
    reconnect on drop or when the user picks a different controller."""
    while True:
        controllers = _rescan()
        if not controllers:
            state['connected'] = False
            state['mode_ok'] = False
            state['controller'] = None
            state['selected'] = None
            time.sleep(1.0)
            continue

        sel = _pick_selected(controllers)
        state['selected'] = sel['id']
        prof = profiles.by_product_id(sel['pid'])
        profiles.set_active(prof)                      # rest of app follows this
        state['controller'] = prof.short if prof else None
        state['firmware'] = read_firmware_version(sel['pid'])   # USB bcdDevice

        # G7-family: input arrives over evdev (standard gamepad), not a vendor
        # hidraw stream, so read that instead of the Cyclone 0x12 path.
        if prof is not None and prof.input_style == 'evdev':
            state['connected'] = True
            read_session_evdev(sel['id'])   # blocks until drop / switch
            state['connected'] = False
            state['mode_ok'] = False
            time.sleep(0.3)
            continue

        # Cyclone: vendor hidraw 0x12 stream.
        devnode = pick_live_node(sel['nodes'])
        if not devnode:
            state['connected'] = False
            time.sleep(1.0)
            continue
        try:
            device = hid.device()
            device.open_path(devnode.encode())
            device.set_nonblocking(True)
        except Exception:
            state['connected'] = False
            time.sleep(1.0)
            continue

        state['connected'] = True
        read_session(device, sel['id'])   # blocks until drop / switch
        state['connected'] = False
        state['mode_ok'] = False
        try:
            device.close()
        except Exception:
            pass
        time.sleep(0.3)   # brief pause before reconnecting


# --- evdev input path (G7 family) -------------------------------------------
# struct input_event { struct timeval time; __u16 type, code; __s32 value; }
# 64-bit timeval = 2*long -> 24 bytes total. (Shared with press_select_loop.)
_EV_FMT = 'llHHi'
_EV_SIZE = struct.calcsize(_EV_FMT)
_EV_KEY, _EV_ABS = 1, 3


# EVIOCGABS(code) = _IOR('E', 0x40+code, struct input_absinfo) — read an axis's
# min/max so we can normalise it to the app's 0..255 (sticks) / 0..255 (triggers).
def _eviocgabs(code):
    return (2 << 30) | (24 << 16) | (ord('E') << 8) | (0x40 + code)


_KEY_TO_STATE = {           # Linux gamepad button codes -> state keys
    0x130: 'a', 0x131: 'b', 0x133: 'y', 0x134: 'x',
    0x136: 'lb', 0x137: 'rb', 0x13a: 'view', 0x13b: 'menu',
    0x13c: 'home', 0x13d: 'ls', 0x13e: 'rs',
    0x138: 'lt_d', 0x139: 'rt_d',
}
# ABS axis codes we care about (ignoring the HAT dpad, handled separately).
_ABS_CANDIDATES = (0, 1, 2, 3, 4, 5, 9, 10)
_HAT = {(0, 0): 'neutral', (0, -1): 'up', (1, -1): 'up-right', (1, 0): 'right',
        (1, 1): 'down-right', (0, 1): 'down', (-1, 1): 'down-left',
        (-1, 0): 'left', (-1, -1): 'up-left'}


def _axis_map(present):
    """Map a device's PRESENT ABS codes to state keys, handling both gamepad
    conventions: classic (right stick = RX/RY 3/4, triggers = Z/RZ 2/5) and
    modern (right stick = Z/RZ 2/5, triggers = GAS/BRAKE 9/10, as on the G7 Pro).
    Left stick is always X/Y."""
    m = {}
    if 0 in present:
        m[0] = 'lx'
    if 1 in present:
        m[1] = 'ly'
    if 3 in present and 4 in present:       # classic: RS on RX/RY
        m[3] = 'rx'; m[4] = 'ry'
        if 2 in present:
            m[2] = 'lt'
        if 5 in present:
            m[5] = 'rt'
    else:                                   # modern: RS on Z/RZ
        if 2 in present:
            m[2] = 'rx'
        if 5 in present:
            m[5] = 'ry'
    if 9 in present:                        # ABS_GAS = RT
        m[9] = 'rt'
    if 10 in present:                       # ABS_BRAKE = LT
        m[10] = 'lt'
    return m


def _scale(value, lo, hi):
    """Normalise an evdev axis value in [lo,hi] to 0..255."""
    if hi <= lo:
        return 128
    return max(0, min(255, round((value - lo) * 255 / (hi - lo))))


def _absinfo(fd, code):
    """(min, max) for an axis on this fd, or None if it lacks the axis."""
    buf = bytearray(24)
    try:
        fcntl.ioctl(fd, _eviocgabs(code), buf, True)
    except OSError:
        return None
    _v, mn, mx, _f, _fl, _r = struct.unpack('6i', bytes(buf))
    return (mn, mx) if mx > mn else None


def read_session_evdev(driving_id):
    """Read one G7-family controller's live input over evdev until it errors, is
    unplugged, or the user selects another controller. Maps standard gamepad
    events into the shared `state` (sticks/triggers normalised to 0..255)."""
    from gamesir_input_diag import parse_devices, VENDOR_VID
    fds = {}                # fd -> path
    axmap = {}              # fd -> {abs_code: state_key} for this device
    ranges = {}             # (fd, code) -> (min, max)
    for d in parse_devices():
        if d['vendor'] != VENDOR_VID:
            continue
        for ev in d['events']:
            if evdev_port(ev) != driving_id:
                continue
            try:
                fd = os.open(ev, os.O_RDONLY | os.O_NONBLOCK)
            except OSError:
                continue
            fds[fd] = ev
            present = {}     # code -> (min, max) for axes this node actually has
            for code in _ABS_CANDIDATES:
                r = _absinfo(fd, code)
                if r:
                    present[code] = r
            axmap[fd] = _axis_map(set(present))
            for code, rng in present.items():
                ranges[(fd, code)] = rng
    if not fds:
        time.sleep(1.0)
        return

    state['mode_ok'] = True
    hat = {'x': 0, 'y': 0}
    last_scan = time.time()
    try:
        while True:
            now = time.time()
            if now - last_scan > 1.0:
                last_scan = now
                ids = [c['id'] for c in _rescan()]
                if driving_id not in ids:               # unplugged
                    break
                sel = state.get('selected')
                if sel in ids and sel != driving_id:    # user switched
                    break
            r, _, _ = select.select(list(fds), [], [], 0.2)
            for fd in r:
                try:
                    data = os.read(fd, _EV_SIZE * 64)
                except BlockingIOError:
                    continue
                except OSError:
                    return                               # node vanished
                for i in range(0, len(data) - _EV_SIZE + 1, _EV_SIZE):
                    _, _, etype, code, value = struct.unpack(_EV_FMT, data[i:i + _EV_SIZE])
                    if etype == _EV_KEY:
                        k = _KEY_TO_STATE.get(code)
                        if k:
                            state[k] = bool(value)
                    elif etype == _EV_ABS:
                        key = axmap[fd].get(code)
                        if key:
                            rng = ranges.get((fd, code))
                            if rng:
                                state[key] = _scale(value, *rng)
                        elif code == 16:                 # ABS_HAT0X
                            hat['x'] = (value > 0) - (value < 0)
                            state['dpad'] = _HAT.get((hat['x'], hat['y']), 'neutral')
                        elif code == 17:                 # ABS_HAT0Y
                            hat['y'] = (value > 0) - (value < 0)
                            state['dpad'] = _HAT.get((hat['x'], hat['y']), 'neutral')
    except Exception:
        pass
    finally:
        for fd in list(fds):
            try:
                os.close(fd)
            except OSError:
                pass
        state['mode_ok'] = False


# --- press-to-select --------------------------------------------------------
def _maybe_select(port):
    """Switch to `port` if it's a connected controller other than the current
    one. No-op with a single controller (nothing to switch between)."""
    if not port:
        return
    ids = [c['id'] for c in state['controllers']]
    if len(ids) >= 2 and port in ids and port != state.get('selected'):
        state['selected'] = port


def press_select_loop():
    """Watch every connected GameSir pad's evdev button events; a button press on
    a controller that ISN'T selected switches to it ('press to select').

    Uses evdev (the standard gamepad interface) rather than the vendor channel:
    the Cyclone's 0x12 report only streams while we heartbeat it, so a
    non-selected controller is silent there — but its buttons always reach evdev.
    Works uniformly for Cyclone and G7."""
    from gamesir_input_diag import parse_devices, VENDOR_VID
    fds = {}                    # fd -> (path, port)
    open_paths = set()

    def sync():
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
                fds[fd] = (ev, evdev_port(ev))

    def drop(fd):
        path, _ = fds.pop(fd, (None, None))
        open_paths.discard(path)
        try:
            os.close(fd)
        except OSError:
            pass

    last_scan = 0.0
    while True:
        now = time.time()
        if now - last_scan > 1.5:       # pick up (re)enumerated pads
            last_scan = now
            sync()
        if not fds:
            time.sleep(0.5)
            continue
        try:
            r, _, _ = select.select(list(fds), [], [], 0.3)
        except OSError:
            for fd in list(fds):
                drop(fd)
            continue
        for fd in r:
            try:
                data = os.read(fd, _EV_SIZE * 32)
            except BlockingIOError:
                continue
            except OSError:
                drop(fd)
                continue
            port = fds.get(fd, (None, None))[1]
            for i in range(0, len(data) - _EV_SIZE + 1, _EV_SIZE):
                _, _, etype, code, value = struct.unpack(_EV_FMT, data[i:i + _EV_SIZE])
                if etype == _EV_KEY and value == 1:   # a button went down
                    _maybe_select(port)
                    break
