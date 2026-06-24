"""
GameSir Cyclone 2 - per-profile config register map
===================================================
Offsets within a PROFILE bank. byte2 of the read/write command selects the
profile: bank 0x01..0x04 = profiles 1..4 (each a ~0x2a0-byte image). Bank 0x20
is lighting (handled in gamesir_led). Map reverse-engineered from USB captures
of the official app (see USBPcap Controller Tests/ + the assistant memory file).

Writes auto-persist to flash; no commit command is needed.

All scalar values are stored as raw 0..100 (percent) unless noted. The official
app rewrites a small block (mode byte + a few neighbours) for curves and the
hair-trigger toggle, so we replay the exact captured blocks for those.

EDIT BANK: edits target the SELECTED profile's own bank (profile 1..4 -> bank
0x01..0x04) via profile_bank(). An earlier theory had bank 0x01 as a live working
copy of whatever profile was active, but in practice that just wrote profile 1 no
matter which profile was selected, so we address each profile's bank directly.
"""

# --- scalar fields (addr, length) ------------------------------------------
VIB_L = 0x0020         # vibration strength left  (raw 0..100; default 75)
VIB_R = 0x0021         # vibration strength right (raw 0..100; default 75)
POLL_RATE = 0x002e     # 0=250Hz, 1=500Hz, 2=1000Hz (default 2)

LT_DZ_MIN = 0x01f1     # trigger (LT) deadzone min   (default 5)
LT_DZ_MAX = 0x01f2     # trigger (LT) deadzone max   (default 95)
LT_ADZ_MIN = 0x01f3    # trigger anti-deadzone min   (default 0)
LT_ADZ_MAX = 0x01f4    # trigger anti-deadzone max   (default 100)
LT_HAIR = 0x01fa       # hair-trigger mode (block, see HAIR_MODES)
LT_CURVE = 0x01fe      # trigger response curve (block, see CURVE_BLOCKS)

# Right trigger (RT): CONFIRMED as the LT block mirrored at +0x1c
# (16_rt_testing_complete.pcapng: dz/adz min+max, hair, and curve all landed at
# LT_* + 0x1c, matching the edit order exactly). No longer inferred.
RT_OFFSET = 0x1c
RT_DZ_MIN = LT_DZ_MIN + RT_OFFSET     # 0x020d
RT_DZ_MAX = LT_DZ_MAX + RT_OFFSET     # 0x020e
RT_ADZ_MIN = LT_ADZ_MIN + RT_OFFSET   # 0x020f
RT_ADZ_MAX = LT_ADZ_MAX + RT_OFFSET   # 0x0210
RT_HAIR = LT_HAIR + RT_OFFSET         # 0x0216
RT_CURVE = LT_CURVE + RT_OFFSET       # 0x021a

ST_TRAJ = 0x0227       # left stick trajectory: 0=circle, 1=raw
ST_DZ_MIN = 0x0229     # left stick deadzone min  (default 10)
ST_DZ_MAX = 0x022a     # left stick deadzone max  (default 100)
ST_ADZ_MIN = 0x022b    # left stick anti-dz min   (default 0)
ST_ADZ_MAX = 0x022c    # left stick anti-dz max   (default 100)
ST_CURVE = 0x022e      # left stick sensitivity curve (block, see CURVE_BLOCKS)

# Right stick (RS): CAPTURED as the left-stick block mirrored at +0x20
# (15_rs_testing.pcapng: trajectory/deadzone min+max/anti-dz min+max/curve all
# landed at ST_* + 0x20, matching the edit order). Confirmed, not inferred.
RS_OFFSET = 0x20
RS_TRAJ = ST_TRAJ + RS_OFFSET        # 0x0247
RS_DZ_MIN = ST_DZ_MIN + RS_OFFSET    # 0x0249
RS_DZ_MAX = ST_DZ_MAX + RS_OFFSET    # 0x024a
RS_ADZ_MIN = ST_ADZ_MIN + RS_OFFSET  # 0x024b
RS_ADZ_MAX = ST_ADZ_MAX + RS_OFFSET  # 0x024c
RS_CURVE = ST_CURVE + RS_OFFSET      # 0x024e

# --- enumerated fields ------------------------------------------------------
POLL_RATES = ['250 Hz', '500 Hz', '1000 Hz']        # index == raw value

TRAJ = [('Circle', 0x00), ('Raw', 0x01)]

# Hair-trigger: the app writes mode + a couple of neighbour bytes. Replay them.
HAIR_MODES = [
    ('Off',      [0x00, 0x0a, 0x5a]),
    ('Adaptive', [0x81, 0x01, 0x64]),
    ('Fixed',    [0x82]),
]

# Response curves (shared format for trigger 0x01fe and stick 0x022e):
#   [type, 0x64, 0x00, 0x00, p0, p1, p2, p3, p4, p5]
# 'Custom' is whatever the user drew in the app; we only offer the 3 presets.
CURVE_BLOCKS = [
    ('Linear',  [0x00, 0x64, 0x00, 0x00, 0x28, 0x29, 0x80, 0x80, 0xd7, 0xd6]),
    ('Concave', [0x01, 0x64, 0x00, 0x00, 0x5e, 0x17, 0xb0, 0x4f, 0xe8, 0xa1]),
    ('S-Curve', [0x02, 0x64, 0x00, 0x00, 0x28, 0x4d, 0x80, 0x80, 0xd7, 0xb3]),
]
CURVE_NAMES = [name for name, _ in CURVE_BLOCKS]
CURVE_ITEMS = CURVE_NAMES + ['Custom']   # Custom = user-drawn control points

# A custom curve is three (x, y) control points (each 0..255) written under
# type byte 0x03, in the same 10-byte block format as the presets. The default
# shape is Linear's points (a sane neutral starting curve).
CUSTOM_TYPE = 0x03
CUSTOM_DEFAULT = [(0x28, 0x29), (0x80, 0x80), (0xd7, 0xd6)]


def curve_block(name):
    """Bytes to write for a curve selection. A preset writes its full block;
    'Custom' (no points given) falls back to the default custom shape. The GUI
    normally passes points via custom_curve_block() for a complete definition."""
    for n, blk in CURVE_BLOCKS:
        if n == name:
            return blk
    return custom_curve_block(CUSTOM_DEFAULT)


def custom_curve_block(points):
    """10-byte block for a custom curve from three (x, y) control points
    (each clamped 0..255): [0x03, 0x64, 0x00, 0x00, x0,y0,x1,y1,x2,y2]."""
    flat = []
    for x, y in points:
        flat += [max(0, min(255, int(x))), max(0, min(255, int(y)))]
    return [CUSTOM_TYPE, 0x64, 0x00, 0x00, *flat]


def curve_points(block):
    """Decode a stored curve block's three (x, y) control points from bytes
    4..9. Falls back to CUSTOM_DEFAULT if the block is too short."""
    if len(block) < 10:
        return [tuple(p) for p in CUSTOM_DEFAULT]
    pts = block[4:10]
    return [(pts[0], pts[1]), (pts[2], pts[3]), (pts[4], pts[5])]


def curve_index(value):
    """Combo index for a stored curve type byte (-> 'Custom' if not a preset)."""
    idx = enum_index(value, CURVE_BLOCKS, default=-1)
    return idx if idx >= 0 else len(CURVE_BLOCKS)


def profile_bank(profile):
    """Profile number (1..4) IS the register bank. None when unknown."""
    return profile if profile in (1, 2, 3, 4) else None


# Reads needed to populate the editor: (addr, length) per scalar/block field.
# The reader thread fulfils these against the active profile bank.
# Curve blocks read 10 bytes (type + the three control points) so the custom
# editor can repopulate; all other fields are single scalars.
READ_FIELDS = [
    (VIB_L, 1), (VIB_R, 1), (POLL_RATE, 1),
    (LT_DZ_MIN, 1), (LT_DZ_MAX, 1), (LT_ADZ_MIN, 1), (LT_ADZ_MAX, 1),
    (LT_HAIR, 1), (LT_CURVE, 10),
    (RT_DZ_MIN, 1), (RT_DZ_MAX, 1), (RT_ADZ_MIN, 1), (RT_ADZ_MAX, 1),
    (RT_HAIR, 1), (RT_CURVE, 10),
    (ST_TRAJ, 1), (ST_DZ_MIN, 1), (ST_DZ_MAX, 1),
    (ST_ADZ_MIN, 1), (ST_ADZ_MAX, 1), (ST_CURVE, 10),
    (RS_TRAJ, 1), (RS_DZ_MIN, 1), (RS_DZ_MAX, 1),
    (RS_ADZ_MIN, 1), (RS_ADZ_MAX, 1), (RS_CURVE, 10),
]


# Human-readable name per config address, for labelled backups (see
# gamesir_backup). Remap-record addresses are named from REMAP_SLOTS instead
# (see field_name), so they're not duplicated here.
FIELD_NAMES = {
    VIB_L: 'Vibration L', VIB_R: 'Vibration R', POLL_RATE: 'Poll rate',
    LT_DZ_MIN: 'LT deadzone min', LT_DZ_MAX: 'LT deadzone max',
    LT_ADZ_MIN: 'LT anti-deadzone min', LT_ADZ_MAX: 'LT anti-deadzone max',
    LT_HAIR: 'LT hair-trigger', LT_CURVE: 'LT response curve',
    RT_DZ_MIN: 'RT deadzone min', RT_DZ_MAX: 'RT deadzone max',
    RT_ADZ_MIN: 'RT anti-deadzone min', RT_ADZ_MAX: 'RT anti-deadzone max',
    RT_HAIR: 'RT hair-trigger', RT_CURVE: 'RT response curve',
    ST_TRAJ: 'Left stick trajectory', ST_DZ_MIN: 'Left stick deadzone min',
    ST_DZ_MAX: 'Left stick deadzone max', ST_ADZ_MIN: 'Left stick anti-deadzone min',
    ST_ADZ_MAX: 'Left stick anti-deadzone max', ST_CURVE: 'Left stick curve',
    RS_TRAJ: 'Right stick trajectory', RS_DZ_MIN: 'Right stick deadzone min',
    RS_DZ_MAX: 'Right stick deadzone max', RS_ADZ_MIN: 'Right stick anti-deadzone min',
    RS_ADZ_MAX: 'Right stick anti-deadzone max', RS_CURVE: 'Right stick curve',
}


def enum_index(value, table, default=0):
    """Index of the row in `table` whose code (table[i][1] or table[i][1][0])
    matches `value`; default if none match (e.g. a Custom curve)."""
    for i, (_name, code) in enumerate(table):
        head = code[0] if isinstance(code, list) else code
        if head == value:
            return i
    return default


# --- button remap ----------------------------------------------------------
# Each remappable input has a 7-byte record; we only touch its first two bytes:
#   [enabled (0x01/0x00), target_code]
# leaving the rest (turbo/macro params) untouched. Clearing = [0x00, 0x00].
# Decoded from captures 10_*..14_*. '*' = inferred from the regular 7-byte stride
# / "code == index+1" pattern rather than directly captured (high confidence).

REMAP_SLOTS = [           # SOURCE button -> its record address (bank 0x01)
    ('Dpad Up',    0x0042),
    ('Dpad Down',  0x0049),
    ('Dpad Left',  0x0050),
    ('Dpad Right', 0x0057),   # *
    ('LB',         0x005e),
    ('RB',         0x0065),
    ('LS',         0x006c),
    ('RS',         0x0073),
    ('A',          0x007a),
    ('B',          0x0081),
    ('X',          0x0088),
    ('Y',          0x008f),
    ('L4',         0x00b2),
    ('R4',         0x0151),
    ('LT',         0x01f5),
    ('RT',         0x0211),
]

REMAP_TARGETS = [         # what a source can be mapped TO -> code byte
    ('Dpad Up',    0x01),     # *
    ('Dpad Down',  0x02),     # *
    ('Dpad Left',  0x03),     # *
    ('Dpad Right', 0x04),
    ('LB',         0x05),
    ('RB',         0x06),
    ('LS',         0x07),
    ('RS',         0x08),     # *
    ('A',          0x09),
    ('B',          0x0a),
    ('X',          0x0b),
    ('Y',          0x0c),
    ('LT',         0x13),
    ('RT',         0x14),
    ('Disabled',   0xff),
]
REMAP_NONE = 'Default'    # not remapped; written as [00 00]
REMAP_ITEMS = [REMAP_NONE] + [name for name, _ in REMAP_TARGETS]


def remap_target_name(enable, code):
    """Combo label for a record's [enable, code] bytes."""
    if not enable:
        return REMAP_NONE
    for name, c in REMAP_TARGETS:
        if c == code:
            return name
    return f'0x{code:02x}'    # captured something we haven't named yet


def remap_write_bytes(target_name):
    """The 2 bytes to write for a chosen target ('Default' clears the remap)."""
    if target_name == REMAP_NONE:
        return [0x00, 0x00]
    for name, c in REMAP_TARGETS:
        if name == target_name:
            return [0x01, c]
    return [0x00, 0x00]


def field_name(addr):
    """Human-readable label for a config/remap address, for readable backups.
    Falls back to the bare hex address if we haven't named it."""
    if addr in FIELD_NAMES:
        return FIELD_NAMES[addr]
    for name, a in REMAP_SLOTS:
        if a == addr:
            return f'Remap {name}'
    return f'0x{addr:04x}'
