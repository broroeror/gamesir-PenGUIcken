"""
GameSir Cyclone 2 - local keyframe cache
========================================
The controller DOES store a custom animation's keyframe count (record byte 0; see
gamesir_led.decode_record), so the count and frames can now be read back exactly.
This side-car file is therefore belt-and-suspenders: it remembers each lighting
slot's authored keyframes (colors + count) so the editor can restore them across
profile switches and restarts even when the on-device readback is ambiguous. It is
only trusted when it still matches what's actually on the device (so a profile
changed on the controller itself, e.g. via the M + right-stick gesture, isn't
masked by a stale cache).

Shape:  { "0": {"count": 3, "frames": [[[r,g,b],[r,g,b],[r,g,b],[r,g,b]], ...]},
          "1": {...}, ... }   # keys are slot numbers as strings
"""

import json
import os

CACHE_PATH = os.path.expanduser('~/.config/gamesir/keyframes.json')


def _load_all():
    try:
        with open(CACHE_PATH) as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save(slot, frames, count):
    """Remember `frames[:count]` (each a list of [r,g,b] per light) for `slot`.
    Best-effort: a write failure is swallowed so it never breaks an Apply."""
    data = _load_all()
    data[str(slot)] = {
        'count': int(count),
        'frames': [[[int(c) for c in col] for col in frame] for frame in frames[:count]],
    }
    try:
        os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
        with open(CACHE_PATH, 'w') as fh:
            json.dump(data, fh, indent=2)
    except OSError:
        pass


def clear():
    """Forget every cached slot. Used after a JSON restore overwrites the device,
    so the editor trusts the freshly-written records instead of stale authored
    keyframes (whose leading frames could still 'match' and mask the new count)."""
    try:
        os.remove(CACHE_PATH)
    except OSError:
        pass


def get(slot):
    """Return (count, frames) cached for `slot`, or None if nothing is cached.
    `frames` is a list of `count` frames, each a list of [r,g,b] per light."""
    entry = _load_all().get(str(slot))
    if not entry or 'frames' not in entry:
        return None
    frames = [[list(col) for col in frame] for frame in entry['frames']]
    count = entry.get('count', len(frames))
    if not 1 <= count <= len(frames) or not frames:
        return None
    return count, frames


def matches(cached_frames, device_frames):
    """True when every cached keyframe equals the device's frame at that index -
    i.e. the cache still reflects what's actually stored in the slot. `device_frames`
    is the full NUM_FRAMES list from decode_record; only the first len(cached_frames)
    are compared (the rest are stale tail on the device)."""
    if len(cached_frames) > len(device_frames):
        return False
    for cached, dev in zip(cached_frames, device_frames):
        if [list(c) for c in cached] != [list(c) for c in dev]:
            return False
    return True
