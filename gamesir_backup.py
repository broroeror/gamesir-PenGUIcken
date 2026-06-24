"""
GameSir Cyclone 2 - full-setup backup / restore
================================================
Snapshot the entire controller (all 4 config profiles + the lighting bank) to a
JSON file and write it back later as a restore point.

The snapshot is a faithful image of raw register bytes, so restore is just a
sequence of register writes - no per-field interpretation needed. Reads go
through the same async request/poll layer the editor uses (gamesir_control), which
keeps one read in flight at a time, so a full snapshot takes several seconds; the
GUI shows progress via the on_progress callback.

Each entry is labelled with a human-readable name (so the file is browsable) and
keeps its raw register address + bytes (so restore stays exact). JSON shape:
  { "schema": 2, "device": "...", "exported": "<iso>",
    "profiles": { "1": { "Vibration L": {"addr": "0x0020", "bytes": [75]}, ... }, ... },
    "lighting": { "active_slot": {"addr": "0x0000", "bytes": [n]},
                  "slots":  { "0": {"addr": "0x0001", "bytes": [124 bytes]}, ... },
                  "power":  { "Audio reactive": {"addr": "0x026d", "bytes": [0]}, ... } } }

Restore reads both this schema and the older schema-1 (addr-keyed raw bytes).
"""

import json
import threading
import time
from datetime import datetime

import gamesir_control as control
import gamesir_config as cfg
import gamesir_led as led

SCHEMA = 2
DEVICE = 'GameSir Cyclone 2'
PROFILES = (1, 2, 3, 4)
LED_SLOTS = (0, 1, 2, 3, 4)
POWER_ADDRS = (led.AUDIO_REACTIVE, led.PICKUP_WAKE, led.SLEEP_TIMEOUT)
POWER_NAMES = {
    led.AUDIO_REACTIVE: 'Audio reactive',
    led.PICKUP_WAKE: 'Pick-up to wake',
    led.SLEEP_TIMEOUT: 'Sleep timeout (min)',
}

# How long to wait for every queued read to land before giving up. A full
# snapshot is ~180 sequential reads and the controller drops back-to-back
# commands (so some get resent), so allow generous headroom.
READ_TIMEOUT = 60.0


def _profile_fields():
    """(addr, length) snapshotted per profile bank: every editor field plus the
    button-remap records."""
    return list(cfg.READ_FIELDS) + [(addr, 2) for _, addr in cfg.REMAP_SLOTS]


def _all_requests():
    """Every (bank, addr, length) read needed for a full snapshot."""
    reqs = []
    for prof in PROFILES:
        for addr, ln in _profile_fields():
            reqs.append((prof, addr, ln))
    reqs.append((led.LED_BANK, 0x0000, 1))                 # active-slot selector
    for slot in LED_SLOTS:
        reqs += led.record_read_fields(slot)               # full 124-byte records
    for addr in POWER_ADDRS:
        reqs.append((led.LED_BANK, addr, 1))
    return reqs


def export_async(path, on_progress=None, on_done=None):
    """Queue every snapshot read, wait for the replies, build the JSON image and
    write it to `path`. Runs on a daemon thread. on_progress(done, total) fires as
    replies arrive; on_done(ok, message) fires once at the end."""
    reqs = _all_requests()
    keys = [(bank, addr) for bank, addr, _ln in reqs]
    total = len(keys)

    def run():
        control.request_regs(reqs)
        deadline = time.time() + READ_TIMEOUT
        while time.time() < deadline:
            done = sum(control.reg_result(b, a) is not None for b, a in keys)
            if on_progress:
                on_progress(done, total)
            if done >= total:
                break
            time.sleep(0.1)

        vals = {(b, a): control.reg_result(b, a) for b, a in keys}
        missing = [k for k, v in vals.items() if v is None]
        if missing:
            if on_done:
                on_done(False, f'Timed out reading {len(missing)}/{total} registers '
                               '(is the controller connected and in Xbox mode?)')
            return
        try:
            with open(path, 'w') as fh:
                json.dump(_build(vals), fh, indent=2)
        except OSError as e:
            if on_done:
                on_done(False, f'Could not write file: {e}')
            return
        if on_done:
            on_done(True, f'Saved snapshot to {path}')

    threading.Thread(target=run, daemon=True).start()


def _entry(addr, byts):
    """A labelled backup entry: keeps the raw register address + bytes so restore
    stays exact, while the dict key (the field name) makes the file readable."""
    return {'addr': f'0x{addr:04x}', 'bytes': byts}


def _build(vals):
    """Assemble the JSON-serialisable snapshot dict from {(bank, addr): bytes}."""
    profiles = {}
    for prof in PROFILES:
        profiles[str(prof)] = {cfg.field_name(addr): _entry(addr, vals[(prof, addr)])
                               for addr, _ln in _profile_fields()}

    led_vals = {a: vals[(led.LED_BANK, a)] for b, a in vals if b == led.LED_BANK}
    slots = {str(slot): _entry(led.record_addr(slot), led.stitch_record(slot, led_vals))
             for slot in LED_SLOTS}
    power = {POWER_NAMES[addr]: _entry(addr, vals[(led.LED_BANK, addr)])
             for addr in POWER_ADDRS}
    lighting = {
        'active_slot': _entry(0x0000, vals[(led.LED_BANK, 0x0000)]),
        'slots': slots,
        'power': power,
    }
    return {
        'schema': SCHEMA,
        'device': DEVICE,
        'exported': datetime.now().isoformat(timespec='seconds'),
        'profiles': profiles,
        'lighting': lighting,
    }


def load(path):
    """Read and validate a snapshot file. Returns the parsed dict, or raises
    ValueError on a bad/incompatible file. Accepts the current schema and the
    older schema-1 (addr-keyed) layout."""
    with open(path) as fh:
        data = json.load(fh)
    if not isinstance(data, dict) or data.get('schema') not in (1, SCHEMA):
        raise ValueError(f'Not a {DEVICE} backup (schema 1 or {SCHEMA})')
    if 'profiles' not in data or 'lighting' not in data:
        raise ValueError('Backup is missing profiles/lighting')
    return data


def _writes_from(data):
    """Flatten a loaded snapshot (either schema) into ordered (bank, addr, bytes)
    writes. The active-slot selector is written last so a restore lands on the
    same slot the snapshot had active."""
    writes = []
    lighting = data['lighting']
    if data.get('schema') == 1:
        # schema 1: profile fields keyed by hex addr -> raw bytes
        for prof_s, fields in data['profiles'].items():
            for addr_s, byts in fields.items():
                writes.append((int(prof_s), int(addr_s, 16), list(byts)))
        for slot_s, byts in lighting['records'].items():
            writes.append((led.LED_BANK, led.record_addr(int(slot_s)), list(byts)))
        for addr_s, byts in lighting['power'].items():
            writes.append((led.LED_BANK, int(addr_s, 16), list(byts)))
        writes.append((led.LED_BANK, 0x0000, list(lighting['selector'])))
    else:
        # schema 2: labelled entries {name: {addr, bytes}}; addr is authoritative
        for prof_s, fields in data['profiles'].items():
            for ent in fields.values():
                writes.append((int(prof_s), int(ent['addr'], 16), list(ent['bytes'])))
        for ent in lighting['slots'].values():
            writes.append((led.LED_BANK, int(ent['addr'], 16), list(ent['bytes'])))
        for ent in lighting['power'].values():
            writes.append((led.LED_BANK, int(ent['addr'], 16), list(ent['bytes'])))
        sel = lighting['active_slot']
        writes.append((led.LED_BANK, int(sel['addr'], 16), list(sel['bytes'])))
    return writes


# Restore writes are split into <=48-byte units so a write chunk and its
# read-back share the same (addr, length) - the controller's read replies top out
# around 56 bytes, so a 124-byte lighting record can't be verified in one read.
WRITE_CHUNK = 48
MAX_PASSES = 3                 # write -> verify -> re-write dropped, up to N times
CRITICAL_BANKS = (0x01, led.LED_BANK)   # active profile + lighting: must verify


def _expand_units(writes):
    """Split (bank, addr, bytes) writes into <=WRITE_CHUNK-byte (bank, addr, bytes)
    units so each can be written and read back at the same address+length."""
    units = []
    for bank, addr, byts in writes:
        for i in range(0, len(byts), WRITE_CHUNK):
            units.append((bank, addr + i, list(byts[i:i + WRITE_CHUNK])))
    return units


def apply_backup(data, on_progress=None, on_done=None):
    """Write a loaded snapshot back to the controller on a daemon thread, then
    READ IT BACK and re-write whatever didn't take - the controller silently
    drops back-to-back commands, so a blind write loses blocks (e.g. a lighting
    record). on_progress(done, total) fires as blocks confirm; on_done(ok, message)
    fires once.

    Banks 0x02-0x04 are the stored (non-active) profiles, which the controller
    appears to expose read-only; they're written best-effort but not required to
    confirm, so they don't mask a genuine failure in the active profile/lighting."""
    units = _expand_units(_writes_from(data))
    total = len(units)

    def run():
        pending = list(units)
        confirmed = []
        for _pass in range(MAX_PASSES):
            # 1. (re)write the not-yet-confirmed units (write_reg paces ~20ms each)
            for bank, addr, byts in pending:
                control.write_reg(bank, addr, byts)

            # 2. read them all back through the reader thread's request/poll layer
            control.request_regs([(b, a, len(by)) for b, a, by in pending])
            keys = [(b, a) for b, a, _by in pending]
            deadline = time.time() + READ_TIMEOUT
            while time.time() < deadline:
                got = sum(control.reg_result(b, a) is not None for b, a in keys)
                if on_progress:
                    on_progress(len(confirmed) + got, total)
                if got >= len(keys):
                    break
                time.sleep(0.1)

            # 3. keep only the units whose read-back doesn't match what we wrote
            still = []
            for bank, addr, byts in pending:
                back = control.reg_result(bank, addr)
                if back is not None and list(back) == byts:
                    confirmed.append((bank, addr, byts))
                else:
                    still.append((bank, addr, byts))
            pending = still
            if on_progress:
                on_progress(len(confirmed), total)
            if not pending:
                break

        if on_done:
            crit_fail = [u for u in pending if u[0] in CRITICAL_BANKS]
            if not pending:
                on_done(True, f'Restored and verified all {total} register blocks.')
            elif not crit_fail:
                on_done(True, f'Restored & verified the active profile + lighting '
                              f'({len(confirmed)}/{total}). The {len(pending)} '
                              'unconfirmed blocks are the stored profiles 2-4 '
                              '(read-only on this controller) - not used live.')
            else:
                on_done(False, f'Restored {len(confirmed)}/{total}; {len(crit_fail)} '
                               'active-profile/lighting blocks were dropped and '
                               'could not be confirmed - click Restore again.')

    threading.Thread(target=run, daemon=True).start()
