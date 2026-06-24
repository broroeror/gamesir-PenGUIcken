"""
GameSir Cyclone 2 - Qt/QML bridge
=================================
The single QObject that QML talks to. It owns NO protocol logic: it polls the
shared `state` dict (filled by the reader thread) on a QTimer and republishes it
as Qt properties/signals, and forwards user actions to the existing command
layer (`gamesir_control`). Everything reverse-engineered stays in its own module
and is reused verbatim.

Two cadences:
  * input  (~60 Hz) - sticks/triggers/buttons, for a fluid live controller view.
  * status (~4  Hz) - connection, battery, profile, firmware, mode warning.
"""

import threading

from PySide6.QtCore import QObject, Signal, Property, Slot, QTimer

from gs_state import state, EXTRA_BTNS
import gamesir_control as control
import gamesir_led as led
import gamesir_kf_cache as kf_cache
from gamesir_led import LIGHTS


def _led_async(fn, *args):
    """Every led.* write is fire-and-forget; run it off the Qt thread."""
    threading.Thread(target=lambda: fn(*args), daemon=True).start()


def _hex(rgb):
    return '#%02X%02X%02X' % (rgb[0] & 0xFF, rgb[1] & 0xFF, rgb[2] & 0xFF)


def _rgb(hexstr):
    h = hexstr.lstrip('#')
    return [int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)]


class GamesirBridge(QObject):
    # --- change signals (one per property group QML binds to) ---------------
    inputChanged = Signal()
    statusChanged = Signal()
    lightsChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        # Cached snapshots so we only emit when something actually changes
        # (avoids waking every QML binding 60x/s for nothing).
        self._input_sig = None
        self._status_sig = None

        # Per-zone display colors for the controller render. Driven by the Lights
        # page; seeded from each zone's factory default so the render looks lit.
        self._light_colors = [_hex(default) for _, default in LIGHTS]
        self._brightness = 100      # 0..100 (device byte range is 0..0x64 == 100)
        self._speed = 10            # 1..20 UI (higher = faster)

        self._input_timer = QTimer(self)
        self._input_timer.setInterval(16)        # ~60 Hz
        self._input_timer.timeout.connect(self._poll_input)
        self._input_timer.start()

        self._status_timer = QTimer(self)
        self._status_timer.setInterval(250)      # 4 Hz
        self._status_timer.timeout.connect(self._poll_status)
        self._status_timer.start()

    # ------------------------------------------------------------------ polls
    def _poll_input(self):
        sig = (state['lx'], state['ly'], state['rx'], state['ry'],
               state['lt'], state['rt'], state['dpad'],
               state['a'], state['b'], state['x'], state['y'],
               state['lb'], state['rb'], state['ls'], state['rs'],
               state['view'], state['menu'],
               state['l4'], state['r4'], state['m'], state['home'], state['share'])
        if sig != self._input_sig:
            self._input_sig = sig
            self.inputChanged.emit()

    def _poll_status(self):
        sig = (state['connected'], state['mode_ok'], state['battery'],
               state['charging'], state['profile'], state['led_slot'],
               state['firmware'])
        if sig != self._status_sig:
            self._status_sig = sig
            self.statusChanged.emit()

    # --------------------------------------------------------- input readouts
    # Sticks reported 0..255 with 128 at rest; expose as -1.0..+1.0 for QML.
    def _axis(self, key):
        return (state[key] - 128) / 127.0

    @Property(float, notify=inputChanged)
    def leftStickX(self):
        return self._axis('lx')

    @Property(float, notify=inputChanged)
    def leftStickY(self):
        return self._axis('ly')

    @Property(float, notify=inputChanged)
    def rightStickX(self):
        return self._axis('rx')

    @Property(float, notify=inputChanged)
    def rightStickY(self):
        return self._axis('ry')

    @Property(float, notify=inputChanged)
    def leftTrigger(self):
        return state['lt'] / 255.0

    @Property(float, notify=inputChanged)
    def rightTrigger(self):
        return state['rt'] / 255.0

    @Property(str, notify=inputChanged)
    def dpad(self):
        return state['dpad']

    @Property('QVariantMap', notify=inputChanged)
    def buttons(self):
        """Map of buttonName -> bool, for QML to bind highlights against."""
        keys = ('a', 'b', 'x', 'y', 'lb', 'rb', 'ls', 'rs',
                'view', 'menu') + EXTRA_BTNS
        return {k: bool(state[k]) for k in keys}

    # --------------------------------------------------------- status readouts
    @Property(bool, notify=statusChanged)
    def connected(self):
        return bool(state['connected'])

    @Property(bool, notify=statusChanged)
    def modeOk(self):
        return bool(state['mode_ok'])

    @Property(int, notify=statusChanged)
    def battery(self):
        return int(state['battery'] or 0)

    @Property(bool, notify=statusChanged)
    def charging(self):
        return bool(state['charging'])

    @Property(int, notify=statusChanged)
    def profile(self):
        return int(state['profile']) if state['profile'] else 0

    @Property(int, notify=statusChanged)
    def ledSlot(self):
        return int(state['led_slot']) if state['led_slot'] is not None else -1

    @Property(str, notify=statusChanged)
    def firmware(self):
        return state['firmware'] or ''

    # ------------------------------------------------------------- lighting view
    @Property('QVariantList', constant=True)
    def lightNames(self):
        """Zone names in LIGHTS order, for labels/callouts."""
        return [name for name, _ in LIGHTS]

    @Property('QVariantList', notify=lightsChanged)
    def lightColors(self):
        """Per-zone display colors the controller render binds to."""
        return list(self._light_colors)

    @Slot(int, str)
    def setLight(self, i, color):
        """Set one zone's display color (the Lights page calls this as the user
        edits). Does NOT write to the controller; pushing is a separate action."""
        if 0 <= i < len(self._light_colors):
            self._light_colors[i] = color
            self.lightsChanged.emit()

    @Property('QVariantList', constant=True)
    def presetNames(self):
        return list(led.PATTERN_NAMES)

    @Property('QVariantList', constant=True)
    def sleepOptions(self):
        return [lbl for lbl, _ in led.SLEEP_OPTIONS]

    @Property(int, notify=lightsChanged)
    def brightness(self):
        return self._brightness

    @Property(int, notify=lightsChanged)
    def speed(self):
        return self._speed

    # --- lighting writes (all fire-and-forget to the active slot) -----------
    def _zone_rgb(self):
        return [_rgb(c) for c in self._light_colors]

    @Slot()
    def applyColors(self):
        """Push the current per-zone colors as a solid palette at brightness."""
        _led_async(led.set_lights, self._zone_rgb(), self._brightness)

    @Slot()
    def lightsOff(self):
        _led_async(led.set_lights, self._zone_rgb(), 0)

    @Slot(str)
    def applyPreset(self, name):
        """Apply a named effect (Flow/Rainbow/...) and reflect its own speed."""
        rec = led.PATTERNS.get(name)
        if rec is not None:
            self._speed = led.speed_ui(rec[led.REC_SPEED_OFF])
            self.lightsChanged.emit()
        _led_async(led.set_pattern, name, self._brightness)

    @Slot(int)
    def setBrightness(self, v):
        self._brightness = max(0, min(100, int(v)))
        self.lightsChanged.emit()
        _led_async(led.set_brightness, self._brightness)

    @Slot(int)
    def setSpeed(self, v):
        self._speed = max(led.SPEED_MIN, min(led.SPEED_MAX, int(v)))
        self.lightsChanged.emit()
        _led_async(led.set_speed, self._speed)

    @Slot(bool)
    def setAudioReactive(self, on):
        _led_async(led.set_audio_reactive, on)

    @Slot(bool)
    def setPickupWake(self, on):
        _led_async(led.set_pickup_wake, on)

    @Slot(str)
    def setSleepTimeout(self, label):
        _led_async(led.set_sleep_timeout, led.sleep_raw(label))

    @Slot('QVariantList')
    def applyKeyframes(self, frames):
        """`frames` is a list of frames; each frame is a list of 4 [r,g,b] ints in
        LIGHTS order. Writes them as a custom animation at the current speed/bri."""
        norm = [[[int(c[0]), int(c[1]), int(c[2])] for c in fr] for fr in frames]
        if not norm:
            return
        slot = led._resolve_slot(None)
        kf_cache.save(slot, norm, len(norm))
        _led_async(led.set_keyframes, norm, self._speed, self._brightness, slot)

    @Slot(bool, int)
    def setPlayback(self, playing, frame):
        _led_async(led.set_playback, playing, frame)

    @Slot()
    def restoreLighting(self):
        _led_async(led.restore_factory)

    # ------------------------------------------------------------- user actions
    @Slot(int)
    def setProfile(self, n):
        control.set_profile(n)

    @Slot()
    def rumbleTest(self):
        control.rumble_test()
