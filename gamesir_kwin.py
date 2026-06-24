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


def available():
    """True if this is a KDE session with the kconfig CLI tools present."""
    if not (shutil.which('kwriteconfig6') and shutil.which('kreadconfig6')):
        return False
    desk = (os.environ.get('XDG_CURRENT_DESKTOP', '') + ':' +
            os.environ.get('XDG_SESSION_DESKTOP', '')).upper()
    return 'KDE' in desk or 'PLASMA' in desk


def is_enabled():
    """Current plugin state from kwinrc, or None if it can't be read. An unset
    key means KWin's default, which is enabled."""
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
    """Write the flag and ask KWin to reload live. The kwinrc value persists
    regardless; a relogin applies it if the live reconfigure is flaky (which it
    can be for *enabling*). Returns True if the write succeeded."""
    val = 'true' if on else 'false'
    try:
        subprocess.run(['kwriteconfig6', '--file', 'kwinrc', '--group', GROUP,
                        '--key', KEY, val], check=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return False
    qdbus = shutil.which('qdbus6') or shutil.which('qdbus')
    if qdbus:
        try:
            subprocess.run([qdbus, 'org.kde.KWin', '/KWin', 'reconfigure'],
                           timeout=5)
        except (OSError, subprocess.SubprocessError):
            pass
    return True
