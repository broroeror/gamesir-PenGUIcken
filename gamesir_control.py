"""
GameSir Cyclone 2 - command / write layer
=========================================
Everything the host SENDS to the controller over the vendor command channel
(report 0x0F): the shared device handle, the thread-safe writer, and the
high-level commands (profile, rumble, register write).

Commands and the read loop share ONE hid handle across threads, so every write
goes through a single lock. The handle is REBOUND on each reconnect, so callers
must never cache it: `send_cmd` reads the current handle live, and the reader
publishes the handle via `set_device` / `clear_device`.
"""

import collections
import threading
import time

from gs_common import pad

_write_lock = threading.Lock()
_device = None


def set_device(dev):
    """Publish the freshly-opened handle so commands target it."""
    global _device
    _device = dev


def clear_device():
    """Drop the handle (on disconnect); commands become no-ops until reopened."""
    global _device
    _device = None


def send_cmd(*payload):
    """Thread-safe padded command write to the current device."""
    dev = _device
    if dev is None:
        return False
    try:
        with _write_lock:
            dev.write(pad(*payload))
        return True
    except Exception:
        return False


def set_profile(n):
    send_cmd(0x0F, 0x07, n)          # device will reply to the periodic get-profile


def rumble(left, right):
    send_cmd(0x0F, 0x20, 0x66, 0x55, left, right)


def rumble_test():
    def run():
        rumble(0xC0, 0xC0)
        time.sleep(0.4)
        rumble(0x00, 0x00)
    threading.Thread(target=run, daemon=True).start()


def write_reg(bank, addr, data):
    """Thread-safe register write, chunked to fit the 64-byte report."""
    i = 0
    while i < len(data):
        chunk = data[i:i + 48]
        a = addr + i
        if not send_cmd(0x0F, 0x03, bank, (a >> 8) & 0xFF, a & 0xFF,
                        len(chunk), *chunk):
            return False
        time.sleep(0.02)
        i += 48
    return True


# --- register READ request/response ----------------------------------------
# The reader thread owns the hid handle, so register reads can't be done
# synchronously from another thread. Instead callers QUEUE reads here; the
# reader thread pumps them (one in flight at a time, resending on timeout) and
# stores replies, which callers poll via reg_result().
_read_lock = threading.Lock()
_read_q = collections.deque()      # pending (bank, addr, length)
_read_results = {}                 # (bank, addr) -> list[int]
_inflight = None                   # {'key', 'cmd', 't'} or None


def request_regs(reqs):
    """Queue a batch of (bank, addr, length) reads, clearing their old results
    so a caller can tell fresh values from stale ones."""
    with _read_lock:
        for bank, addr, length in reqs:
            _read_results.pop((bank, addr), None)
            _read_q.append((bank, addr, length))


def reg_result(bank, addr):
    """Latest bytes read at (bank, addr), or None if not yet available."""
    with _read_lock:
        return _read_results.get((bank, addr))


def store_reg_result(bank, addr, data):
    """Called by the reader thread when a 0x10 0x05 reply arrives."""
    global _inflight
    with _read_lock:
        _read_results[(bank, addr)] = data
        if _inflight is not None and _inflight['key'] == (bank, addr):
            _inflight = None


def pump_reads():
    """Run from the reader thread between device reads: keep exactly one
    register read in flight, resending if a reply is dropped (the controller
    drops back-to-back commands)."""
    global _inflight
    now = time.time()
    cmd = None
    with _read_lock:
        if _inflight is not None:
            if now - _inflight['t'] > 0.25:      # timed out -> resend
                _inflight['t'] = now
                cmd = _inflight['cmd']
        elif _read_q:
            bank, addr, length = _read_q.popleft()
            cmd = (0x0F, 0x04, bank, (addr >> 8) & 0xFF, addr & 0xFF, length)
            _inflight = {'key': (bank, addr), 'cmd': cmd, 't': now}
    if cmd:
        send_cmd(*cmd)
