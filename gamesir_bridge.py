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
import time
from datetime import datetime

from PySide6.QtCore import QObject, Signal, Property, Slot, QTimer

from gs_state import state, EXTRA_BTNS
import gamesir_control as control
import gamesir_led as led
import gamesir_config as cfg
import gamesir_kf_cache as kf_cache
import gamesir_kwin as kwin
import gamesir_factory as factory
import gamesir_backup as backup
import gamesir_flash as flash
from gamesir_led import LIGHTS

from PySide6.QtCore import QUrl


def _led_async(fn, *args):
    """Every led.* write is fire-and-forget; run it off the Qt thread."""
    threading.Thread(target=lambda: fn(*args), daemon=True).start()


def _led_retry(fn, *args):
    """Like _led_async, but send twice (spaced) for one-shot single-byte settings
    the controller is prone to dropping when a command arrives back-to-back with
    its heartbeat/queries (audio-reactive, pick-up-to-wake, sleep timeout)."""
    def run():
        fn(*args); time.sleep(0.06); fn(*args)
    threading.Thread(target=run, daemon=True).start()


# Friendly key -> (register address, review-label) for the scalar config fields
# the Sticks/Triggers/Vibration pages edit.
SCALARS = {
    'st_dz_min':  (cfg.ST_DZ_MIN,  'Left stick deadzone min'),
    'st_dz_max':  (cfg.ST_DZ_MAX,  'Left stick deadzone max'),
    'st_adz_min': (cfg.ST_ADZ_MIN, 'Left stick anti-deadzone min'),
    'st_adz_max': (cfg.ST_ADZ_MAX, 'Left stick anti-deadzone max'),
    'rs_dz_min':  (cfg.RS_DZ_MIN,  'Right stick deadzone min'),
    'rs_dz_max':  (cfg.RS_DZ_MAX,  'Right stick deadzone max'),
    'rs_adz_min': (cfg.RS_ADZ_MIN, 'Right stick anti-deadzone min'),
    'rs_adz_max': (cfg.RS_ADZ_MAX, 'Right stick anti-deadzone max'),
    'lt_dz_min':  (cfg.LT_DZ_MIN,  'LT deadzone min'),
    'lt_dz_max':  (cfg.LT_DZ_MAX,  'LT deadzone max'),
    'lt_adz_min': (cfg.LT_ADZ_MIN, 'LT anti-deadzone min'),
    'lt_adz_max': (cfg.LT_ADZ_MAX, 'LT anti-deadzone max'),
    'rt_dz_min':  (cfg.RT_DZ_MIN,  'RT deadzone min'),
    'rt_dz_max':  (cfg.RT_DZ_MAX,  'RT deadzone max'),
    'rt_adz_min': (cfg.RT_ADZ_MIN, 'RT anti-deadzone min'),
    'rt_adz_max': (cfg.RT_ADZ_MAX, 'RT anti-deadzone max'),
    'vib_l':      (cfg.VIB_L,      'Vibration L'),
    'vib_r':      (cfg.VIB_R,      'Vibration R'),
}
CURVE_ADDR = {'st': cfg.ST_CURVE, 'rs': cfg.RS_CURVE,
              'lt': cfg.LT_CURVE, 'rt': cfg.RT_CURVE}
TRAJ_ADDR = {'st': cfg.ST_TRAJ, 'rs': cfg.RS_TRAJ}
HAIR_ADDR = {'lt': cfg.LT_HAIR, 'rt': cfg.RT_HAIR}

# Reverse lookups so a saved write can be folded back into the cached config
# snapshot (keeps the editor consistent across sub-tab switches after a Save).
_ADDR_TO_SCALAR = {addr: key for key, (addr, _l) in SCALARS.items()}
_ADDR_TO_CURVE = {addr: side for side, addr in CURVE_ADDR.items()}
_ADDR_TO_TRAJ = {addr: side for side, addr in TRAJ_ADDR.items()}
_ADDR_TO_HAIR = {addr: side for side, addr in HAIR_ADDR.items()}
_ADDR_TO_REMAP = {addr: name for name, addr in cfg.REMAP_SLOTS}
_REMAP_ADDR = {name: addr for name, addr in cfg.REMAP_SLOTS}


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
    lightingLoaded = Signal()       # fired when a slot's lighting is read back
    mouseModeChanged = Signal()
    configLoaded = Signal()         # fired when a profile's config is read back
    pendingChanged = Signal()       # number of queued (unsaved) config edits
    backupBusyChanged = Signal()
    backupProgress = Signal(int, int)   # done, total
    backupStatus = Signal(bool, str)    # ok, message
    fwBusyChanged = Signal()
    fwProgress = Signal(str)            # phase text (Entering loader / Writing / …)
    fwStatus = Signal(bool, str)        # ok, message
    fwVersionsChanged = Signal()        # library changed (e.g. after a backup)

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

        # Lighting read-back: pull the active slot's real state off the device so
        # the Lights page opens reflecting reality (mirrors the Dear PyGui app's
        # auto-load: load once per active-slot change, gathered across polls).
        self._loaded_led_slot = None
        self._led_loading = None        # slot awaiting replies, or None
        self._audio_reactive = False
        self._pickup_wake = False
        self._sleep_label = '10 min'
        self._loaded_frames = []        # list of frames, each = 4 hex strings

        # Per-profile config read-back + staged edits (Sticks/Triggers/Vibration).
        self._loaded_profile = None
        self._config_loading = None     # bank awaiting replies, or None
        self._config = {}               # friendly key -> loaded value
        self._pending = {}              # addr -> {'data','label','display'}
        self._backup_busy = False
        self._fw_busy = False

        self._input_timer = QTimer(self)
        self._input_timer.setInterval(16)        # ~60 Hz
        self._input_timer.timeout.connect(self._poll_input)
        self._input_timer.start()

        self._status_timer = QTimer(self)
        self._status_timer.setInterval(250)      # 4 Hz
        self._status_timer.timeout.connect(self._poll_status)
        self._status_timer.start()

        self._light_timer = QTimer(self)
        self._light_timer.setInterval(120)       # gather record/config read chunks
        self._light_timer.timeout.connect(self._poll_lighting)
        self._light_timer.timeout.connect(self._poll_config)
        self._light_timer.start()

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

    def _poll_lighting(self):
        """Read the active lighting slot's real state once, whenever the active
        slot first appears or changes. Reads queue on the reader thread and land
        over several polls; we publish once every chunk + power byte is in."""
        slot = state['led_slot']
        if (slot is not None and 0 <= slot <= 3
                and slot != self._loaded_led_slot and self._led_loading is None):
            self._loaded_led_slot = slot
            control.request_regs(led.record_read_fields(slot) + [
                (led.LED_BANK, led.AUDIO_REACTIVE, 1),
                (led.LED_BANK, led.PICKUP_WAKE, 1),
                (led.LED_BANK, led.SLEEP_TIMEOUT, 1),
            ])
            self._led_loading = slot

        slot = self._led_loading
        if slot is None:
            return
        recvals = {addr: control.reg_result(bank, addr)
                   for bank, addr, _ln in led.record_read_fields(slot)}
        audio = control.reg_result(led.LED_BANK, led.AUDIO_REACTIVE)
        pickup = control.reg_result(led.LED_BANK, led.PICKUP_WAKE)
        sleep = control.reg_result(led.LED_BANK, led.SLEEP_TIMEOUT)
        if (any(v is None for v in recvals.values())
                or audio is None or pickup is None or sleep is None):
            return                              # still waiting on replies

        self._led_loading = None
        record = led.stitch_record(slot, recvals)
        if record is None:
            return
        decoded = led.decode_record(record)

        self._audio_reactive = bool(audio[0])
        self._pickup_wake = bool(pickup[0])
        self._sleep_label = led.sleep_label(sleep[0])
        self._speed = decoded['speed']
        self._brightness = decoded['brightness']
        count = max(1, decoded['count'])
        self._loaded_frames = [[_hex(c) for c in fr] for fr in decoded['frames'][:count]]
        if self._loaded_frames:
            self._light_colors = list(self._loaded_frames[0])
        self.lightsChanged.emit()
        self.lightingLoaded.emit()

    def _poll_config(self):
        """Read the selected profile's config once whenever the profile changes.
        Switching profiles discards any unsaved edits (mirrors the DPG app)."""
        prof = state['profile']
        bank = cfg.profile_bank(prof)
        if (bank is not None and prof != self._loaded_profile
                and self._config_loading is None):
            self._loaded_profile = prof
            if self._pending:
                self._pending = {}
                self.pendingChanged.emit()
            reqs = [(bank, addr, ln) for addr, ln in cfg.READ_FIELDS]
            reqs += [(bank, addr, 2) for _n, addr in cfg.REMAP_SLOTS]
            control.request_regs(reqs)
            self._config_loading = bank

        bank = self._config_loading
        if bank is None:
            return
        vals = {addr: control.reg_result(bank, addr) for addr, _ln in cfg.READ_FIELDS}
        vals.update({addr: control.reg_result(bank, addr) for _n, addr in cfg.REMAP_SLOTS})
        if any(v is None for v in vals.values()):
            return
        self._config_loading = None
        self._config = self._build_config(vals)
        self.configLoaded.emit()

    @staticmethod
    def _build_config(vals):
        g = lambda a: vals[a][0]
        def curve(addr):
            blk = vals[addr]
            return {'type': cfg.curve_index(blk[0]),
                    'points': [list(p) for p in cfg.curve_points(blk)]}
        out = {
            'st_traj': cfg.enum_index(g(cfg.ST_TRAJ), cfg.TRAJ), 'st_curve': curve(cfg.ST_CURVE),
            'rs_traj': cfg.enum_index(g(cfg.RS_TRAJ), cfg.TRAJ), 'rs_curve': curve(cfg.RS_CURVE),
            'lt_hair': cfg.enum_index(g(cfg.LT_HAIR), cfg.HAIR_MODES), 'lt_curve': curve(cfg.LT_CURVE),
            'rt_hair': cfg.enum_index(g(cfg.RT_HAIR), cfg.HAIR_MODES), 'rt_curve': curve(cfg.RT_CURVE),
            'poll': min(g(cfg.POLL_RATE), 2),
        }
        for key, (addr, _lbl) in SCALARS.items():
            out[key] = g(addr)
        remap = {}
        for name, addr in cfg.REMAP_SLOTS:
            rec = vals[addr]
            remap[name] = cfg.remap_target_name(rec[0], rec[1] if len(rec) > 1 else 0)
        out['remap'] = remap
        return out

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

    # Read-back state (populated by _poll_lighting; QML refreshes on lightingLoaded)
    @Property(bool, notify=lightingLoaded)
    def audioReactive(self):
        return self._audio_reactive

    @Property(bool, notify=lightingLoaded)
    def pickupWake(self):
        return self._pickup_wake

    @Property(str, notify=lightingLoaded)
    def sleepLabel(self):
        return self._sleep_label

    @Property('QVariantList', notify=lightingLoaded)
    def loadedFrames(self):
        return [list(f) for f in self._loaded_frames]

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
        _led_retry(led.set_audio_reactive, bool(on))

    @Slot(bool)
    def setPickupWake(self, on):
        _led_retry(led.set_pickup_wake, bool(on))

    @Slot(str)
    def setSleepTimeout(self, label):
        _led_retry(led.set_sleep_timeout, led.sleep_raw(label))

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

    @Slot(int)
    def selectSlot(self, n):
        """Make lighting slot n active (the lighting profiles are independent of
        the hardware button profiles, so this is its own selector). Forces a
        re-read so the page reflects that slot."""
        state['led_slot'] = n                  # optimistic; the poll confirms it
        self._loaded_led_slot = None           # force _poll_lighting to reload
        _led_async(led.select_slot, n)

    @Slot()
    def restoreLighting(self):
        _led_async(led.restore_factory)

    # ------------------------------------------------------------- mouse mode
    @Property(bool, constant=True)
    def mouseModeAvailable(self):
        return kwin.available()

    @Property(bool, notify=mouseModeChanged)
    def mouseModeOn(self):
        v = kwin.is_enabled()
        return bool(v) if v is not None else False

    @Slot(bool)
    def setMouseMode(self, on):
        kwin.set_enabled(on)
        self.mouseModeChanged.emit()

    # ------------------------------------------------------------- backup/restore
    @Property(bool, notify=backupBusyChanged)
    def backupBusy(self):
        return self._backup_busy

    @staticmethod
    def _to_path(url_or_path):
        u = QUrl(url_or_path)
        return u.toLocalFile() if u.isLocalFile() else url_or_path

    @Property(str, constant=True)
    def defaultBackupName(self):
        return 'gamesir_backup_' + datetime.now().strftime('%Y%m%d') + '.json'

    def _backup_done(self, ok, msg):
        self._backup_busy = False
        self.backupBusyChanged.emit()
        self.backupStatus.emit(ok, msg)
        # A restore changes the device underneath us — re-read everything.
        self._loaded_profile = None
        self._loaded_led_slot = None

    @Slot(str)
    def exportBackup(self, url):
        if self._backup_busy:
            return
        self._backup_busy = True
        self.backupBusyChanged.emit()
        backup.export_async(self._to_path(url),
                            on_progress=lambda d, t: self.backupProgress.emit(d, t),
                            on_done=self._backup_done)

    @Slot(str)
    def importBackup(self, url):
        if self._backup_busy:
            return
        try:
            data = backup.load(self._to_path(url))
        except (OSError, ValueError) as e:
            self.backupStatus.emit(False, str(e))
            return
        self._backup_busy = True
        self.backupBusyChanged.emit()
        backup.apply_backup(data,
                            on_progress=lambda d, t: self.backupProgress.emit(d, t),
                            on_done=self._backup_done)

    # ------------------------------------------------------------- firmware flash
    # Mirrors the backup pattern: a worker thread drives gamesir_flash (enter
    # loader -> jl-uboot-tool write/read -> reset), reporting phase text. Loader
    # entry reuses the app's own command channel (control.send_cmd) so we don't
    # open a second hidraw handle alongside the reader thread.
    @Property(bool, notify=fwBusyChanged)
    def fwBusy(self):
        return self._fw_busy

    @Property('QVariantList', notify=fwVersionsChanged)
    def fwVersions(self):
        return [f['version'] for f in flash.list_firmware()
                if f['kind'] == 'fw' and f['product'] == flash.PRODUCT]

    def _fw_done(self, ok, msg):
        self._fw_busy = False
        self.fwBusyChanged.emit()
        self.fwStatus.emit(ok, msg)
        self.fwVersionsChanged.emit()      # a backup may have added a version
        self._loaded_profile = None        # device changed underneath us
        self._loaded_led_slot = None

    def _fw_run(self, work, done_msg):
        if self._fw_busy:
            return
        self._fw_busy = True
        self.fwBusyChanged.emit()

        def run():
            try:
                work()
                ok, msg = True, done_msg()
            except Exception as e:
                ok, msg = False, str(e)
            self._fw_done(ok, msg)
        threading.Thread(target=run, daemon=True).start()

    def _enter_loader_cmd(self):
        control.send_cmd(0x0F, 0x17, 0x55, 0x88)

    @Slot(str)
    def flashFirmware(self, version):
        prog = lambda p: self.fwProgress.emit(p)
        self._fw_run(
            lambda: flash.flash_version(version=version, on_progress=prog,
                                        send=self._enter_loader_cmd),
            lambda: f"Flashed firmware {version}.")

    @Slot(str)
    def backupFirmware(self, label):
        prog = lambda p: self.fwProgress.emit(p)
        out = {}
        def work():
            path, ver = flash.backup_current(label=label or None, on_progress=prog,
                                             send=self._enter_loader_cmd)
            out['ver'] = ver
        self._fw_run(work, lambda: f"Backed up firmware {out.get('ver', '')}.")

    # ------------------------------------------------------------- config editor
    @Property('QVariantMap', notify=configLoaded)
    def config(self):
        """The selected profile's read-back config (friendly key -> value). QML
        seeds its controls from this on configLoaded."""
        return dict(self._config)

    @Property('QVariantList', constant=True)
    def pollRates(self):
        return list(cfg.POLL_RATES)

    @Property('QVariantList', constant=True)
    def curveNames(self):
        return list(cfg.CURVE_NAMES)        # presets; QML adds "Custom"

    @Property('QVariantMap', constant=True)
    def curvePresets(self):
        """Preset name -> its three [x,y] control points, for the curve editor."""
        return {name: [list(p) for p in cfg.curve_points(blk)]
                for name, blk in cfg.CURVE_BLOCKS}

    @Property('QVariantList', constant=True)
    def hairModes(self):
        return [name for name, _ in cfg.HAIR_MODES]

    @Property(int, notify=pendingChanged)
    def pendingCount(self):
        return len(self._pending)

    @Property('QVariantList', notify=pendingChanged)
    def pendingList(self):
        return [self._pending[a]['label'] + ': ' + self._pending[a]['display']
                for a in sorted(self._pending)]

    def _queue(self, addr, data, label, display):
        if cfg.profile_bank(state['profile']) is None:
            return
        self._pending[addr] = {'data': list(data), 'label': label, 'display': str(display)}
        self.pendingChanged.emit()

    @Slot(str, int)
    def setScalar(self, key, value):
        addr, label = SCALARS[key]
        self._queue(addr, [max(0, min(255, int(value)))], label, str(int(value)))

    @Slot(str, int)
    def setTraj(self, side, index):
        name, code = cfg.TRAJ[index]
        self._queue(TRAJ_ADDR[side], [code],
                    ('Left' if side == 'st' else 'Right') + ' stick trajectory', name)

    @Slot(str, int)
    def setHair(self, side, index):
        name, data = cfg.HAIR_MODES[index]
        self._queue(HAIR_ADDR[side], list(data), side.upper() + ' hair-trigger', name)

    @Slot(str, int)
    def setPoll(self, index):
        self._queue(cfg.POLL_RATE, [index], 'Poll rate', cfg.POLL_RATES[index])

    @Property('QVariantList', constant=True)
    def remapSources(self):
        return [name for name, _ in cfg.REMAP_SLOTS]

    @Property('QVariantList', constant=True)
    def remapTargets(self):
        return list(cfg.REMAP_ITEMS)

    @Slot(str, str)
    def setRemap(self, source, target):
        addr = _REMAP_ADDR.get(source)
        if addr is not None:
            self._queue(addr, cfg.remap_write_bytes(target), 'Remap ' + source, target)

    @Slot(str, str, 'QVariantList')
    def setCurve(self, key, name, points):
        addr = CURVE_ADDR[key]
        if name == 'Custom':
            pts = [(int(p[0]), int(p[1])) for p in points]
            self._queue(addr, cfg.custom_curve_block(pts), key.upper() + ' curve', 'Custom')
        else:
            self._queue(addr, cfg.curve_block(name), key.upper() + ' curve', name)

    def _fold(self, addr, data):
        """Mirror a written value back into the cached config snapshot so the
        editor doesn't re-seed a stale value after Save (the 'second edit reverts
        the first' bug: the device was correct, but our cache wasn't)."""
        if addr in _ADDR_TO_SCALAR:
            self._config[_ADDR_TO_SCALAR[addr]] = data[0]
        elif addr in _ADDR_TO_CURVE:
            self._config[_ADDR_TO_CURVE[addr] + '_curve'] = {
                'type': cfg.curve_index(data[0]),
                'points': [list(p) for p in cfg.curve_points(data)]}
        elif addr in _ADDR_TO_TRAJ:
            self._config[_ADDR_TO_TRAJ[addr] + '_traj'] = cfg.enum_index(data[0], cfg.TRAJ)
        elif addr in _ADDR_TO_HAIR:
            self._config[_ADDR_TO_HAIR[addr] + '_hair'] = cfg.enum_index(data[0], cfg.HAIR_MODES)
        elif addr == cfg.POLL_RATE:
            self._config['poll'] = data[0]
        elif addr in _ADDR_TO_REMAP:
            rec = self._config.setdefault('remap', {})
            rec[_ADDR_TO_REMAP[addr]] = cfg.remap_target_name(
                data[0], data[1] if len(data) > 1 else 0)

    @Slot()
    def applyConfig(self):
        bank = cfg.profile_bank(state['profile'])
        if bank is None:
            return
        changes = [(a, r['data']) for a, r in self._pending.items()]
        for addr, data in changes:
            self._fold(addr, data)

        def run():
            for addr, data in changes:
                control.write_reg(bank, addr, data)
        threading.Thread(target=run, daemon=True).start()
        self._pending = {}
        self.pendingChanged.emit()

    @Slot()
    def discardConfig(self):
        self._pending = {}
        self.pendingChanged.emit()
        self.configLoaded.emit()        # snap controls back to last-loaded values

    @Slot()
    def resetProfileToDefault(self):
        """Rewrite the active profile to its factory out-of-box state (config +
        cleared remaps + default lighting), captured from the official app. Drops
        any staged edits and re-reads so every page reflects the reset."""
        bank = cfg.profile_bank(state['profile'])
        if bank is None:
            return
        self._pending = {}
        self.pendingChanged.emit()

        def run():
            factory.restore_default_profile(bank)
            self._loaded_profile = None     # force config re-read after writes land
            self._loaded_led_slot = None    # and lighting re-read
        threading.Thread(target=run, daemon=True).start()

    # ------------------------------------------------------------- user actions
    @Slot(int)
    def setProfile(self, n):
        control.set_profile(n)

    @Slot()
    def rumbleTest(self):
        control.rumble_test()
