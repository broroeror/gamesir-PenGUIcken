"""
GameSir controller PROFILES  (multi-controller abstraction)
===========================================================
A `ControllerProfile` bundles everything that differs between GameSir models:
USB identity, the register-write transport, the config register map, and the
enum/block formats. The app selects the profile for whichever controller is
plugged in, so the rest of the stack (bridge, editor) works against one
controller = one profile of addresses, instead of hard-coded Cyclone constants.

Key reverse-engineering result that makes this tidy: across GameSir's vendor
family the *internal* layout of the trigger and stick config blocks is IDENTICAL
(hair at base+0x09, curve at base+0x0d, stick DZ at base+0x02, RT mirror +0x1c,
RS mirror +0x20). Only the block BASE addresses move between models. Likewise the
curve-block format, hair-trigger modes, trajectory codes and remap TARGET codes
are shared. So a profile is mostly: {USB PID, a handful of base addresses}.

Two profiles are defined:
  * CYCLONE  - GameSir Cyclone 2 (3537:0575 / 3537:100b). Sourced from the
               existing, battle-tested `gamesir_config` so there is a single
               source of truth for the Cyclone and nothing changes for it.
  * G7       - GameSir G7 (3537:10ba). From the G7 USB-capture RE (see the
               `g7-protocol-findings` memory).

Runtime wiring (making the bridge apply/read against the active profile, plus
the G7 write envelope and GIP input parsing) is the next stage; this module is
the data + detection foundation and is safe to import without touching Cyclone.
"""

from dataclasses import dataclass, field
from typing import Optional

import gamesir_config as _cy


# --- shared enums / block formats (identical across the vendor family) -------
# Response curves (shared 10-byte format for triggers and sticks):
#   [type, 0x64, 0x00, 0x00, x0,y0, x1,y1, x2,y2]
# type: 0x00 linear, 0x01 curve/concave, 0x02 s-curve, 0x03 custom (user points)
CURVE_BLOCKS = list(_cy.CURVE_BLOCKS)      # reuse the exact captured presets
CURVE_NAMES = [n for n, _ in CURVE_BLOCKS]
CURVE_ITEMS = CURVE_NAMES + ['Custom']

# Hair-trigger: mode byte + a couple of neighbours the app replays.
HAIR_MODES = list(_cy.HAIR_MODES)          # Off / Adaptive / Fixed

TRAJ = list(_cy.TRAJ)                       # ('Circle',0)/('Raw',1)

# Button remap TARGET codes: confirmed shared between Cyclone and G7 (A=0x09,
# B=0x0a, X=0x0b, Y=0x0c, LB=0x05..RT=0x14). See gamesir_config.REMAP_TARGETS.
REMAP_TARGETS = list(_cy.REMAP_TARGETS)
REMAP_NONE = _cy.REMAP_NONE
REMAP_ITEMS = [REMAP_NONE] + [n for n, _ in REMAP_TARGETS]


@dataclass
class ControllerProfile:
    """One controller model expressed as identity + a register-address map.

    Config addresses are absolute offsets within a profile bank. Fields a model
    lacks are left as None. RT_*/RS_* mirror addresses are derived in
    __post_init__ from the LT_/ST_ bases plus the per-model mirror offset.
    """
    name: str                              # display name
    short: str                             # short label (status line)
    usb_products: tuple                    # USB product ids that identify it
    write_style: str = 'cyclone'           # 'cyclone' bare 0f03 / 'g7' enveloped
    input_style: str = 'cyclone_0x12'      # 'cyclone_0x12' (vendor hidraw) / 'evdev'
    profile_banks: tuple = (1, 2, 3, 4)    # banks that hold editable profiles

    # vibration
    VIB_L: Optional[int] = None
    VIB_R: Optional[int] = None

    # poll / report rate (address AND encoding vary; see poll_rates)
    POLL_RATE: Optional[int] = None
    POLL_RATES: tuple = tuple(_cy.POLL_RATES)

    # trigger block: LT base + these fixed intra-block offsets, RT = +RT_OFFSET
    LT_DZ_MIN: Optional[int] = None
    LT_DZ_MAX: Optional[int] = None
    LT_ADZ_MIN: Optional[int] = None
    LT_ADZ_MAX: Optional[int] = None
    LT_HAIR: Optional[int] = None
    LT_CURVE: Optional[int] = None
    RT_OFFSET: int = 0x1c

    # stick block: LS base fields, RS = +RS_OFFSET
    ST_TRAJ: Optional[int] = None
    ST_DZ_MIN: Optional[int] = None
    ST_DZ_MAX: Optional[int] = None
    ST_ADZ_MIN: Optional[int] = None
    ST_ADZ_MAX: Optional[int] = None
    ST_CURVE: Optional[int] = None
    RS_OFFSET: int = 0x20

    # enum/format tables (shared defaults; a model can override)
    TRAJ: tuple = tuple(TRAJ)
    HAIR_MODES: tuple = tuple(HAIR_MODES)
    CURVE_BLOCKS: tuple = tuple(CURVE_BLOCKS)
    REMAP_TARGETS: tuple = tuple(REMAP_TARGETS)
    REMAP_SLOTS: tuple = ()                 # (name, addr) source-button records

    # model-specific registers not in the common set (name -> addr), e.g. the
    # G7's trigger-vibration, resolution, dpad options and dock settings.
    extras: dict = field(default_factory=dict)

    # RT_*/RS_* derived mirrors (filled by __post_init__)
    RT_DZ_MIN: Optional[int] = field(default=None, init=False)
    RT_DZ_MAX: Optional[int] = field(default=None, init=False)
    RT_ADZ_MIN: Optional[int] = field(default=None, init=False)
    RT_ADZ_MAX: Optional[int] = field(default=None, init=False)
    RT_HAIR: Optional[int] = field(default=None, init=False)
    RT_CURVE: Optional[int] = field(default=None, init=False)
    RS_TRAJ: Optional[int] = field(default=None, init=False)
    RS_DZ_MIN: Optional[int] = field(default=None, init=False)
    RS_DZ_MAX: Optional[int] = field(default=None, init=False)
    RS_ADZ_MIN: Optional[int] = field(default=None, init=False)
    RS_ADZ_MAX: Optional[int] = field(default=None, init=False)
    RS_CURVE: Optional[int] = field(default=None, init=False)

    def __post_init__(self):
        def mirror(base, off):
            return None if base is None else base + off
        self.RT_DZ_MIN = mirror(self.LT_DZ_MIN, self.RT_OFFSET)
        self.RT_DZ_MAX = mirror(self.LT_DZ_MAX, self.RT_OFFSET)
        self.RT_ADZ_MIN = mirror(self.LT_ADZ_MIN, self.RT_OFFSET)
        self.RT_ADZ_MAX = mirror(self.LT_ADZ_MAX, self.RT_OFFSET)
        self.RT_HAIR = mirror(self.LT_HAIR, self.RT_OFFSET)
        self.RT_CURVE = mirror(self.LT_CURVE, self.RT_OFFSET)
        self.RS_TRAJ = mirror(self.ST_TRAJ, self.RS_OFFSET)
        self.RS_DZ_MIN = mirror(self.ST_DZ_MIN, self.RS_OFFSET)
        self.RS_DZ_MAX = mirror(self.ST_DZ_MAX, self.RS_OFFSET)
        self.RS_ADZ_MIN = mirror(self.ST_ADZ_MIN, self.RS_OFFSET)
        self.RS_ADZ_MAX = mirror(self.ST_ADZ_MAX, self.RS_OFFSET)
        self.RS_CURVE = mirror(self.ST_CURVE, self.RS_OFFSET)

    # --- read plan: (addr, length) reads to populate the editor -------------
    def read_fields(self):
        """(addr, length) pairs for every supported field; curve blocks read 10
        bytes (type + 3 control points), scalars read 1. Skips unsupported
        (None) fields so a model only reads what it has."""
        singles = [self.VIB_L, self.VIB_R, self.POLL_RATE,
                   self.LT_DZ_MIN, self.LT_DZ_MAX, self.LT_ADZ_MIN,
                   self.LT_ADZ_MAX, self.LT_HAIR,
                   self.RT_DZ_MIN, self.RT_DZ_MAX, self.RT_ADZ_MIN,
                   self.RT_ADZ_MAX, self.RT_HAIR,
                   self.ST_TRAJ, self.ST_DZ_MIN, self.ST_DZ_MAX,
                   self.ST_ADZ_MIN, self.ST_ADZ_MAX,
                   self.RS_TRAJ, self.RS_DZ_MIN, self.RS_DZ_MAX,
                   self.RS_ADZ_MIN, self.RS_ADZ_MAX]
        blocks = [self.LT_CURVE, self.RT_CURVE, self.ST_CURVE, self.RS_CURVE]
        fields = [(a, 1) for a in singles if a is not None]
        fields += [(a, 10) for a in blocks if a is not None]
        return fields

    def profile_bank(self, profile):
        """Profile number -> register bank (identity map for these models)."""
        return profile if profile in self.profile_banks else None


# --- Cyclone 2 : sourced verbatim from the proven gamesir_config -------------
CYCLONE = ControllerProfile(
    name='GameSir Cyclone 2',
    short='Cyclone 2',
    # 0575 = extras/macro mode, 100b = pure XInput; 1053 = XInput identity of the
    # firmware images in the flash library (a flashed unit enumerates as this).
    usb_products=(0x0575, 0x100b, 0x1053),
    write_style='cyclone',
    input_style='cyclone_0x12',
    profile_banks=(1, 2, 3, 4),
    VIB_L=_cy.VIB_L, VIB_R=_cy.VIB_R,
    POLL_RATE=_cy.POLL_RATE,
    LT_DZ_MIN=_cy.LT_DZ_MIN, LT_DZ_MAX=_cy.LT_DZ_MAX,
    LT_ADZ_MIN=_cy.LT_ADZ_MIN, LT_ADZ_MAX=_cy.LT_ADZ_MAX,
    LT_HAIR=_cy.LT_HAIR, LT_CURVE=_cy.LT_CURVE, RT_OFFSET=_cy.RT_OFFSET,
    ST_TRAJ=_cy.ST_TRAJ, ST_DZ_MIN=_cy.ST_DZ_MIN, ST_DZ_MAX=_cy.ST_DZ_MAX,
    ST_ADZ_MIN=_cy.ST_ADZ_MIN, ST_ADZ_MAX=_cy.ST_ADZ_MAX,
    ST_CURVE=_cy.ST_CURVE, RS_OFFSET=_cy.RS_OFFSET,
    REMAP_SLOTS=tuple(_cy.REMAP_SLOTS),
)


# --- G7 : from the G7 USB-capture reverse-engineering ------------------------
# Config rides the same register protocol as the Cyclone but wrapped in a
# sequenced envelope (write_style='g7'); input is GIP on the interrupt endpoint.
# Trigger LT base 0x00cf (RT +0x1c), stick LS base 0x013d (RS +0x20). The block
# internal offsets match the Cyclone, only the bases differ.
G7 = ControllerProfile(
    name='GameSir G7',
    short='G7',
    usb_products=(0x10ba,),
    write_style='g7',
    input_style='evdev',
    profile_banks=(1,),                     # single editable bank observed
    VIB_L=0x0020, VIB_R=0x0021,             # grip vibration L/R
    POLL_RATE=0x0030,                       # report rate (encoding differs)
    LT_DZ_MIN=0x00cf, LT_DZ_MAX=0x00d0,
    LT_ADZ_MIN=0x00d1, LT_ADZ_MAX=0x00d2,
    LT_HAIR=0x00d8, LT_CURVE=0x00dc, RT_OFFSET=0x1c,
    ST_TRAJ=0x013d, ST_DZ_MIN=0x013f, ST_DZ_MAX=0x0140,
    ST_ADZ_MIN=0x0141, ST_ADZ_MAX=0x0142,
    ST_CURVE=0x0144, RS_OFFSET=0x20,
    # Button remaps: same stride/target codes as the Cyclone, plus L5/R5 paddles.
    REMAP_SLOTS=(
        ('Dpad Up',    0x0042),
        ('RS',         0x0073),
        ('A',          0x007a),
        ('B',          0x0081),
        ('L4',         0x00b2),
        ('L5',         0x00b9),
        ('R4',         0x00c0),
        ('R5',         0x00c7),
    ),
    # G7-only registers, kept here until the editor grows fields for them.
    extras={
        'VIB_TRIG_L': 0x0022, 'VIB_TRIG_R': 0x0023,   # trigger-motor strength
        'VIB_MODE_L': 0x0024, 'VIB_MODE_R': 0x0025,   # 0 off/1 force/2 sync
        'DPAD_SWAP': 0x002b, 'DPAD_LOCK': 0x002d,
        'RESOLUTION': 0x0032,                          # 04=12-bit / 00=8-bit
        'LT_HAIR_MIN': 0x00d9, 'LT_HAIR_MAX': 0x00da,
        'RT_HAIR_MIN': 0x00f5, 'RT_HAIR_MAX': 0x00f6,
        'ST_INVERT_X': 0x0151, 'ST_INVERT_Y': 0x0152, 'ST_SENS': 0x0153,
        'RS_INVERT_X': 0x0171, 'RS_INVERT_Y': 0x0172, 'RS_SENS': 0x0173,
        'DOCK_AUTO': 0x01f6, 'DOCK_BRIGHT': 0x01f9,    # bank 0x20
    },
)


# --- G7 Pro : GameSir G7 Pro (3537:1022) ------------------------------------
# A different model from the plain G7: a standard HID composite (HID gamepad on
# one interface, keyboard/mouse/consumer + a vendor 0xfff0 collection on another)
# rather than a GIP/Xbox device. Live input comes over evdev (the standard
# gamepad interface). Its config protocol (over the 0xfff0 vendor node) is NOT
# yet reverse-engineered, so config fields are unset (TODO: capture the G7 Pro).
G7_PRO = ControllerProfile(
    name='GameSir G7 Pro',
    short='G7 Pro',
    usb_products=(0x1022,),
    write_style='g7',
    input_style='evdev',
    profile_banks=(1,),
)


# --- registry + detection ----------------------------------------------------
ALL = (CYCLONE, G7, G7_PRO)
DEFAULT = CYCLONE


def by_product_id(pid):
    """ControllerProfile for a USB product id, or None if unrecognised."""
    for prof in ALL:
        if pid in prof.usb_products:
            return prof
    return None


def detect(product_ids):
    """Pick a profile from an iterable of connected GameSir product ids.
    Returns the first recognised profile, else None."""
    for pid in product_ids or ():
        prof = by_product_id(pid)
        if prof is not None:
            return prof
    return None


# --- active profile ----------------------------------------------------------
# The rest of the app addresses the connected controller through the ACTIVE
# profile. The reader sets it on connect (detect -> set_active); everything else
# reads it via active(). Defaults to the Cyclone so behaviour is unchanged when
# nothing is plugged in yet.
_active = DEFAULT


def active():
    """The profile for the currently connected controller (Cyclone default)."""
    return _active


def set_active(prof):
    """Set the active profile (None -> fall back to the default)."""
    global _active
    _active = prof or DEFAULT
