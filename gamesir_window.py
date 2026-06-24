"""
GameSir Cyclone 2 - viewport placement
======================================
Platform/window-manager glue, split out of the GUI view layer: figure out the
primary monitor's geometry (X11/XWayland via xrandr) and park the DearPyGui
viewport somewhere reachable on it. Pure OS/placement code with no GUI state.
"""

import re
import subprocess

import dearpygui.dearpygui as dpg


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
