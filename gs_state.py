"""
GameSir Cyclone 2 - shared live state
=====================================
One mutable dict updated by the reader thread and read by the GUI loop. Kept in
its own dependency-free module so every layer can import it by reference without
creating an import cycle.
"""

# Live controller state. The reader thread writes it; the GUI reads it.
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
    'firmware': None,    # firmware version string from USB bcdDevice (e.g. '3.52')
    'controller': None,  # detected model short name ('Cyclone 2'/'G7'), else None
    'controllers': [],   # all connected controllers: [{id, name, port, pid}]
    'selected': None,    # id (USB port) of the controller currently being driven
}

EXTRA_BTNS = ('l4', 'r4', 'm', 'home', 'share')
