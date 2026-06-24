"""
GameSir Cyclone 2 - GUI
=======================
The view layer only: window/panel construction, per-frame widget updates, and
the button callbacks. All controller I/O lives in the sibling modules:
  gs_state       - the shared live `state` dict
  gamesir_reader - background connect/read loop that fills `state`
  gamesir_control- command + register read/write (profile, rumble, write_reg)
  gamesir_led    - lighting domain (set_lights, slot select, factory restore)
  gamesir_config - per-profile config register map (deadzones/curves/etc.)

Run in Xbox mode:  sudo python3 gamesir_gui.py
"""

import colorsys
import json
import os
import random
import threading
from datetime import datetime

import dearpygui.dearpygui as dpg

from gs_state import state, EXTRA_BTNS
import gamesir_control as control
import gamesir_led as led
import gamesir_config as cfg
import gamesir_backup as backup
import gamesir_kf_cache as kf_cache
import gamesir_kwin as kwin
import gamesir_mousegrab as mousegrab
from gamesir_reader import read_controller
from gamesir_window import place_on_screen

__version__ = '0.1.0-alpha.1'   # known-good baseline; see TODO.md for the roadmap

# Which profile bank we're waiting on register reads for (None = not loading).
_config_loading = [None]
# Profile whose settings are currently shown in the editor (drives auto-load).
_loaded_profile = [None]
# Lighting readback: slot whose record reads are in flight (None = not loading),
# and the slot currently reflected in the panel (drives auto-load on slot change).
_led_loading = [None]
_loaded_led_slot = [None]
# Custom keyframe editor, PER color profile (lighting slot 0..3). Each slot keeps
# its own NUM_FRAMES-long frame buffer (each frame = one (r,g,b) per light, LIGHTS
# order) and an active keyframe count (1..8). The swatches only show the frame in
# _kf_current of the slot in _kf_slot; switching frames saves the swatches first.
# Slots are loaded from the controller on switch (see update_keyframes).
_kf_frames = {s: [[[0, 128, 255] for _ in led.LIGHTS] for _ in range(led.NUM_FRAMES)]
              for s in range(4)}
_kf_count = {s: led.NUM_FRAMES for s in range(4)}
_kf_current = [0]      # selected keyframe index within the shown slot
_kf_slot = [0]         # the slot the editor currently reflects
# Keyframe readback: slot whose record reads are in flight, and the last slot
# auto-loaded into the editor (drives the load on slot change).
_kf_loading = [None]
_loaded_kf_slot = [None]
_kf_playing = [True]   # lighting animation play/pause state (device default: running)
# Queued, not-yet-pushed edits for the shown profile:
#   addr -> {'data': [int], 'label': str, 'display': str}
# Keyed by addr so re-editing a field just overwrites its pending value.
_pending = {}

FONT_PATH = '/usr/share/fonts/TTF/DejaVuSans.ttf'

ON = (0, 200, 80, 255)
OFF = (60, 60, 60, 255)
CONN_STATUS = {
    True: ('Connected', (0, 200, 80, 255)),
    False: ('Not found', (220, 60, 60, 255)),
    None: ('Connecting...', (200, 180, 0, 255)),
}


# --- small view helpers ----------------------------------------------------

def stick_pos(value):
    return (value - 128) / 128


def battery_color(pct):
    if pct > 50:
        return (0, 200, 80, 255)
    if pct > 20:
        return (220, 180, 0, 255)
    return (220, 60, 60, 255)


def centered_text(cx, cy, label, size=14):
    # dpg.get_text_size() only works after the first rendered frame, too late for
    # build-time layout, so estimate glyph width instead.
    w = len(label) * size * 0.55
    h = size * 1.15
    dpg.draw_text((cx - w / 2, cy - h / 2), label, size=size)


# --- lighting widget callbacks ---------------------------------------------

def _picker_rgb(tag):
    """Read a color_edit widget as 0-255 ints (DPG may return 0-1 or 0-255)."""
    col = dpg.get_value(tag)[:3]
    if max(col) <= 1.0:
        return [int(round(c * 255)) for c in col]
    return [int(round(c)) for c in col]


def _current_colors():
    return [_picker_rgb(f'led_color_{i}') for i in range(len(led.LIGHTS))]


def apply_led():
    colors = _current_colors()
    bri = dpg.get_value('led_bright')
    threading.Thread(target=lambda: led.set_lights(colors, bri), daemon=True).start()


def led_off():
    colors = _current_colors()
    threading.Thread(target=lambda: led.set_lights(colors, 0), daemon=True).start()


def led_fill_all():
    """Copy the first light's color into every swatch (quick solid color)."""
    col = dpg.get_value('led_color_0')
    for i in range(1, len(led.LIGHTS)):
        dpg.set_value(f'led_color_{i}', col)


def apply_pattern(name):
    """Apply a named effect preset (Flow/Rainbow/...) to the active slot at the
    current brightness. The custom per-light swatches/Apply are unaffected."""
    if not name:
        return
    bri = dpg.get_value('led_bright')
    # Each effect carries its own default speed (record +2); reflect it so the
    # Speed slider isn't stale. set_value doesn't fire the slider's callback.
    dpg.set_value('led_speed', led.speed_ui(led.PATTERNS[name][led.REC_SPEED_OFF]))
    threading.Thread(target=lambda: led.set_pattern(name, bri), daemon=True).start()


def activate_slot(n):
    """Make lighting slot n the active one (so Apply edits it / it's displayed)."""
    state['led_slot'] = n     # optimistic; the periodic poll confirms it
    threading.Thread(target=lambda: led.select_slot(n), daemon=True).start()


def restore_presets():
    threading.Thread(target=led.restore_factory, daemon=True).start()


def _led_async(fn, *args):
    """Run a lighting write off the UI thread (every led.* write is fire-and-forget)."""
    threading.Thread(target=lambda: fn(*args), daemon=True).start()


# --- custom keyframe editor callbacks --------------------------------------

def _kf_store_current():
    """Save the on-screen swatches into the shown slot's current keyframe."""
    _kf_frames[_kf_slot[0]][_kf_current[0]] = [_picker_rgb(f'kf_color_{i}')
                                               for i in range(len(led.LIGHTS))]


def _kf_load(n):
    """Show keyframe n of the shown slot in the swatches."""
    for i, col in enumerate(_kf_frames[_kf_slot[0]][n]):
        dpg.set_value(f'kf_color_{i}', (*col, 255))


def _kf_refresh_controls():
    """Rebuild the frame selector to show only the active count, and sync the
    count label + the Add/Remove button enabled state (min 1, max NUM_FRAMES)."""
    count = _kf_count[_kf_slot[0]]
    if _kf_current[0] >= count:
        _kf_current[0] = count - 1
    dpg.configure_item('kf_frame', items=[str(i + 1) for i in range(count)])
    dpg.set_value('kf_frame', str(_kf_current[0] + 1))
    dpg.set_value('kf_count_text', f'{count} / {led.NUM_FRAMES} keyframes  (slot {_kf_slot[0]})')
    dpg.configure_item('kf_add_btn', enabled=count < led.NUM_FRAMES)
    dpg.configure_item('kf_remove_btn', enabled=count > 1)


def kf_select_frame(n):
    """Switch the editor to keyframe n, saving edits to the one we're leaving."""
    _kf_store_current()
    _kf_current[0] = n
    _kf_load(n)


def _kf_default_frame():
    """A fresh keyframe = each light at its default color."""
    return [list(default) for _, default in led.LIGHTS]


def kf_add_frame():
    """Append a new keyframe (a fresh default color, ready to edit) up to
    NUM_FRAMES, and jump to it. A new keyframe starts blank rather than copying
    the current one, so it's obvious you're editing a distinct frame."""
    slot = _kf_slot[0]
    if _kf_count[slot] >= led.NUM_FRAMES:
        return
    _kf_store_current()
    _kf_frames[slot][_kf_count[slot]] = _kf_default_frame()
    _kf_count[slot] += 1
    _kf_current[0] = _kf_count[slot] - 1
    _kf_refresh_controls()
    _kf_load(_kf_current[0])


def kf_remove_frame():
    """Remove the current keyframe (at least 1 always remains)."""
    slot = _kf_slot[0]
    if _kf_count[slot] <= 1:
        return
    _kf_store_current()
    frames = _kf_frames[slot]
    del frames[_kf_current[0]]
    frames.append([[0, 128, 255] for _ in led.LIGHTS])   # keep the buffer NUM_FRAMES long
    _kf_count[slot] -= 1
    _kf_refresh_controls()
    _kf_load(_kf_current[0])


def kf_copy_to_all():
    """Copy the current keyframe's colors into every keyframe of this slot."""
    _kf_store_current()
    slot = _kf_slot[0]
    cur = _kf_frames[slot][_kf_current[0]]
    for f in range(led.NUM_FRAMES):
        _kf_frames[slot][f] = [list(c) for c in cur]


def _random_vivid_rgb():
    """A random fully-saturated, full-brightness color (random hue, S=V=1)."""
    r, g, b = colorsys.hsv_to_rgb(random.random(), 1.0, 1.0)
    return [round(r * 255), round(g * 255), round(b * 255)]


def kf_randomize():
    """Give all 4 lights a fresh random vivid color on the current keyframe,
    then show it in the swatches (still needs Apply to push to the device)."""
    _kf_frames[_kf_slot[0]][_kf_current[0]] = [_random_vivid_rgb() for _ in led.LIGHTS]
    _kf_load(_kf_current[0])


def apply_keyframes():
    """Write the shown slot's keyframes (its active count) to that slot at the
    current speed/brightness - i.e. save them to the active color profile."""
    _kf_store_current()
    slot = _kf_slot[0]
    count = _kf_count[slot]
    speed = dpg.get_value('led_speed')
    bri = dpg.get_value('led_bright')
    frames = [_kf_frames[slot][i] for i in range(count)]
    # Mirror the exact count+colors locally as a backup. The device now stores the
    # count in record byte 0 (so decode_record recovers it), but the cache keeps an
    # authoritative copy across profile switches (see gamesir_kf_cache).
    kf_cache.save(slot, frames, count)
    threading.Thread(target=lambda: led.set_keyframes(frames, speed, bri, slot),
                     daemon=True).start()


def kf_toggle_playback():
    """Pause/resume the controller's lighting animation (vendor command 0x0d,
    captured from the official app's play/pause button). Passes the editor's
    current keyframe (1-based) so Pause freezes on the frame you're viewing
    instead of snapping back to frame 1 (see led.set_playback / capture 20).
    Updates the button label to reflect the new state."""
    _kf_playing[0] = not _kf_playing[0]
    playing = _kf_playing[0]
    dpg.set_item_label('kf_playpause_btn', 'Pause' if playing else 'Play')
    _led_async(led.set_playback, playing, _kf_current[0] + 1)


def load_keyframes(slot):
    """Queue a full record read for `slot` so its stored keyframes can be decoded
    into the editor (update_keyframes finishes the load when the chunks land)."""
    control.request_regs(led.record_read_fields(slot))
    _kf_loading[0] = slot


def update_keyframes():
    """Auto-load a slot's stored keyframes into the editor whenever the active
    lighting slot changes (mirrors the lighting auto-load). Switching slots
    abandons any keyframe edits not yet pushed via Apply animation."""
    slot = state['led_slot']
    if slot is not None and 0 <= slot <= 3 \
            and slot != _loaded_kf_slot[0] and _kf_loading[0] is None:
        _loaded_kf_slot[0] = slot
        load_keyframes(slot)

    slot = _kf_loading[0]
    if slot is None:
        return
    vals = {addr: control.reg_result(bank, addr)
            for bank, addr, _ln in led.record_read_fields(slot)}
    if any(v is None for v in vals.values()):
        return                          # still waiting on chunk replies
    _kf_loading[0] = None
    record = led.stitch_record(slot, vals)
    if record is None:
        return
    decoded = led.decode_record(record)
    _kf_slot[0] = slot
    if decoded['type'] == led.KEYFRAME_TYPE:
        # A palette-engine record (custom animation or a preset - same 0x05 engine).
        # The device stores the keyframe count in byte 0, so decode recovers it; we
        # still prefer the local cache when it matches the slot (authoritative exact
        # colors), otherwise use what the device reports.
        cached = kf_cache.get(slot)
        if cached and kf_cache.matches(cached[1], decoded['frames']):
            count, frames = cached[0], [[list(c) for c in fr] for fr in cached[1]]
            note = ''
        else:
            count = decoded['count']
            frames = [[list(c) for c in decoded['frames'][i]] for i in range(count)]
            note = ('' if cached is None else
                    'Loaded from the device (the saved keyframe count no longer '
                    'matches this slot).')
        # Pad the unused slots with a default color so 'Add' reveals clean frames,
        # not stale palette bytes left over from a previous effect.
        while len(frames) < led.NUM_FRAMES:
            frames.append(_kf_default_frame())
        _kf_frames[slot] = frames
        _kf_count[slot] = count
        dpg.set_value('kf_profile_note', note)
    else:
        # The slot holds a built-in preset effect (Rainbow/Pulse/...), which is
        # NOT a keyframe sequence. Start the editor from a clean single frame;
        # editing + Apply converts the profile into a custom animation.
        _kf_frames[slot] = [_kf_default_frame() for _ in range(led.NUM_FRAMES)]
        _kf_count[slot] = 1
        dpg.set_value('kf_profile_note',
                      f'This profile holds a preset effect (type 0x{decoded["type"]:02x}), '
                      'not custom keyframes. Edit and Apply to make a custom animation.')
    _kf_current[0] = 0
    _kf_refresh_controls()
    _kf_load(0)


# --- config editor callbacks -----------------------------------------------
# Edits target the SELECTED profile's own bank (profile 1..4 -> bank 0x01..0x04).
# Edits do NOT write immediately: they're collected in `_pending` and only sent
# (via Review & push) once the user confirms. Setting a widget value in code does
# NOT fire its callback, so auto-load populates widgets without queuing edits.

def queue_change(addr, data, label, display):
    """Record an edit to `addr` for the shown profile, pending user confirmation.
    `label`/`display` are the human-readable field name and new value for the
    review dialog. No-op when no profile is selected."""
    if cfg.profile_bank(state['profile']) is None:
        return
    _pending[addr] = {'data': list(data), 'label': label, 'display': str(display)}
    _refresh_pending()


def _refresh_pending():
    """Sync the 'unsaved changes' indicator and the Review/Discard button states."""
    n = len(_pending)
    dpg.set_value('cfg_pending_text',
                  f'{n} unsaved change(s)' if n else 'No pending changes')
    dpg.configure_item('cfg_pending_text',
                       color=(220, 180, 0, 255) if n else (130, 130, 130, 255))
    for tag in ('cfg_review_btn', 'cfg_discard_btn'):
        dpg.configure_item(tag, enabled=bool(n))


def discard_pending():
    _pending.clear()
    _refresh_pending()


def open_review():
    """Populate and show the modal listing every queued change for confirmation."""
    if cfg.profile_bank(state['profile']) is None or not _pending:
        return
    dpg.delete_item('review_list', children_only=True)
    dpg.set_value('review_header',
                  f'Push {len(_pending)} change(s) to profile {state["profile"]}?')
    for addr in sorted(_pending):
        rec = _pending[addr]
        dpg.add_text(f"  - {rec['label']}: {rec['display']}", parent='review_list')
    dpg.configure_item('review_modal', show=True)


def apply_pending():
    """Write every queued change to the selected profile's bank, then clear."""
    bank = cfg.profile_bank(state['profile'])
    dpg.configure_item('review_modal', show=False)
    if bank is None:
        return
    changes = [(addr, rec['data']) for addr, rec in _pending.items()]

    def run():
        for addr, data in changes:
            control.write_reg(bank, addr, data)
    threading.Thread(target=run, daemon=True).start()
    _pending.clear()
    _refresh_pending()


def _load_addrs():
    """Every (addr, length) the editor reads: scalar/curve fields + remap slots."""
    return list(cfg.READ_FIELDS) + [(addr, 2) for _, addr in cfg.REMAP_SLOTS]


def load_config():
    """Queue reads of every editor field against the selected profile's bank;
    the update loop populates the widgets once the replies land."""
    bank = cfg.profile_bank(state['profile'])
    if bank is None:
        return
    control.request_regs([(bank, addr, ln) for addr, ln in _load_addrs()])
    _config_loading[0] = bank


# --- custom curve editor (per stick/trigger) -------------------------------
# Each editor has three draggable control points and matching numeric inputs,
# kept in sync. Any edit selects 'Custom' for that input and queues the full
# 10-byte block. `pfx` namespaces the widget tags (st/rs/lt/rt).

def _curve_read_drags(pfx):
    return [tuple(dpg.get_value(f'cfg_{pfx}_drag{n}')[:2]) for n in range(3)]


def _curve_read_inputs(pfx):
    return [(dpg.get_value(f'cfg_{pfx}_cx{n}'), dpg.get_value(f'cfg_{pfx}_cy{n}'))
            for n in range(3)]


def _curve_norm(pts):
    """Clamp to 0..255 and sort by x so the curve stays left-to-right monotonic."""
    pts = [(max(0, min(255, int(round(x)))), max(0, min(255, int(round(y)))))
           for x, y in pts]
    pts.sort(key=lambda p: p[0])
    return pts


def _curve_set_widgets(pfx, pts):
    """Write normalised points into the drag handles, numeric inputs and the
    preview line. set_value does not fire callbacks, so this won't re-queue."""
    for n, (x, y) in enumerate(pts):
        dpg.set_value(f'cfg_{pfx}_drag{n}', (x, y))
        dpg.set_value(f'cfg_{pfx}_cx{n}', x)
        dpg.set_value(f'cfg_{pfx}_cy{n}', y)
    xs = [0] + [x for x, _ in pts] + [255]
    ys = [0] + [y for _, y in pts] + [255]
    dpg.set_value(f'cfg_{pfx}_curveline', [xs, ys])


def _curve_load(pfx, pts):
    """Show stored points in the editor without queuing a change."""
    _curve_set_widgets(pfx, _curve_norm(pts))


def _curve_commit(pfx, addr, grp, pts):
    pts = _curve_norm(pts)
    _curve_set_widgets(pfx, pts)
    dpg.set_value(f'cfg_{pfx}_curve', 'Custom')        # editing implies Custom
    queue_change(addr, cfg.custom_curve_block(pts), f'{grp} curve', 'Custom (drawn)')


def curve_from_drag(pfx, addr, grp):
    _curve_commit(pfx, addr, grp, _curve_read_drags(pfx))


def curve_from_input(pfx, addr, grp):
    _curve_commit(pfx, addr, grp, _curve_read_inputs(pfx))


def curve_combo_changed(pfx, addr, grp, name):
    """Combo selection: a preset queues its block; 'Custom' queues the editor's
    current control points (a complete definition, not just the type byte)."""
    if name == 'Custom':
        queue_change(addr, cfg.custom_curve_block(_curve_norm(_curve_read_inputs(pfx))),
                     f'{grp} curve', 'Custom')
    else:
        queue_change(addr, cfg.curve_block(name), f'{grp} curve', name)


def _load_curve_widget(pfx, block):
    """Set a curve combo from a stored 10-byte block; if it's a custom curve,
    load its control points into the editor too."""
    dpg.set_value(f'cfg_{pfx}_curve', cfg.CURVE_ITEMS[cfg.curve_index(block[0])])
    if block and block[0] == cfg.CUSTOM_TYPE:
        _curve_load(pfx, cfg.curve_points(block))


def _populate_stick(pfx, g, gb, traj, dz_min, dz_max, adz_min, adz_max, curve):
    """Set one stick's widgets (LS or RS share an identical layout). `g` reads a
    scalar byte; `gb` reads a field's full block (for the curve points)."""
    dpg.set_value(f'cfg_{pfx}_traj', cfg.TRAJ[cfg.enum_index(g(traj), cfg.TRAJ)][0])
    dpg.set_value(f'cfg_{pfx}_dz_min', g(dz_min))
    dpg.set_value(f'cfg_{pfx}_dz_max', g(dz_max))
    dpg.set_value(f'cfg_{pfx}_adz_min', g(adz_min))
    dpg.set_value(f'cfg_{pfx}_adz_max', g(adz_max))
    _load_curve_widget(pfx, gb(curve))


def _populate_config(bank, vals):
    g = lambda addr: vals[addr][0]
    gb = lambda addr: vals[addr]            # full block (for curve points)
    dpg.set_value('cfg_vib_l', g(cfg.VIB_L))
    dpg.set_value('cfg_vib_r', g(cfg.VIB_R))
    dpg.set_value('cfg_poll', cfg.POLL_RATES[min(g(cfg.POLL_RATE), 2)])
    dpg.set_value('cfg_lt_dz_min', g(cfg.LT_DZ_MIN))
    dpg.set_value('cfg_lt_dz_max', g(cfg.LT_DZ_MAX))
    dpg.set_value('cfg_lt_adz_min', g(cfg.LT_ADZ_MIN))
    dpg.set_value('cfg_lt_adz_max', g(cfg.LT_ADZ_MAX))
    dpg.set_value('cfg_lt_hair', cfg.HAIR_MODES[cfg.enum_index(g(cfg.LT_HAIR), cfg.HAIR_MODES)][0])
    _load_curve_widget('lt', gb(cfg.LT_CURVE))
    dpg.set_value('cfg_rt_dz_min', g(cfg.RT_DZ_MIN))
    dpg.set_value('cfg_rt_dz_max', g(cfg.RT_DZ_MAX))
    dpg.set_value('cfg_rt_adz_min', g(cfg.RT_ADZ_MIN))
    dpg.set_value('cfg_rt_adz_max', g(cfg.RT_ADZ_MAX))
    dpg.set_value('cfg_rt_hair', cfg.HAIR_MODES[cfg.enum_index(g(cfg.RT_HAIR), cfg.HAIR_MODES)][0])
    _load_curve_widget('rt', gb(cfg.RT_CURVE))
    _populate_stick('st', g, gb, cfg.ST_TRAJ, cfg.ST_DZ_MIN, cfg.ST_DZ_MAX,
                    cfg.ST_ADZ_MIN, cfg.ST_ADZ_MAX, cfg.ST_CURVE)
    _populate_stick('rs', g, gb, cfg.RS_TRAJ, cfg.RS_DZ_MIN, cfg.RS_DZ_MAX,
                    cfg.RS_ADZ_MIN, cfg.RS_ADZ_MAX, cfg.RS_CURVE)
    # Remap: each slot's [enable, code] -> its combo
    for _name, addr in cfg.REMAP_SLOTS:
        rec = vals[addr]
        dpg.set_value(f'remap_{addr:04x}',
                      cfg.remap_target_name(rec[0], rec[1] if len(rec) > 1 else 0))


# --- backup / restore callbacks --------------------------------------------
# Export/restore run on worker threads (gamesir_backup). DearPyGui widgets are
# only touched from the main thread, so the worker callbacks just stash a status
# string here and update_backup() pushes it to the label each frame.

_backup_status = ['']
_restore_data = [None]
_restore_refresh = [False]   # set on a worker thread; consumed on the GUI thread


def _set_backup_status(msg):
    _backup_status[0] = msg


def _post_restore_refresh():
    """After a JSON restore overwrites the controller, drop all cached and
    auto-loaded editor state so every panel re-reads the freshly-written values
    from the device. Without this the editor keeps showing - and the next push
    re-writes - the pre-restore state, and the keyframe cache would mask the
    restored keyframe count. Runs on the GUI thread (touches dpg state)."""
    kf_cache.clear()
    if _pending:
        discard_pending()
    _loaded_profile[0] = _config_loading[0] = None
    _loaded_led_slot[0] = _led_loading[0] = None
    _loaded_kf_slot[0] = _kf_loading[0] = None


def _user_home():
    """The invoking user's home directory. Under `sudo`, os.path.expanduser('~')
    resolves to /root, which is where backups silently disappeared to; recover
    the real user's home from SUDO_USER so saved files land somewhere findable."""
    home = os.path.expanduser('~')
    sudo_user = os.environ.get('SUDO_USER')
    if sudo_user and home == '/root':
        cand = f'/home/{sudo_user}'
        if os.path.isdir(cand):
            return cand
    return home


def _do_export(path):
    """Snapshot the whole controller to `path` (an absolute file path chosen in
    the save dialog). Reflects the chosen path in the box for reference."""
    dpg.set_value('backup_path', path)
    _set_backup_status('Reading controller...')
    backup.export_async(
        path,
        on_progress=lambda d, t: _set_backup_status(f'Reading registers {d}/{t}...'),
        on_done=lambda ok, msg: _set_backup_status(msg))


def _on_export_pick(sender, app_data):
    """Save-dialog callback: export to the picked path (force a .json suffix)."""
    path = app_data['file_path_name']
    if not path.lower().endswith('.json'):
        path += '.json'
    _do_export(path)


def open_restore(path):
    """Load + validate the chosen JSON file, then show the confirmation modal."""
    try:
        data = backup.load(path)
    except (OSError, ValueError, json.JSONDecodeError) as e:
        _set_backup_status(f'Could not load: {e}')
        return
    dpg.set_value('backup_path', path)
    _restore_data[0] = data
    n_prof = len(data.get('profiles', {}))
    lighting = data.get('lighting', {})
    n_slots = len(lighting.get('slots', lighting.get('records', {})))
    _set_backup_status(f'Loaded {n_prof} profile(s) + {n_slots} lighting slot(s) '
                       f'(exported {data.get("exported", "?")}). Click '
                       '"Write loaded backup to controller" to apply.')
    dpg.configure_item('restore_write_btn', show=True)


def _on_restore_pick(sender, app_data):
    """Open-dialog callback: load the picked file and confirm the restore."""
    open_restore(app_data['file_path_name'])


def do_restore():
    """Write the loaded snapshot back to the controller."""
    dpg.configure_item('restore_write_btn', show=False)
    _set_backup_status('Starting restore...')
    data = _restore_data[0]
    if not data:
        _set_backup_status('Restore failed: no backup loaded - re-pick the file.')
        return

    def done(ok, msg):
        _set_backup_status(msg)
        if ok:
            _restore_refresh[0] = True   # GUI thread re-reads everything next frame

    backup.apply_backup(
        data,
        on_progress=lambda d, t: _set_backup_status(f'Writing {d}/{t}...'),
        on_done=done)


def update_backup():
    msg = _backup_status[0] or 'idle'
    dpg.set_value('backup_status', msg)
    low = msg.lower()
    if 'could not' in low or 'dropped' in low or 'timed out' in low:
        color = (220, 80, 80, 255)           # failure
    elif 'verified' in low or 'saved' in low or 'restored' in low:
        color = (80, 190, 110, 255)          # success
    elif 'writing' in low or 'reading' in low:
        color = (220, 200, 120, 255)         # in progress
    else:
        color = (170, 170, 170, 255)
    dpg.configure_item('backup_status', color=color)
    if _restore_refresh[0]:
        _restore_refresh[0] = False
        _post_restore_refresh()


# --- mouse mode ------------------------------------------------------------
# "Mouse mode" (sticks drive the cursor after a dongle re-pair) is KDE's KWin
# Game Controller plugin. On KDE we toggle that plugin directly (clean, bidirec-
# tional: off = normal gamepad, on = couch-mode cursor control); elsewhere we fall
# back to EVIOCGRAB-suppressing the joystick node.
_mouse_backend = ['grab']                       # 'kwin' or 'grab'
_mousemode_msg = ['', (170, 170, 170, 255)]     # [text, color] for the kwin path


def _set_mouse_status(on):
    if on:
        _mousemode_msg[0] = 'couch mode ON - sticks move the cursor, triggers click'
        _mousemode_msg[1] = (0, 170, 70, 255)
    else:
        _mousemode_msg[0] = 'off - normal gamepad'
        _mousemode_msg[1] = (150, 150, 150, 255)


def _toggle_mouse_kwin(on):
    """Checkbox callback (KDE path): flip the KWin Game Controller plugin."""
    if kwin.set_enabled(on):
        _set_mouse_status(on)
    else:
        _mousemode_msg[0] = "couldn't change the KWin setting"
        _mousemode_msg[1] = (220, 80, 80, 255)


def update_mousegrab():
    """Push the mouse-mode status into the label each frame."""
    if _mouse_backend[0] == 'kwin':
        dpg.set_value('mouse_status', _mousemode_msg[0])
        dpg.configure_item('mouse_status', color=_mousemode_msg[1])
        return
    st = mousegrab.status()                      # EVIOCGRAB fallback (non-KDE)
    if st.startswith('active'):
        text, color = 'mouse mode off (gamepad grabbed from the desktop)', (0, 170, 70, 255)
    elif st == 'no access':
        text, color = "can't open input devices - (re)install the udev rule", (220, 60, 60, 255)
    elif st == 'not found':
        text, color = 'on - waiting for the controller', (150, 150, 150, 255)
    else:
        text, color = '', (150, 150, 150, 255)
    dpg.set_value('mouse_status', text)
    dpg.configure_item('mouse_status', color=color)


# --- per-frame updates -----------------------------------------------------

def update_inputs():
    dpg.set_value('ls_dot', [[stick_pos(state['lx'])], [-stick_pos(state['ly'])]])
    dpg.set_value('rs_dot', [[stick_pos(state['rx'])], [-stick_pos(state['ry'])]])
    dpg.set_value('lt_bar', state['lt'] / 255)
    dpg.set_value('rt_bar', state['rt'] / 255)
    for btn in ('a', 'b', 'x', 'y', 'lb', 'rb', 'view', 'menu', 'ls', 'rs', *EXTRA_BTNS):
        dpg.configure_item(f'btn_{btn}', fill=ON if state[btn] else OFF)
    dpg.set_value('dpad_text', f"D-pad: {state['dpad']}")


def update_status():
    text, color = CONN_STATUS[state['connected']]
    dpg.set_value('conn_text', text)
    dpg.configure_item('conn_text', color=color)

    # Mode awareness. The vendor command channel (everything this app does) only
    # exists in Xbox/XInput mode; in Switch or PlayStation mode the controller
    # re-enumerates as a plain console gamepad and the 0x12 stream goes all-zero
    # (see gamesir_reader). GameSir only supports Xbox mode on PC, so flag any
    # other mode loudly rather than just looking "half-connected".
    if state['connected'] and not state['mode_ok']:
        dpg.set_value('mode_text',
                      'NOT in Xbox mode (controller is in Switch/PlayStation mode). '
                      'GameSir only supports Xbox mode on PC and this app cannot '
                      'control the pad otherwise - hold the GREEN button ~2s to '
                      'return to Xbox mode.')
        dpg.configure_item('mode_text', color=(220, 60, 60, 255))
    elif state['connected'] and state['mode_ok']:
        dpg.set_value('mode_text', 'Xbox mode (vendor control active)')
        dpg.configure_item('mode_text', color=(0, 170, 70, 255))
    else:
        dpg.set_value('mode_text', '')

    # Firmware comes from the connected USB device's bcdDevice. WIRED, that's the
    # controller (e.g. 3.52); over the 2.4GHz DONGLE, the dongle presents its own
    # descriptor, so we read the dongle's firmware instead (e.g. 1.21). Use the
    # cable-connected bit (state['charging']) to say which - only when we have a
    # live 0x12 stream (mode_ok) to trust it.
    fw = state.get('firmware')
    if fw and state['mode_ok']:
        where = 'controller' if state['charging'] else 'dongle'
        dpg.set_value('fw_text', f'Firmware: {fw} ({where})')
    else:
        dpg.set_value('fw_text', f'Firmware: {fw}' if fw else 'Firmware: --')
    dpg.configure_item('fw_text', color=(150, 150, 150, 255) if fw else (140, 140, 140, 255))
    dpg.configure_item('update_note', show=bool(fw))

    # Battery: byte 36 = % (confirmed), byte 35 bit 0 = charging/cable connected.
    pct = max(0, min(100, state['battery']))
    if state['mode_ok']:
        if state['charging']:
            label = f'Battery: {pct}% (full)' if pct >= 99 else f'Battery: {pct}% (charging)'
        else:
            label = f'Battery: {pct}%'
        dpg.set_value('batt_text', label)
        dpg.configure_item('batt_text', color=battery_color(pct))
    else:
        dpg.set_value('batt_text', 'Battery: --')
        dpg.configure_item('batt_text', color=(140, 140, 140, 255))


def load_lighting(slot):
    """Queue reads of the live lighting controls (active slot's speed/brightness +
    the global power settings); update_lighting populates them once they land."""
    control.request_regs(led.read_fields(slot))
    _led_loading[0] = slot


def _populate_lighting(slot, vals):
    """vals: {addr: [bytes]} for led.read_fields(slot). set_value doesn't fire the
    widgets' callbacks, so this won't echo back as a write."""
    rec = 0x0001 + slot * led.LED_REC
    dpg.set_value('led_speed', led.speed_ui(vals[rec + led.REC_SPEED_OFF][0]))
    dpg.set_value('led_bright', vals[rec + led.REC_BRIGHT_OFF][0])
    dpg.set_value('led_audio', bool(vals[led.AUDIO_REACTIVE][0]))
    dpg.set_value('led_pickup', bool(vals[led.PICKUP_WAKE][0]))
    dpg.set_value('led_sleep', led.sleep_label(vals[led.SLEEP_TIMEOUT][0]))


def update_lighting():
    """Auto-load the live lighting controls whenever the active slot changes (via
    the radio OR a physical gesture), then populate once the replies arrive."""
    slot = state['led_slot']
    if slot is not None and 0 <= slot <= 3 \
            and slot != _loaded_led_slot[0] and _led_loading[0] is None:
        _loaded_led_slot[0] = slot
        load_lighting(slot)

    slot = _led_loading[0]
    if slot is None:
        return
    vals = {addr: control.reg_result(bank, addr)
            for bank, addr, _ln in led.read_fields(slot)}
    if any(v is None for v in vals.values()):
        return                          # still waiting on replies
    _populate_lighting(slot, vals)
    _led_loading[0] = None


def update_customization():
    prof = state['profile']
    dpg.set_value('profile_text', f'Profile: {prof}' if prof else 'Profile: -')

    # Active lighting slot: reflect the controller's live selector in the radio
    # (set_value does not fire the callback, so this won't loop).
    slot = state['led_slot']
    if slot is not None and 0 <= slot <= 3:
        dpg.set_value('led_slot_radio', str(slot))
    update_lighting()
    update_keyframes()


def update_config():
    prof = state['profile']
    dpg.set_value('cfg_profile_text',
                  f'Editing profile {prof}' if cfg.profile_bank(prof)
                  else 'Editing profile: - (set/switch a profile)')

    # Auto-load: whenever the selected profile changes (via the GUI buttons OR a
    # physical M + right-stick switch), read that profile's settings into the
    # editor. Switching profiles abandons any unpushed edits for the old one.
    if cfg.profile_bank(prof) is not None and prof != _loaded_profile[0] \
            and _config_loading[0] is None:
        _loaded_profile[0] = prof
        if _pending:
            discard_pending()
        load_config()

    bank = _config_loading[0]
    if not bank:
        return
    vals = {addr: control.reg_result(bank, addr) for addr, _ln in _load_addrs()}
    if any(v is None for v in vals.values()):
        return                          # still waiting on replies
    _populate_config(bank, vals)
    _config_loading[0] = None


def update_gui():
    update_inputs()
    update_status()
    update_customization()
    update_config()
    update_backup()
    update_mousegrab()


# --- panel builders --------------------------------------------------------

def stick_plot(prefix, label):
    with dpg.group():
        dpg.add_text(label)
        with dpg.plot(width=150, height=150, no_title=True, no_menus=True,
                      equal_aspects=True, no_box_select=True):
            dpg.add_plot_axis(dpg.mvXAxis, no_gridlines=True, no_tick_marks=True,
                              no_tick_labels=True, tag=f'{prefix}_xaxis')
            dpg.add_plot_axis(dpg.mvYAxis, no_gridlines=True, no_tick_marks=True,
                              no_tick_labels=True, tag=f'{prefix}_yaxis')
            dpg.add_scatter_series([0], [0], parent=f'{prefix}_yaxis', tag=f'{prefix}_dot')
            dpg.set_axis_limits(f'{prefix}_xaxis', -1.1, 1.1)
            dpg.set_axis_limits(f'{prefix}_yaxis', -1.1, 1.1)


def build_header():
    with dpg.group(horizontal=True):
        dpg.add_text('GameSir Cyclone 2 - Live Input', color=(200, 200, 200))
        dpg.add_spacer(width=120)
        dpg.add_text('Connecting...', tag='conn_text', color=(200, 180, 0, 255))
    with dpg.group(horizontal=True):
        dpg.add_text('Battery: --', tag='batt_text', color=(140, 140, 140, 255))
        dpg.add_spacer(width=20)
        dpg.add_text('Firmware: --', tag='fw_text', color=(140, 140, 140, 255))
        # Read locally from the USB descriptor (bcdDevice); the official app's
        # update check is a Windows-only cloud call we can't act on from Linux
        # (firmware can't be flashed here), so this is informational only.
        with dpg.tooltip('fw_text'):
            dpg.add_text('Firmware version of the connected USB device (bcdDevice).')
            dpg.add_text('Wired = the controller; over the 2.4GHz dongle = the')
            dpg.add_text('dongle (it presents its own descriptor), so the number')
            dpg.add_text('differs between wired and wireless - both are correct.')
            dpg.add_text('Updates are only available through the official GameSir')
            dpg.add_text('app on Windows - https://www.gamesir.hk (support > downloads).')
    dpg.add_text('Updates: via the official GameSir app on Windows (firmware cannot be flashed from Linux)',
                 tag='update_note', color=(110, 110, 110, 255))
    dpg.add_text('', tag='mode_text', color=(220, 60, 60, 255))
    dpg.add_separator()
    dpg.add_spacer(height=8)


def build_input_panel():
    with dpg.group(horizontal=True):
        stick_plot('ls', 'L Stick')
        dpg.add_spacer(width=20)

        # Face buttons (Xbox diamond: Y top, A bottom, X left, B right)
        with dpg.group():
            dpg.add_text('Buttons')
            dpg.add_spacer(height=5)
            with dpg.drawlist(width=120, height=120):
                dpg.draw_circle((60, 20), 14, fill=OFF, tag='btn_y')
                dpg.draw_circle((60, 100), 14, fill=OFF, tag='btn_a')
                dpg.draw_circle((20, 60), 14, fill=OFF, tag='btn_x')
                dpg.draw_circle((100, 60), 14, fill=OFF, tag='btn_b')
                centered_text(60, 20, 'Y', size=16)
                centered_text(60, 100, 'A', size=16)
                centered_text(20, 60, 'X', size=16)
                centered_text(100, 60, 'B', size=16)

        dpg.add_spacer(width=20)
        stick_plot('rs', 'R Stick')

    dpg.add_spacer(height=10)

    with dpg.group(horizontal=True):
        dpg.add_text('LT')
        dpg.add_progress_bar(tag='lt_bar', width=200, default_value=0)
        dpg.add_spacer(width=20)
        dpg.add_text('RT')
        dpg.add_progress_bar(tag='rt_bar', width=200, default_value=0)

    dpg.add_spacer(height=10)

    # Bumpers + system buttons
    with dpg.drawlist(width=540, height=40):
        for label, tag, x in [('LB', 'btn_lb', 30), ('RB', 'btn_rb', 110),
                               ('View', 'btn_view', 210), ('Menu', 'btn_menu', 310),
                               ('LS', 'btn_ls', 400), ('RS', 'btn_rs', 470)]:
            dpg.draw_rectangle((x - 25, 5), (x + 25, 35), fill=OFF, tag=tag)
            centered_text(x, 20, label, size=14)

    dpg.add_spacer(height=8)

    # Extra buttons (from the 0x12 enhanced report, byte 60)
    dpg.add_text('Extra buttons')
    with dpg.drawlist(width=540, height=40):
        for label, tag, x in [('L4', 'btn_l4', 50), ('R4', 'btn_r4', 150),
                               ('M', 'btn_m', 250), ('Home', 'btn_home', 350),
                               ('Share', 'btn_share', 460)]:
            dpg.draw_rectangle((x - 40, 5), (x + 40, 35), fill=OFF, tag=tag)
            centered_text(x, 20, label, size=14)

    dpg.add_spacer(height=8)
    dpg.add_text('D-pad: neutral', tag='dpad_text')


def build_customization_panel():
    dpg.add_spacer(height=6)
    dpg.add_separator()
    dpg.add_text('Customization', color=(200, 200, 200))
    with dpg.group(horizontal=True):
        dpg.add_text('Profile: -', tag='profile_text')
        dpg.add_spacer(width=20)
        for n in (1, 2, 3, 4):
            dpg.add_button(label=f'Set {n}', user_data=n,
                           callback=lambda s, a, u: control.set_profile(u))
        dpg.add_spacer(width=20)
        dpg.add_button(label='Rumble test', callback=lambda s, a, u: control.rumble_test())
    dpg.add_text('(Profile also switches via M + right stick up/down)',
                 color=(130, 130, 130, 255))


def build_mouse_panel():
    """'Mouse mode' control. On KDE this drives KWin's Game Controller plugin
    directly (off = normal gamepad, on = sticks-as-cursor for couch/bed use);
    elsewhere it falls back to EVIOCGRAB-suppressing the joystick node."""
    dpg.add_spacer(height=6)
    dpg.add_separator()
    if kwin.available():
        _mouse_backend[0] = 'kwin'
        _build_mouse_panel_kwin()
    else:
        _mouse_backend[0] = 'grab'
        _build_mouse_panel_grab()


def _build_mouse_panel_kwin():
    enabled = bool(kwin.is_enabled())
    with dpg.group(horizontal=True):
        dpg.add_text('Mouse mode', color=(200, 200, 200))
        dpg.add_spacer(width=12)
        dpg.add_checkbox(label='Gamepad controls the cursor (couch mode)',
                         tag='mouse_suppress', default_value=enabled,
                         callback=lambda s, a, u: _toggle_mouse_kwin(a))
        dpg.add_spacer(width=10)
        dpg.add_text('', tag='mouse_status', color=(150, 150, 150, 255))
    dpg.add_text("(KDE's KWin Game Controller plugin. ON = the sticks move the mouse "
                 'and triggers click - great for couch/bed use; OFF = normal gamepad. '
                 'Same setting as System Settings -> Game Controller; it persists, and '
                 'games are unaffected either way. Turning it ON may need a logout/login '
                 "if it doesn't take effect immediately.)",
                 color=(130, 130, 130, 255), wrap=560)
    _set_mouse_status(enabled)


def _build_mouse_panel_grab():
    with dpg.group(horizontal=True):
        dpg.add_text('Mouse-mode fix', color=(200, 200, 200))
        dpg.add_spacer(width=12)
        dpg.add_checkbox(label='Stop mouse mode (grab gamepad from the desktop)',
                         tag='mouse_suppress',
                         callback=lambda s, a, u: mousegrab.set_suppressed(a))
        dpg.add_spacer(width=10)
        dpg.add_text('', tag='mouse_status', color=(150, 150, 150, 255))
    dpg.add_text('(If your compositor drives the cursor from the sticks after a dongle '
                 're-pair, enable this to take an exclusive grab on the gamepad evdev node '
                 'so it can no longer move the cursor - the grab re-applies itself across '
                 'replugs. The app keeps reading inputs (hidraw), but while this is on, '
                 "evdev games (Steam/SDL) won't see the pad. Needs the udev rule.)",
                 color=(130, 130, 130, 255), wrap=560)


def build_lighting_panel():
    dpg.add_spacer(height=6)
    with dpg.group(horizontal=True):
        dpg.add_text('Lighting', color=(200, 200, 200))
        dpg.add_spacer(width=12)
        dpg.add_text('Slot:')
        dpg.add_radio_button(['0', '1', '2', '3'], tag='led_slot_radio',
                             horizontal=True,
                             callback=lambda s, a, u: activate_slot(int(a)))
        dpg.add_spacer(width=16)
        dpg.add_text('Effect:')
        # Captured app presets; applies to the active slot at current brightness.
        dpg.add_combo(led.PATTERN_NAMES, tag='led_pattern', width=120,
                      default_value='', no_preview=False,
                      callback=lambda s, a, u: apply_pattern(a))
    with dpg.group(horizontal=True):
        for i, (name, default) in enumerate(led.LIGHTS):
            with dpg.group():
                dpg.add_text(name)
                dpg.add_color_edit(default_value=(*default, 255),
                                   tag=f'led_color_{i}', no_alpha=True,
                                   no_inputs=True, width=40)
            dpg.add_spacer(width=14)
    with dpg.group(horizontal=True):
        dpg.add_text('Brightness')
        # Live-writes the active slot's record (+3) as you drag, like the app.
        dpg.add_slider_int(tag='led_bright', default_value=100,
                           min_value=0, max_value=100, width=160,
                           callback=lambda s, a, u: _led_async(led.set_brightness, a))
        dpg.add_button(label='Apply', callback=lambda s, a, u: apply_led())
        dpg.add_button(label='Fill all', callback=lambda s, a, u: led_fill_all())
        dpg.add_button(label='Off', callback=lambda s, a, u: led_off())
        dpg.add_spacer(width=12)
        dpg.add_button(label='Restore presets',
                       callback=lambda s, a, u: restore_presets())
    with dpg.group(horizontal=True):
        dpg.add_text('Speed     ')
        # Live-writes the active slot's record (+2); animated effects only.
        dpg.add_slider_int(tag='led_speed', default_value=10,
                           min_value=1, max_value=20, width=160,
                           callback=lambda s, a, u: _led_async(led.set_speed, a))
        dpg.add_spacer(width=8)
        dpg.add_text('(animated effects only)', color=(130, 130, 130, 255))
    with dpg.group(horizontal=True):
        dpg.add_checkbox(label='Audio reactive', tag='led_audio',
                         callback=lambda s, a, u: _led_async(led.set_audio_reactive, a))
        dpg.add_spacer(width=14)
        dpg.add_checkbox(label='Pick-up to wake', tag='led_pickup', default_value=True,
                         callback=lambda s, a, u: _led_async(led.set_pickup_wake, a))
        dpg.add_spacer(width=14)
        dpg.add_text('Sleep:')
        dpg.add_combo([lbl for lbl, _ in led.SLEEP_OPTIONS], tag='led_sleep',
                      default_value='10 min', width=80,
                      callback=lambda s, a, u: _led_async(led.set_sleep_timeout,
                                                          led.sleep_raw(a)))
    dpg.add_text('(Per-light color via Apply; or pick an Effect preset. Needs Xbox/green mode)',
                 color=(130, 130, 130, 255))
    with dpg.collapsing_header(label='Custom keyframes'):
        dpg.add_text('Build your own animation: set the 4 lights for each keyframe, '
                     'add/remove keyframes, then Apply. Speed/Brightness above '
                     'control playback.', color=(130, 130, 130, 255))
        dpg.add_text('', tag='kf_profile_note', wrap=560, color=(220, 180, 0, 255))
        with dpg.group(horizontal=True):
            dpg.add_text('Keyframe:')
            dpg.add_radio_button(['1'], tag='kf_frame', horizontal=True,
                                 default_value='1',
                                 callback=lambda s, a, u: kf_select_frame(int(a) - 1))
            dpg.add_spacer(width=10)
            dpg.add_button(label='+ Add', tag='kf_add_btn',
                           callback=lambda s, a, u: kf_add_frame())
            dpg.add_button(label='- Remove', tag='kf_remove_btn',
                           callback=lambda s, a, u: kf_remove_frame())
            dpg.add_spacer(width=10)
            dpg.add_text('8 / 8 keyframes', tag='kf_count_text',
                         color=(130, 130, 130, 255))
        with dpg.group(horizontal=True):
            for i, (name, default) in enumerate(led.LIGHTS):
                with dpg.group():
                    dpg.add_text(name)
                    dpg.add_color_edit(default_value=(*default, 255),
                                       tag=f'kf_color_{i}', no_alpha=True,
                                       no_inputs=True, width=40)
                dpg.add_spacer(width=14)
        with dpg.group(horizontal=True):
            dpg.add_button(label='Apply animation',
                           callback=lambda s, a, u: apply_keyframes())
            dpg.add_button(label='Copy keyframe to all',
                           callback=lambda s, a, u: kf_copy_to_all())
            dpg.add_button(label='Randomize',
                           callback=lambda s, a, u: kf_randomize())
            dpg.add_spacer(width=10)
            dpg.add_button(label='Pause', tag='kf_playpause_btn',
                           callback=lambda s, a, u: kf_toggle_playback())
        dpg.add_text('(Keyframes load from / save to the active color profile '
                     '(slot 0-3). Apply writes them to the controller. Max 8, min 1.)',
                     color=(130, 130, 130, 255))
        _kf_refresh_controls()   # seed the selector/labels for the default slot


def _cfg_slider(tag, addr, label, default=0, group=''):
    """A 0-100 slider that queues its raw value for `addr` on change. `group`
    prefixes the review label so same-named fields stay distinguishable."""
    full = f'{group} {label}'.strip()
    dpg.add_text(label)
    dpg.add_slider_int(tag=tag, default_value=default, min_value=0, max_value=100,
                       width=150,
                       callback=lambda s, a, u: queue_change(addr, [a], full, a))


def build_config_panel():
    dpg.add_spacer(height=6)
    dpg.add_separator()
    with dpg.group(horizontal=True):
        dpg.add_text('Config editor', color=(200, 200, 200))
        dpg.add_spacer(width=12)
        dpg.add_text('Editing profile: -', tag='cfg_profile_text',
                     color=(150, 150, 150, 255))
        dpg.add_spacer(width=12)
        dpg.add_button(label='Reload', tag='cfg_reload_btn',
                       callback=lambda s, a, u: load_config())
    with dpg.group(horizontal=True):
        dpg.add_text('No pending changes', tag='cfg_pending_text',
                     color=(130, 130, 130, 255))
        dpg.add_spacer(width=12)
        dpg.add_button(label='Review & push...', tag='cfg_review_btn', enabled=False,
                       callback=lambda s, a, u: open_review())
        dpg.add_button(label='Discard', tag='cfg_discard_btn', enabled=False,
                       callback=lambda s, a, u: discard_pending())
    dpg.add_text('(Selecting a profile loads its settings. Edits are queued until you push them.)',
                 color=(130, 130, 130, 255))

    # Global-ish
    with dpg.group(horizontal=True):
        _cfg_slider('cfg_vib_l', cfg.VIB_L, 'Vibration L')
        dpg.add_spacer(width=16)
        _cfg_slider('cfg_vib_r', cfg.VIB_R, 'Vibration R')
        dpg.add_spacer(width=16)
        with dpg.group():
            dpg.add_text('Poll rate')
            dpg.add_radio_button(cfg.POLL_RATES, tag='cfg_poll', horizontal=True,
                                 callback=lambda s, a, u: queue_change(
                                     cfg.POLL_RATE, [cfg.POLL_RATES.index(a)],
                                     'Poll rate', a))

    build_stick_panel('Left stick', 'st', 'Left stick',
                      cfg.ST_TRAJ, cfg.ST_DZ_MIN, cfg.ST_DZ_MAX,
                      cfg.ST_ADZ_MIN, cfg.ST_ADZ_MAX, cfg.ST_CURVE)
    build_stick_panel('Right stick', 'rs', 'Right stick',
                      cfg.RS_TRAJ, cfg.RS_DZ_MIN, cfg.RS_DZ_MAX,
                      cfg.RS_ADZ_MIN, cfg.RS_ADZ_MAX, cfg.RS_CURVE)

    build_trigger_panel('Trigger (LT)', 'lt', 'LT',
                        cfg.LT_DZ_MIN, cfg.LT_DZ_MAX, cfg.LT_ADZ_MIN,
                        cfg.LT_ADZ_MAX, cfg.LT_HAIR, cfg.LT_CURVE)
    build_trigger_panel('Trigger (RT)  [inferred LT+0x1c - verify]', 'rt', 'RT',
                        cfg.RT_DZ_MIN, cfg.RT_DZ_MAX, cfg.RT_ADZ_MIN,
                        cfg.RT_ADZ_MAX, cfg.RT_HAIR, cfg.RT_CURVE)

    build_remap_panel()


def build_stick_panel(title, pfx, grp, traj, dz_min, dz_max, adz_min, adz_max,
                      curve):
    """One stick's tuning block (LS or RS share an identical layout). `pfx`
    namespaces the widget tags; `grp` prefixes the review labels."""
    dpg.add_text(title, color=(170, 170, 170))
    with dpg.group(horizontal=True):
        _cfg_slider(f'cfg_{pfx}_dz_min', dz_min, 'Deadzone min', group=grp)
        dpg.add_spacer(width=16)
        _cfg_slider(f'cfg_{pfx}_dz_max', dz_max, 'Deadzone max', default=100, group=grp)
    with dpg.group(horizontal=True):
        _cfg_slider(f'cfg_{pfx}_adz_min', adz_min, 'Anti-dz min', group=grp)
        dpg.add_spacer(width=16)
        _cfg_slider(f'cfg_{pfx}_adz_max', adz_max, 'Anti-dz max', default=100, group=grp)
    with dpg.group(horizontal=True):
        with dpg.group():
            dpg.add_text('Trajectory')
            dpg.add_radio_button([n for n, _ in cfg.TRAJ], tag=f'cfg_{pfx}_traj',
                                 horizontal=True,
                                 callback=lambda s, a, u: queue_change(
                                     traj, [dict(cfg.TRAJ)[a]],
                                     f'{grp} trajectory', a))
        dpg.add_spacer(width=16)
        with dpg.group():
            dpg.add_text('Sensitivity curve')
            dpg.add_combo(cfg.CURVE_ITEMS, tag=f'cfg_{pfx}_curve', width=130,
                          default_value='Linear',
                          callback=lambda s, a, u: curve_combo_changed(pfx, curve, grp, a))
    build_curve_editor(pfx, curve, grp)


def build_curve_editor(pfx, addr, grp):
    """Custom-curve editor: a draggable 0..255 plot with 3 control points plus
    numeric x/y inputs, kept in sync. Editing selects 'Custom' for this input.
    Collapsed by default to keep the panel compact."""
    with dpg.collapsing_header(label='Custom curve'):
        dpg.add_text('Drag the 3 points or type values (0-255). Editing selects '
                     'Custom for this input.', color=(130, 130, 130, 255))
        with dpg.group(horizontal=True):
            with dpg.plot(width=190, height=190, no_menus=True, no_box_select=True,
                          no_mouse_pos=True, tag=f'cfg_{pfx}_curveplot'):
                dpg.add_plot_axis(dpg.mvXAxis, no_tick_labels=True,
                                  tag=f'cfg_{pfx}_cxaxis')
                dpg.add_plot_axis(dpg.mvYAxis, no_tick_labels=True,
                                  tag=f'cfg_{pfx}_cyaxis')
                dpg.set_axis_limits(f'cfg_{pfx}_cxaxis', 0, 255)
                dpg.set_axis_limits(f'cfg_{pfx}_cyaxis', 0, 255)
                dpg.add_line_series([0, 255], [0, 255], parent=f'cfg_{pfx}_cyaxis',
                                    tag=f'cfg_{pfx}_curveline')
                for n in range(3):
                    dpg.add_drag_point(tag=f'cfg_{pfx}_drag{n}',
                                       color=(0, 200, 80, 255),
                                       default_value=cfg.CUSTOM_DEFAULT[n],
                                       user_data=(pfx, addr, grp),
                                       callback=lambda s, a, u: curve_from_drag(*u))
            with dpg.group():
                for n in range(3):
                    with dpg.group(horizontal=True):
                        dpg.add_text(f'P{n + 1}')
                        dpg.add_input_int(tag=f'cfg_{pfx}_cx{n}', width=80, step=0,
                                          min_value=0, max_value=255,
                                          min_clamped=True, max_clamped=True,
                                          default_value=cfg.CUSTOM_DEFAULT[n][0],
                                          user_data=(pfx, addr, grp),
                                          callback=lambda s, a, u: curve_from_input(*u))
                        dpg.add_input_int(tag=f'cfg_{pfx}_cy{n}', width=80, step=0,
                                          min_value=0, max_value=255,
                                          min_clamped=True, max_clamped=True,
                                          default_value=cfg.CUSTOM_DEFAULT[n][1],
                                          user_data=(pfx, addr, grp),
                                          callback=lambda s, a, u: curve_from_input(*u))
    _curve_load(pfx, [tuple(p) for p in cfg.CUSTOM_DEFAULT])


def build_trigger_panel(title, pfx, grp, dz_min, dz_max, adz_min, adz_max,
                        hair, curve):
    """One trigger's tuning block (LT or RT share an identical layout). `pfx`
    namespaces the widget tags; `grp` prefixes the review labels."""
    dpg.add_text(title, color=(170, 170, 170))
    with dpg.group(horizontal=True):
        _cfg_slider(f'cfg_{pfx}_dz_min', dz_min, 'Deadzone min', group=grp)
        dpg.add_spacer(width=16)
        _cfg_slider(f'cfg_{pfx}_dz_max', dz_max, 'Deadzone max', default=100, group=grp)
    with dpg.group(horizontal=True):
        _cfg_slider(f'cfg_{pfx}_adz_min', adz_min, 'Anti-dz min', group=grp)
        dpg.add_spacer(width=16)
        _cfg_slider(f'cfg_{pfx}_adz_max', adz_max, 'Anti-dz max', default=100, group=grp)
    with dpg.group(horizontal=True):
        with dpg.group():
            dpg.add_text('Hair trigger')
            dpg.add_radio_button([n for n, _ in cfg.HAIR_MODES], tag=f'cfg_{pfx}_hair',
                                 horizontal=True,
                                 callback=lambda s, a, u: queue_change(
                                     hair, dict(cfg.HAIR_MODES)[a],
                                     f'{grp} hair trigger', a))
        dpg.add_spacer(width=16)
        with dpg.group():
            dpg.add_text('Response curve')
            dpg.add_combo(cfg.CURVE_ITEMS, tag=f'cfg_{pfx}_curve', width=130,
                          default_value='Linear',
                          callback=lambda s, a, u: curve_combo_changed(pfx, curve, grp, a))
    build_curve_editor(pfx, curve, grp)


def build_remap_panel():
    """Button remap, collapsed by default (16 rows would dominate the window).
    Each source's combo queues [enable, code] for its record on change."""
    with dpg.collapsing_header(label='Button remap'):
        dpg.add_text('(Each button -> what it acts as. "Default" clears the remap.)',
                     color=(130, 130, 130, 255))
        slots = cfg.REMAP_SLOTS
        half = (len(slots) + 1) // 2
        with dpg.group(horizontal=True):
            for col in (slots[:half], slots[half:]):
                with dpg.group():
                    for name, addr in col:
                        with dpg.group(horizontal=True):
                            dpg.add_text(f'{name:>10}')
                            # nm binds the loop var so the queued label is correct.
                            dpg.add_combo(
                                cfg.REMAP_ITEMS, tag=f'remap_{addr:04x}',
                                width=120, default_value=cfg.REMAP_NONE,
                                user_data=addr,
                                callback=lambda s, a, u, nm=name: queue_change(
                                    u, cfg.remap_write_bytes(a), f'Remap {nm}', a))
                dpg.add_spacer(width=16)


def build_backup_panel():
    """Full-setup export/restore: snapshot every profile + lighting to JSON and
    write it back later as a restore point. Export/Restore each open a file
    dialog so you choose exactly where the snapshot is saved/loaded from."""
    dpg.add_spacer(height=6)
    dpg.add_separator()
    dpg.add_text('Backup / Restore', color=(200, 200, 200))
    with dpg.group(horizontal=True):
        dpg.add_button(label='Export to JSON...',
                       callback=lambda s, a, u: dpg.show_item('export_dialog'))
        dpg.add_button(label='Restore from JSON...',
                       callback=lambda s, a, u: dpg.show_item('restore_dialog'))
    # Appears once a restore file is loaded (open_restore) - the explicit
    # confirm/write step, inline rather than a fragile modal popup.
    dpg.add_button(label='Write loaded backup to controller', tag='restore_write_btn',
                   show=False, callback=lambda s, a, u: do_restore())
    with dpg.group(horizontal=True):
        dpg.add_text('Status:', color=(130, 130, 130, 255))
        dpg.add_text('idle', tag='backup_status', color=(170, 170, 170, 255))
    with dpg.group(horizontal=True):
        dpg.add_text('Last file:', color=(130, 130, 130, 255))
        dpg.add_input_text(tag='backup_path', default_value='', width=380,
                           readonly=True)
    dpg.add_text('(Export snapshots all 4 profiles + lighting. Restore writes a '
                 'snapshot back. Reading takes a few seconds.)',
                 color=(130, 130, 130, 255))


def build_backup_dialogs():
    """The save/open file dialogs for Backup/Restore. Created top-level (like the
    modals) and shown on demand. DearPyGui renders these itself, so they behave
    consistently across window managers."""
    home = _user_home()
    default_name = f'gamesir_backup_{datetime.now():%Y%m%d-%H%M}.json'
    with dpg.file_dialog(tag='export_dialog', directory_selector=False, show=False,
                         callback=_on_export_pick, default_path=home,
                         default_filename=default_name, width=560, height=400,
                         modal=True):
        dpg.add_file_extension('.json')
        dpg.add_file_extension('.*')
    with dpg.file_dialog(tag='restore_dialog', directory_selector=False, show=False,
                         callback=_on_restore_pick, default_path=home,
                         width=560, height=400, modal=True):
        dpg.add_file_extension('.json')
        dpg.add_file_extension('.*')


def build_review_modal():
    """Hidden modal that open_review() fills with the queued changes and shows."""
    with dpg.window(label='Review changes', modal=True, show=False,
                    tag='review_modal', no_resize=True, width=460, height=380,
                    pos=(80, 120)):
        dpg.add_text('', tag='review_header')
        dpg.add_separator()
        dpg.add_child_window(tag='review_list', height=270, autosize_x=True)
        dpg.add_separator()
        with dpg.group(horizontal=True):
            dpg.add_button(label='Push to controller',
                           callback=lambda s, a, u: apply_pending())
            dpg.add_button(label='Cancel',
                           callback=lambda s, a, u: dpg.configure_item(
                               'review_modal', show=False))


def build_ui():
    with dpg.window(label='Controller Input', tag='main_win', no_title_bar=True):
        build_header()
        build_input_panel()
        build_customization_panel()
        build_mouse_panel()
        build_lighting_panel()
        build_config_panel()
        build_backup_panel()
    # Top-level (not nested in main_win): the modal dialogs + file pickers.
    build_review_modal()
    build_backup_dialogs()


def main():
    threading.Thread(target=read_controller, daemon=True).start()
    if not kwin.available():
        mousegrab.start()   # EVIOCGRAB fallback (non-KDE); KDE uses the KWin plugin

    dpg.create_context()

    with dpg.font_registry():
        default_font = dpg.add_font(FONT_PATH, 20)
    dpg.bind_font(default_font)

    dpg.create_viewport(title=f'GameSir Cyclone 2  —  alpha 1 (v{__version__})',
                        width=620, height=800)
    build_ui()

    dpg.setup_dearpygui()
    dpg.show_viewport()
    # Make the window fill (and track) the viewport so content scales/scrolls
    # instead of overflowing a fixed-size window.
    dpg.set_primary_window('main_win', True)

    # Many WMs ignore the viewport position until the window is actually mapped,
    # leaving the title bar off-screen. Render one frame first, then place it on
    # the primary monitor (handles multi-monitor global-coordinate offsets).
    dpg.render_dearpygui_frame()
    place_on_screen(620, 800)

    while dpg.is_dearpygui_running():
        update_gui()
        dpg.render_dearpygui_frame()

    dpg.destroy_context()


if __name__ == '__main__':
    main()
