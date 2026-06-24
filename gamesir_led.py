"""
GameSir Cyclone 2 - LED / RGB domain
====================================
Lighting lives in register bank 0x20 (NOT the per-profile config bank):
  0x0000          = active effect selector (the preset slot to show)
  0x0001 + M*0x7c = 124-byte record for slot M (M = 0..4)
  record +2       = animation speed (1..20);  record +3 = brightness (0..0x64)
  record +4..     = RGB triplet palette (8 frames x 5 lights for animated effects)
  0x026d ..       = global power block (right after the 5 records):
                    0x026d = audio-reactive, 0x0272 = pick-up-to-wake,
                    0x0273 = sleep-when-inactive timeout in minutes (0 = never)
A solid color = fill the palette with one repeated (R,G,B); brightness 0 = off.
Speed/brightness/power settings are single live byte-writes (matching the app).

The record renders as 5-triplet FRAMES (4 lights + a trailing duplicate). Zeroing
the tail leaves a broken frame that drops the Profile LED, so we tile an IDENTICAL
frame across the whole record -> static, fully lit, no animation.
"""

from gamesir_control import write_reg, send_cmd
from gamesir_led_factory import FACTORY_START, FACTORY_DATA
from gs_state import state

LED_BANK = 0x20
LED_REC = 0x7c
LED_SLOT = 1          # the preset slot the GUI writes to / activates
LED_TRIPLETS = 40     # palette capacity within one 124-byte record
FRAME_TRIPLETS = 5    # the LED render frame size (tiled to fill the record)
NUM_FRAMES = 8        # animated effects cycle 8 frames (8 * 5 triplets = 40)
KEYFRAME_TYPE = 0x05  # effect type that plays the palette as cycling keyframes
                      # (the app's "flow"; confirmed = the custom-animation engine)

REC_SPEED_OFF = 2     # within a record: +2 = animation speed (device 1..20)
REC_BRIGHT_OFF = 3    # within a record: +3 = brightness (0..0x64)

# Speed: the device byte is INVERTED vs intuition (1 = fastest, 20 = slowest).
# The GUI shows 1..20 with higher = faster, so we flip between UI and raw.
SPEED_MIN, SPEED_MAX = 1, 20

# Global power/lighting settings, in the block right after the 5 slot records.
AUDIO_REACTIVE = 0x026d   # 0 = off, 1 = on
PICKUP_WAKE = 0x0272      # 0 = off, 1 = on
SLEEP_TIMEOUT = 0x0273    # minutes of inactivity before sleep; 0 = never
SLEEP_OPTIONS = [('Off', 0x00), ('1 min', 0x01), ('5 min', 0x05),
                 ('10 min', 0x0a), ('20 min', 0x14)]   # the app's choices

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


def _resolve_slot(slot):
    """Default to the slot the controller currently shows (so we don't clobber a
    different preset), falling back to LED_SLOT until that's known."""
    if slot is not None:
        return slot
    return state['led_slot'] if state['led_slot'] is not None else LED_SLOT


def _write_slot(record, slot):
    """Write a 124-byte record to `slot` and make it the active effect."""
    write_reg(LED_BANK, 0x0001 + slot * LED_REC, record[:LED_REC])
    write_reg(LED_BANK, 0x0000, [slot])   # select it


def set_lights(colors, brightness=100, slot=None):
    """Write a per-light palette and make it the active effect. `colors` is a
    list of (r,g,b), one per light in index order; brightness 0..100 (0 = off)."""
    slot = _resolve_slot(slot)
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
    _write_slot([0x01, 0x05, 0x14, bri] + flat, slot)


def set_keyframes(frames, speed=10, brightness=100, slot=None):
    """Write a user-built animation to the active slot and select it. `frames` is
    1..8 frames, each a list of (r,g,b) per light in LIGHTS order
    [Left, Right, Profile, Home]. Stored as effect type 0x05 (the firmware's
    keyframe engine).

    Record layout for the palette engine: header [COUNT, 0x05, speed, brightness]
    then `count` 5-triplet frames. Byte 0 is the keyframe COUNT and byte 1 is the
    constant 0x05 format marker (the same engine drives every animated preset -
    Rainbow=8 frames, Pulse=2, Alarm=6, Flow=5, static=1 - they differ only by
    count + palette). Proven by capture 19: the official app's Add/Remove keyframe
    just writes a single byte = the new count to record byte 0 (bank 0x20 addr
    0x0001), touching no frame data. The firmware plays exactly that many frames.

    Earlier code wrote [0x05, count, ...] - byte 0 = 0x05 - so the device read the
    count as 5 for EVERY animation: a 3-frame loop played 5 frames (2 ghosts that
    looked like a hang), and an 8-frame loop only played 5. Swapping to count-first
    fixes all counts. We also zero-fill the frames past `count` so a shorter
    animation can never leave a longer one's frames behind to be replayed."""
    frames = (list(frames) or [[(0, 0, 0)] * len(LIGHTS)])[:NUM_FRAMES]
    count = len(frames)
    flat = []
    for cols in frames:
        # 5-triplet render frame: positions 0,1,3,4 = the 4 lights; position 2 has
        # no LED but is kept = light 0's color so the frame stays complete.
        frame = [cols[0]] * FRAME_TRIPLETS
        for i, pos in enumerate(LIGHT_FRAME_POS):
            frame[pos] = cols[i]
        for r, g, b in frame:
            flat += [r & 0xFF, g & 0xFF, b & 0xFF]
    # Clear the unused frame slots so a previous, longer animation's frames can't
    # linger in the record and get replayed (the firmware reads `count` frames,
    # but zeroing keeps the slot honest for read-back and any off-by-one safety).
    flat += [0] * ((NUM_FRAMES - count) * FRAME_TRIPLETS * 3)
    bri = max(0, min(0x64, round(brightness / 100 * 0x64)))
    _write_slot([count, KEYFRAME_TYPE, speed_ui(speed), bri] + flat,
                _resolve_slot(slot))


# --- named effect patterns (captured from the official app) -----------------
# Each value is a full 124-byte slot record: header [COUNT, 0x05, speed,
# brightness] then the effect's palette. Reconstructed byte-for-byte from
# rgb_profiles_test.pcapng (cycle: Off -> Flow -> Rainbow -> Pulse -> Standoff
# -> Alarm). They all use the same 0x05 palette engine as set_keyframes and
# differ only by frame COUNT + palette: Flow=5, Rainbow=8, Pulse=2, Alarm=6,
# Standoff=1 frames (byte 0). Byte 3 is the brightness level (0..0x64);
# set_pattern overrides it from the GUI slider.
PATTERN_BRIGHT_IDX = 3
PATTERNS = {
    'Flow': [
        0x05, 0x05, 0x03, 0x50, 0x00, 0xff, 0x00, 0xff, 0xff, 0x00, 0x00, 0x00,
        0xff, 0xff, 0x00, 0x00, 0xff, 0x00, 0x00, 0x00, 0x00, 0xff, 0x00, 0xff,
        0x80, 0xff, 0x00, 0x00, 0xff, 0x80, 0x00, 0xff, 0xff, 0x00, 0x80, 0x00,
        0x80, 0x00, 0x00, 0xff, 0xff, 0x80, 0xff, 0xff, 0xff, 0x00, 0x00, 0xff,
        0x00, 0xff, 0x00, 0x00, 0xff, 0x00, 0x00, 0x80, 0x80, 0x00, 0x14, 0xff,
        0x01, 0x00, 0x00, 0xff, 0xff, 0x00, 0x00, 0x80, 0x80, 0x00, 0x00, 0x80,
        0x00, 0x00, 0x0f, 0xff, 0xff, 0x00, 0x80, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00,
    ],
    'Rainbow': [
        0x08, 0x05, 0x0a, 0x50, 0xff, 0x00, 0x00, 0xff, 0x00, 0x00, 0xff, 0x00,
        0x00, 0xff, 0x00, 0x00, 0xff, 0x00, 0x00, 0xff, 0xa5, 0x00, 0xff, 0xa5,
        0x00, 0xff, 0xa5, 0x00, 0xff, 0xa5, 0x00, 0xff, 0xa5, 0x00, 0xff, 0xff,
        0x00, 0xff, 0xff, 0x00, 0xff, 0xff, 0x00, 0xff, 0xff, 0x00, 0xff, 0xff,
        0x00, 0x00, 0xff, 0x00, 0x00, 0xff, 0x00, 0x00, 0xff, 0x00, 0x00, 0xff,
        0x00, 0x00, 0xff, 0x00, 0x00, 0xff, 0xff, 0x00, 0xff, 0xff, 0x00, 0xff,
        0xff, 0x00, 0xff, 0xff, 0x00, 0xff, 0xff, 0x00, 0x00, 0xff, 0x00, 0x00,
        0xff, 0x00, 0x00, 0xff, 0x00, 0x00, 0xff, 0x00, 0x00, 0xff, 0xff, 0x00,
        0xff, 0xff, 0x00, 0xff, 0xff, 0x00, 0xff, 0xff, 0x00, 0xff, 0xff, 0x00,
        0xff, 0xff, 0x00, 0x00, 0xff, 0x00, 0x00, 0xff, 0x00, 0x00, 0xff, 0x00,
        0x00, 0xff, 0x00, 0x00,
    ],
    'Pulse': [
        0x02, 0x05, 0x0f, 0x50, 0x80, 0x00, 0xff, 0x80, 0x00, 0xff, 0xff, 0x00,
        0x00, 0xff, 0x00, 0xc8, 0xff, 0x00, 0x00, 0x00, 0x80, 0xff, 0x00, 0x80,
        0xff, 0x00, 0x00, 0x00, 0x00, 0x80, 0xff, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00,
    ],
    'Standoff': [
        0x01, 0x05, 0x0a, 0x50, 0x00, 0x40, 0xff, 0xff, 0x05, 0x00, 0x00, 0xb3,
        0xff, 0xff, 0xff, 0xff, 0xff, 0x05, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00,
    ],
    'Alarm': [
        0x06, 0x05, 0x02, 0x50, 0xff, 0x00, 0x00, 0xff, 0x00, 0x00, 0xff, 0x00,
        0x00, 0xff, 0x00, 0x00, 0xff, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xff, 0x00,
        0x00, 0xff, 0x00, 0x00, 0xff, 0x00, 0x00, 0xff, 0x00, 0x00, 0xff, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00,
    ],
}
PATTERN_NAMES = list(PATTERNS)


def set_pattern(name, brightness=100, slot=None):
    """Write a named effect pattern to the active slot and select it. brightness
    0..100 overrides the record's stored level (byte 3)."""
    rec = PATTERNS.get(name)
    if rec is None:
        return
    rec = list(rec)
    rec[PATTERN_BRIGHT_IDX] = max(0, min(0x64, round(brightness / 100 * 0x64)))
    _write_slot(rec, _resolve_slot(slot))


def select_slot(n):
    """Make lighting slot n the active one (so Apply edits it / it's displayed)."""
    write_reg(LED_BANK, 0x0000, [n])


# Lighting playback toggle. The official app's keyframe play/pause button sends
# vendor command 0x0d (NOT a register write): byte 0 = 1 play / 0 pause, byte 1 =
# the 1-BASED KEYFRAME INDEX to freeze on / resume from, rest zero. Captures 19
# (frame 1 -> 0x01) and 20 (frame 3 -> 0x03) prove byte 1 tracks the selected
# keyframe: pausing with the current frame there holds that frame instead of
# snapping back to frame 1.
PLAYBACK_CMD = 0x0D


def set_playback(playing, frame=1):
    """Resume (playing=True) or pause (False) the lighting animation. `frame` is
    the 1-based keyframe the device freezes on when paused (and resumes from):
    pass the editor's current keyframe so Pause holds the frame you're looking at."""
    send_cmd(0x0F, PLAYBACK_CMD, 1 if playing else 0, frame)


def _rec_addr(slot, off):
    """Address of byte `off` within the active (or given) slot's record."""
    return 0x0001 + _resolve_slot(slot) * LED_REC + off


def speed_ui(raw):
    """Convert between device raw speed (1 = fastest) and UI speed (higher =
    faster). The map is its own inverse, so it works in both directions."""
    return SPEED_MIN + SPEED_MAX - max(SPEED_MIN, min(SPEED_MAX, int(raw)))


def set_speed(value, slot=None):
    """Live-write animation speed to the active slot's record (+2). `value` is the
    UI speed (higher = faster), stored inverted since the device uses 1 = fastest.
    Only affects animated effects (Flow/Rainbow/...); ignored by static colors."""
    write_reg(LED_BANK, _rec_addr(slot, REC_SPEED_OFF), [speed_ui(value)])


def set_brightness(value, slot=None):
    """Live-write brightness (0..100) to the active slot's record (+3)."""
    write_reg(LED_BANK, _rec_addr(slot, REC_BRIGHT_OFF), [max(0, min(0x64, int(value)))])


def set_audio_reactive(on):
    write_reg(LED_BANK, AUDIO_REACTIVE, [1 if on else 0])


def set_pickup_wake(on):
    write_reg(LED_BANK, PICKUP_WAKE, [1 if on else 0])


def set_sleep_timeout(minutes):
    """`minutes` is the raw byte (0 = never); use values from SLEEP_OPTIONS."""
    write_reg(LED_BANK, SLEEP_TIMEOUT, [max(0, min(0xff, int(minutes)))])


def sleep_raw(label):
    """Raw timeout byte for a SLEEP_OPTIONS label (default 10 min)."""
    return dict(SLEEP_OPTIONS).get(label, 0x0a)


def sleep_label(raw):
    """SLEEP_OPTIONS label for a raw timeout byte (default '10 min')."""
    for lbl, r in SLEEP_OPTIONS:
        if r == raw:
            return lbl
    return '10 min'


def read_fields(slot):
    """(bank, addr, len) reads that populate the live lighting controls for
    `slot`: that slot record's speed (+2) and brightness (+3), plus the three
    bank-global power settings. Pair the replies back up via FIELD_SPEED etc."""
    rec = 0x0001 + slot * LED_REC
    return [
        (LED_BANK, rec + REC_SPEED_OFF, 1),
        (LED_BANK, rec + REC_BRIGHT_OFF, 1),
        (LED_BANK, AUDIO_REACTIVE, 1),
        (LED_BANK, PICKUP_WAKE, 1),
        (LED_BANK, SLEEP_TIMEOUT, 1),
    ]


# --- full record read-back (for per-slot keyframe editing / backups) ---------
# A register read reply carries the bytes inline in a 64-byte report, so a single
# read tops out around ~58 bytes. The 124-byte slot record is read in chunks and
# stitched back together by the caller.
READ_CHUNK = 56


def record_addr(slot):
    """Address of slot `slot`'s 124-byte record (its first byte = effect type)."""
    return 0x0001 + slot * LED_REC


def record_read_fields(slot):
    """(bank, addr, len) chunk reads covering slot `slot`'s whole 124-byte record."""
    base = record_addr(slot)
    fields = []
    off = 0
    while off < LED_REC:
        ln = min(READ_CHUNK, LED_REC - off)
        fields.append((LED_BANK, base + off, ln))
        off += ln
    return fields


def stitch_record(slot, vals):
    """Reassemble a 124-byte record from the chunk replies in `vals`
    ({addr: [bytes]}, as returned for record_read_fields). Returns None if any
    chunk is missing."""
    base = record_addr(slot)
    out = []
    off = 0
    while off < LED_REC:
        chunk = vals.get(base + off)
        if chunk is None:
            return None
        out += list(chunk)
        off += min(READ_CHUNK, LED_REC - off)
    return out[:LED_REC]


def decode_record(record):
    """Decode a 124-byte record into {type, count, speed, brightness, frames},
    the inverse of how set_keyframes packs it. `frames` is NUM_FRAMES frames, each
    a list of (r,g,b) per light in LIGHTS order (read from LIGHT_FRAME_POS).

    Header is [COUNT, 0x05, speed, brightness]: byte 0 is the keyframe loop length
    and byte 1 is the 0x05 palette-engine marker (constant for every animated
    effect). `count` is read straight from byte 0 for a palette-engine record;
    for any other record byte 1 isn't 0x05, so fall back to a repeat-period guess
    from the frame data. 'type' returns byte 1 (the engine marker)."""
    etype = record[1]
    speed = speed_ui(record[REC_SPEED_OFF])
    brightness = round(record[REC_BRIGHT_OFF] / 0x64 * 100)
    palette = record[4:4 + LED_TRIPLETS * 3]
    triplets = [tuple(palette[i:i + 3]) for i in range(0, len(palette), 3)]
    frames = []
    for f in range(NUM_FRAMES):
        grp = triplets[f * FRAME_TRIPLETS:(f + 1) * FRAME_TRIPLETS]
        if len(grp) < FRAME_TRIPLETS:
            grp = grp + [(0, 0, 0)] * (FRAME_TRIPLETS - len(grp))
        frames.append([list(grp[pos]) for pos in LIGHT_FRAME_POS])
    if etype == KEYFRAME_TYPE and 1 <= record[0] <= NUM_FRAMES:
        count = record[0]
    else:
        count = frame_period(frames)
    return {'type': etype, 'count': count, 'speed': speed,
            'brightness': brightness, 'frames': frames}


def frame_period(frames):
    """Fallback loop-length guess when the count byte is unavailable/invalid:
    the smallest p in {1,2,4,8} that tiles to reproduce all 8 frames, else 8."""
    for p in (1, 2, 4, 8):
        if all(frames[i] == frames[i % p] for i in range(NUM_FRAMES)):
            return p
    return NUM_FRAMES


def restore_factory():
    """Rewrite lighting records 0-3 from the captured baseline."""
    write_reg(LED_BANK, FACTORY_START, FACTORY_DATA)
