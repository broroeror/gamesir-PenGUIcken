"""
KWin "Game Controller" plugin toggle (KDE Plasma 6.7+)
======================================================
"Mouse mode" - the sticks driving the desktop cursor after a dongle re-pair - is
KDE's KWin Game Controller plugin (maps sticks -> pointer, triggers -> clicks,
reading the joystick evdev node directly). This module reads/sets that plugin's
enabled flag in ~/.config/kwinrc, so the in-app toggle can turn it OFF (normal
gamepad) or ON (couch/bed cursor control) the clean, gaming-safe way - games read
evdev directly and are unaffected either way.

This is the same setting as System Settings -> Game Controller; it persists.
Falls back to nothing on non-KDE sessions (available() returns False), where the
app uses the EVIOCGRAB suppressor in gamesir_mousegrab.py instead.
"""

import os
import shutil
import subprocess

GROUP = 'Plugins'
KEY = 'gamecontrollerEnabled'
PLUGIN = 'gamecontroller'   # KWin's internal plugin id (org.kde.KWin.Plugins)


def _qdbus():
    return shutil.which('qdbus6') or shutil.which('qdbus')


def _plugins(method, *args):
    """Call org.kde.KWin.Plugins.<method>. Returns the command's stdout (str)
    on success, or None if qdbus is missing / the call failed. This is the live
    load/unload mechanism — loading the plugin enables couch mode *immediately*,
    which a plain `reconfigure` did not do for enabling."""
    q = _qdbus()
    if not q:
        return None
    try:
        r = subprocess.run([q, 'org.kde.KWin', '/Plugins',
                            'org.kde.KWin.Plugins.' + method, *args],
                           capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def available():
    """True if this is a KDE session with the kconfig CLI tools present."""
    if not (shutil.which('kwriteconfig6') and shutil.which('kreadconfig6')):
        return False
    desk = (os.environ.get('XDG_CURRENT_DESKTOP', '') + ':' +
            os.environ.get('XDG_SESSION_DESKTOP', '')).upper()
    return 'KDE' in desk or 'PLASMA' in desk


def is_enabled():
    """Current plugin state. Prefer the live loaded-plugin list (ground truth);
    fall back to the kwinrc flag if D-Bus is unavailable. An unset kwinrc key
    means KWin's default, which is enabled. Returns None if nothing is readable."""
    loaded = _plugins('LoadedPlugins')
    if loaded is not None:
        return PLUGIN in loaded.split()
    try:
        out = subprocess.run(
            ['kreadconfig6', '--file', 'kwinrc', '--group', GROUP, '--key', KEY],
            capture_output=True, text=True, timeout=5).stdout.strip().lower()
    except (OSError, subprocess.SubprocessError):
        return None
    if out in ('true', 'false'):
        return out == 'true'
    return True


def set_enabled(on):
    """Apply the mouse-mode (couch) setting both live and persistently.

    1. Write the kwinrc flag so the choice survives a relogin and matches what
       System Settings -> Game Controller shows.
    2. Load / unload the plugin over D-Bus so it takes effect *now*. Loading is
       what previously needed a logout; LoadPlugin makes enabling instant.

    Returns True if either the live apply or the persisted write succeeded."""
    val = 'true' if on else 'false'
    ok_cfg = True
    try:
        subprocess.run(['kwriteconfig6', '--file', 'kwinrc', '--group', GROUP,
                        '--key', KEY, val], check=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        ok_cfg = False

    live = _plugins('LoadPlugin' if on else 'UnloadPlugin', PLUGIN)
    if live is None:
        # No plugin D-Bus call possible — fall back to asking KWin to reread
        # config (works reliably for disabling, less so for enabling).
        q = _qdbus()
        if q:
            try:
                subprocess.run([q, 'org.kde.KWin', '/KWin', 'reconfigure'],
                               timeout=5)
            except (OSError, subprocess.SubprocessError):
                pass
        return ok_cfg

    return True
