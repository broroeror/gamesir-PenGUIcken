"""
GameSir Cyclone 2 - read / connection loop
==========================================
The background side: keep the controller open, maintain the heartbeat, poll the
profile + lighting slot, and parse the 0x12 enhanced stream into shared `state`.

Survives unplugging the cable (it keeps working over the 2.4GHz dongle), mode
switches, and hidraw node renumbering on re-enumeration.
"""

import threading
import time
import hid

from gs_common import (find_vendor_hidraw, read_firmware_version,
                       connected_product_ids)
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


def read_session(device):
    """Read one open device until it errors/disconnects. Returns on failure."""
    control.set_device(device)
    alive = [True]
    threading.Thread(target=maintenance_loop, args=(alive,), daemon=True).start()
    try:
        while True:
            control.pump_reads()   # keep queued register reads moving
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


def read_controller():
    """Continuously find, open, and read the controller; reconnect on drop."""
    while True:
        devnode, _name, _hid_name = find_vendor_hidraw()
        if not devnode:
            state['connected'] = False
            state['mode_ok'] = False
            state['controller'] = None
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
        state['firmware'] = read_firmware_version()   # from USB bcdDevice (no I/O)
        prof = profiles.detect(connected_product_ids())   # Cyclone vs G7
        profiles.set_active(prof)                          # rest of app follows this
        state['controller'] = prof.short if prof else None
        read_session(device)   # blocks until disconnect/error
        state['connected'] = False
        state['mode_ok'] = False
        try:
            device.close()
        except Exception:
            pass
        time.sleep(0.5)   # brief pause before trying to reconnect
