import hid
import re
import subprocess
import threading
import time
import dearpygui.dearpygui as dpg

from gs_common import find_vendor_hidraw, pad
from gamesir_enhanced import parse_enhanced
from gamesir_led_factory import FACTORY_START, FACTORY_DATA

FONT_PATH = '/usr/share/fonts/TTF/DejaVuSans.ttf'


def primary_monitor_geometry():
    """Return (x, y, w, h) of the primary monitor in global coordinates, or
    None. Uses xrandr, which works on X11 and XWayland. On a multi-monitor
    setup the global origin is often NOT the primary screen's corner, so a
    naive position like (100,100) can land in dead space above another output."""
    try:
        out = subprocess.run(['xrandr', '--listmonitors'],
                             capture_output=True, text=True, timeout=2).stdout
    except Exception:
        return None
    fallback = None
    for line in out.splitlines():
        # token looks like:  3840/697x2160/392+2880+0   -> w x h + x + y
        m = re.search(r'(\d+)/\d+x(\d+)/\d+\+(\d+)\+(\d+)', line)
        if not m:
            continue
        w, h, x, y = (int(g) for g in m.groups())
        if '*' in line:          # xrandr flags the primary monitor with '*'
            return (x, y, w, h)
        if fallback is None:
            fallback = (x, y, w, h)
    return fallback


def place_on_screen(win_w, win_h):
    """Position the viewport on the primary monitor (upper third, centered),
    so the title bar is always reachable regardless of monitor layout."""
    geo = primary_monitor_geometry()
    if not geo:
        dpg.set_viewport_pos([80, 80])     # best-effort fallback
        return
    x, y, w, h = geo
    px = x + max(0, (w - win_w) // 2)
    py = y + max(40, (h - win_h) // 3)
    dpg.set_viewport_pos([px, py])

state = {
    'lx': 128, 'ly': 128, 'rx': 128, 'ry': 128,
    'lt': 0, 'rt': 0,
    'dpad': 'neutral',
    'a': False, 'b': False, 'x': False, 'y': False,
    'lb': False, 'rb': False,
    'view': False, 'menu': False,
    'ls': False, 'rs': False,
    'l4': False, 'r4': False, 'm': False, 'home': False, 'share': False,
    'battery': 0, 'charging': False,
    'profile': None,     # current profile 1-4 (from get-profile 0x0B -> 0x10 reply)
    'led_slot': None,    # active lighting slot (from read-reg 0x20/0x0000 -> 0x10 0x05)
    'connected': None,   # None = connecting, True = open, False = not found/lost
    'mode_ok': False,    # True when we're getting a populated Xbox-mode 0x12 report
}

EXTRA_BTNS = ('l4', 'r4', 'm', 'home', 'share')

# --- write layer -----------------------------------------------------------
# Commands and the read loop share one hid handle across threads, so all writes
# go through one lock. _device is the currently-open handle (or None).
_write_lock = threading.Lock()
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


# --- LED / RGB -------------------------------------------------------------
# Lighting lives in register bank 0x20 (NOT the per-profile config bank):
#   0x0000          = active effect selector (the preset slot to show)
#   0x0001 + M*0x7c = 124-byte record for slot M
#   record +3       = brightness (0..0x64);  record +4.. = RGB triplet palette
# A solid color = fill the palette with one repeated (R,G,B); brightness 0 = off.
LED_BANK = 0x20
LED_REC = 0x7c
LED_SLOT = 1          # the preset slot the GUI writes to / activates
LED_TRIPLETS = 40     # palette capacity within one 124-byte record
FRAME_TRIPLETS = 5    # the LED render frame size (tiled to fill the record)

# Individually-addressable lights (confirmed via gamesir_led_map.py). Each maps
# to a position within the 5-triplet render frame; frame position 2 has no
# visible LED. LIGHTS order must line up with LIGHT_FRAME_POS.
LIGHTS = [
    ('Left grip',  (0, 128, 255)),
    ('Right grip', (0, 128, 255)),
    ('Profile',    (0, 128, 255)),
    ('Home',       (0, 128, 255)),
]
LIGHT_FRAME_POS = (0, 1, 3, 4)   # frame position for each light above


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


def set_lights(colors, brightness=100, slot=None):
    """Write a per-light palette and make it the active effect. `colors` is a
    list of (r,g,b), one per light in index order; brightness 0..100 (0 = off).
    slot=None edits the slot the controller currently shows (so we don't clobber
    a different preset), falling back to LED_SLOT until that's known.

    The record renders as 5-triplet FRAMES (4 lights + a trailing duplicate).
    Zeroing the tail leaves a broken frame that drops the Profile LED, so we
    tile an IDENTICAL frame across the whole record instead -> static, fully
    lit, no animation."""
    if slot is None:
        slot = state['led_slot'] if state['led_slot'] is not None else LED_SLOT
    bri = max(0, min(0x64, round(brightness / 100 * 0x64)))
    # Place each light's color at its frame position; position 2 has no LED but
    # is kept non-black so the frame stays complete (a broken/zeroed frame drops
    # the Profile LED).
    frame = [colors[0]] * FRAME_TRIPLETS
    for i, pos in enumerate(LIGHT_FRAME_POS):
        frame[pos] = colors[i]
    palette = (frame * (LED_TRIPLETS // FRAME_TRIPLETS))[:LED_TRIPLETS]
    flat = []
    for r, g, b in palette:
        flat += [r & 0xFF, g & 0xFF, b & 0xFF]
    record = [0x01, 0x05, 0x14, bri] + flat
    write_reg(LED_BANK, 0x0001 + slot * LED_REC, record[:LED_REC])
    write_reg(LED_BANK, 0x0000, [slot])   # select it


def _picker_rgb(tag):
    """Read a color_edit widget as 0-255 ints (DPG may return 0-1 or 0-255)."""
    col = dpg.get_value(tag)[:3]
    if max(col) <= 1.0:
        return [int(round(c * 255)) for c in col]
    return [int(round(c)) for c in col]


def _current_colors():
    return [_picker_rgb(f'led_color_{i}') for i in range(len(LIGHTS))]


def apply_led():
    colors = _current_colors()
    bri = dpg.get_value('led_bright')
    threading.Thread(target=lambda: set_lights(colors, bri), daemon=True).start()


def led_off():
    colors = _current_colors()
    threading.Thread(target=lambda: set_lights(colors, 0), daemon=True).start()


def led_fill_all():
    """Copy the first light's color into every swatch (quick solid color)."""
    col = dpg.get_value('led_color_0')
    for i in range(1, len(LIGHTS)):
        dpg.set_value(f'led_color_{i}', col)


def activate_slot(n):
    """Make lighting slot n the active one (so Apply edits it / it's displayed)."""
    state['led_slot'] = n     # optimistic; the periodic poll confirms it
    threading.Thread(target=lambda: write_reg(LED_BANK, 0x0000, [n]),
                     daemon=True).start()


def restore_presets():
    """Rewrite lighting records 0-3 from the captured baseline."""
    threading.Thread(
        target=lambda: write_reg(LED_BANK, FACTORY_START, FACTORY_DATA),
        daemon=True).start()


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
        send_cmd(0x0F, 0xF2)
        now = time.time()
        if now - last_query > 0.45:
            if toggle == 0:
                send_cmd(0x0F, 0x0B)                          # profile -> 0x10 0x0C
            else:
                send_cmd(0x0F, 0x04, 0x20, 0x00, 0x00, 0x01)  # lighting slot -> 0x10 0x05
            toggle ^= 1
            last_query = now
        time.sleep(0.5)


def read_session(device):
    """Read one open device until it errors/disconnects. Returns on failure."""
    global _device
    _device = device
    alive = [True]
    threading.Thread(target=maintenance_loop, args=(alive,), daemon=True).start()
    try:
        while True:
            data = device.read(64, timeout_ms=200)
            if not data:
                continue
            if data[0] == 0x10 and data[1] == 0x0C:     # get-profile reply
                state['profile'] = data[2]
                continue
            if (data[0] == 0x10 and data[1] == 0x05 and data[2] == 0x20
                    and data[3] == 0x00 and data[4] == 0x00):  # lighting selector
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
        _device = None


def read_controller():
    """Continuously find, open, and read the controller; reconnect on drop.

    Survives unplugging the cable (it keeps working over the 2.4GHz dongle),
    mode switches, and the hidraw node renumbering on re-enumeration.
    """
    while True:
        devnode, _name, _hid_name = find_vendor_hidraw()
        if not devnode:
            state['connected'] = False
            state['mode_ok'] = False
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
        read_session(device)   # blocks until disconnect/error
        state['connected'] = False
        state['mode_ok'] = False
        try:
            device.close()
        except Exception:
            pass
        time.sleep(0.5)   # brief pause before trying to reconnect


def stick_pos(value):
    return (value - 128) / 128


def centered_text(cx, cy, label, size=14):
    # dpg.get_text_size() only works after the first rendered frame, too late for
    # build-time layout, so estimate glyph width instead.
    w = len(label) * size * 0.55
    h = size * 1.15
    dpg.draw_text((cx - w / 2, cy - h / 2), label, size=size)


CONN_STATUS = {
    True: ('Connected', (0, 200, 80, 255)),
    False: ('Not found', (220, 60, 60, 255)),
    None: ('Connecting...', (200, 180, 0, 255)),
}

ON = (0, 200, 80, 255)
OFF = (60, 60, 60, 255)


def battery_color(pct):
    if pct > 50:
        return (0, 200, 80, 255)
    if pct > 20:
        return (220, 180, 0, 255)
    return (220, 60, 60, 255)


def update_gui():
    dpg.set_value('ls_dot', [[stick_pos(state['lx'])], [-stick_pos(state['ly'])]])
    dpg.set_value('rs_dot', [[stick_pos(state['rx'])], [-stick_pos(state['ry'])]])

    dpg.set_value('lt_bar', state['lt'] / 255)
    dpg.set_value('rt_bar', state['rt'] / 255)

    for btn in ('a', 'b', 'x', 'y', 'lb', 'rb', 'view', 'menu', 'ls', 'rs', *EXTRA_BTNS):
        dpg.configure_item(f'btn_{btn}', fill=ON if state[btn] else OFF)

    dpg.set_value('dpad_text', f"D-pad: {state['dpad']}")

    # Connection + mode
    text, color = CONN_STATUS[state['connected']]
    dpg.set_value('conn_text', text)
    dpg.configure_item('conn_text', color=color)

    if state['connected'] and not state['mode_ok']:
        dpg.set_value('mode_text',
                      'No Xbox-mode data - hold the GREEN button ~2s to switch to Xbox mode')
        dpg.configure_item('mode_text', color=(220, 60, 60, 255))
    else:
        dpg.set_value('mode_text', '')

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

    # Active profile
    prof = state['profile']
    dpg.set_value('profile_text', f'Profile: {prof}' if prof else 'Profile: -')

    # Active lighting slot: reflect the controller's live selector in the radio
    # (set_value does not fire the callback, so this won't loop).
    slot = state['led_slot']
    if slot is not None and 0 <= slot <= 3:
        dpg.set_value('led_slot_radio', str(slot))


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


def main():
    threading.Thread(target=read_controller, daemon=True).start()

    dpg.create_context()

    with dpg.font_registry():
        default_font = dpg.add_font(FONT_PATH, 20)
    dpg.bind_font(default_font)

    dpg.create_viewport(title='GameSir Cyclone 2', width=620, height=800)

    with dpg.window(label='Controller Input', tag='main_win',
                    no_title_bar=True):

        with dpg.group(horizontal=True):
            dpg.add_text('GameSir Cyclone 2 - Live Input', color=(200, 200, 200))
            dpg.add_spacer(width=120)
            dpg.add_text('Connecting...', tag='conn_text', color=(200, 180, 0, 255))
        with dpg.group(horizontal=True):
            dpg.add_text('Battery: --', tag='batt_text', color=(140, 140, 140, 255))
        dpg.add_text('', tag='mode_text', color=(220, 60, 60, 255))
        dpg.add_separator()
        dpg.add_spacer(height=8)

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

        dpg.add_spacer(height=6)
        dpg.add_separator()
        dpg.add_text('Customization', color=(200, 200, 200))
        with dpg.group(horizontal=True):
            dpg.add_text('Profile: -', tag='profile_text')
            dpg.add_spacer(width=20)
            for n in (1, 2, 3, 4):
                dpg.add_button(label=f'Set {n}', user_data=n,
                               callback=lambda s, a, u: set_profile(u))
            dpg.add_spacer(width=20)
            dpg.add_button(label='Rumble test', callback=lambda s, a, u: rumble_test())
        dpg.add_text('(Profile also switches via M + right stick up/down)',
                     color=(130, 130, 130, 255))

        dpg.add_spacer(height=6)
        with dpg.group(horizontal=True):
            dpg.add_text('Lighting', color=(200, 200, 200))
            dpg.add_spacer(width=12)
            dpg.add_text('Slot:')
            dpg.add_radio_button(['0', '1', '2', '3'], tag='led_slot_radio',
                                 horizontal=True,
                                 callback=lambda s, a, u: activate_slot(int(a)))
        with dpg.group(horizontal=True):
            for i, (name, default) in enumerate(LIGHTS):
                with dpg.group():
                    dpg.add_text(name)
                    dpg.add_color_edit(default_value=(*default, 255),
                                       tag=f'led_color_{i}', no_alpha=True,
                                       no_inputs=True, width=40)
                dpg.add_spacer(width=14)
        with dpg.group(horizontal=True):
            dpg.add_text('Brightness')
            dpg.add_slider_int(tag='led_bright', default_value=100,
                               min_value=0, max_value=100, width=160)
            dpg.add_button(label='Apply', callback=lambda s, a, u: apply_led())
            dpg.add_button(label='Fill all', callback=lambda s, a, u: led_fill_all())
            dpg.add_button(label='Off', callback=lambda s, a, u: led_off())
            dpg.add_spacer(width=12)
            dpg.add_button(label='Restore presets',
                           callback=lambda s, a, u: restore_presets())
        dpg.add_text('(Per-light color; click a swatch to pick. Needs Xbox/green mode)',
                     color=(130, 130, 130, 255))

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
