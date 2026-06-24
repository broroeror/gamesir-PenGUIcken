"""
Dump the lighting section of a backup JSON, so we can see which slot holds which
colour (isolates export-side bugs from restore-side ones).

    python3 gamesir_dump_backup.py [path/to/backup.json]

With no path it picks the newest gamesir_backup*.json under ~ and the repo dir.
"""

import glob
import json
import os
import sys


def newest_backup():
    pats = [os.path.expanduser('~/gamesir_backup*.json'),
            os.path.expanduser('~/**/gamesir_backup*.json'),
            'gamesir_backup*.json']
    hits = []
    for p in pats:
        hits += glob.glob(p, recursive=True)
    return max(hits, key=os.path.getmtime) if hits else None


def colour(rgb):
    r, g, b = (rgb + [0, 0, 0])[:3]
    if r > 120 and g < 80 and b < 80:
        return 'RED'
    if g > 120 and r < 80 and b < 80:
        return 'GREEN'
    if b > 120 and r < 80 and g < 80:
        return 'BLUE'
    return f'rgb({r},{g},{b})'


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else newest_backup()
    if not path or not os.path.exists(path):
        print('No backup file found - pass a path explicitly.')
        return
    print(f'# {path}')
    data = json.load(open(path))
    print(f'# schema {data.get("schema")}  exported {data.get("exported")}')
    light = data.get('lighting', {})

    sel = light.get('active_slot') or {'bytes': light.get('selector', ['?'])}
    print(f'active_slot = {sel.get("bytes")}')

    slots = light.get('slots') or light.get('records', {})
    for key in sorted(slots, key=lambda k: int(k)):
        ent = slots[key]
        byts = ent['bytes'] if isinstance(ent, dict) else ent
        addr = ent['addr'] if isinstance(ent, dict) else '(schema1)'
        header = byts[:4]
        first_rgb = byts[4:7]
        print(f'slot {key} @ {addr}: header={header}  first-colour={first_rgb} '
              f'({colour(first_rgb)})')


if __name__ == '__main__':
    main()
