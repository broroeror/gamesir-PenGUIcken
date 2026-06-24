"""
GameSir Cyclone 2 - captured lighting baseline (bank 0x20, records 0-3)
======================================================================
Snapshot of the four lighting preset records as read from THIS unit before any
of the Linux-side experiments modified them (the first gamesir_regdump run).
Used by the GUI's "Restore presets" button to undo edits.

Layout: selector at 0x0000; record M at 0x0001 + M*0x7c (124 bytes each). This
covers records 0..3 = addresses 0x0001..0x01f0.

To regenerate on another unit: run `sudo python3 gamesir_regdump.py 32 0x0000
0x0200` and paste the rows below.
"""

# Raw dump rows (addr: 16 bytes), 0x0000..0x01f0.
_DUMP = """
0000: 00 01 05 14 50 ff 00 00 ff 00 00 00 00 00 ff 00
0010: 00 ff 00 00 00 00 00 00 00 00 00 00 00 00 00 00
0020: 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
0030: 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
0040: 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
0050: 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
0060: 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
0070: 00 00 00 00 00 00 00 00 00 00 00 00 00 01 05 14
0080: 50 2b ff 00 2b ff 00 ff 00 00 2b ff 00 2b ff 00
0090: 00 ff dd 00 ff dd 00 00 00 00 ff dd 00 ff dd 00
00a0: 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
00b0: 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
00c0: 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
00d0: 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
00e0: 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
00f0: 00 00 00 00 00 00 00 00 00 01 05 14 64 19 00 ff
0100: 19 00 ff 00 00 00 19 00 ff 19 00 ff 00 00 00 00
0110: 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
0120: 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
0130: 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
0140: 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
0150: 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
0160: 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
0170: 00 00 00 00 00 05 05 03 64 00 ff 00 ff ff 00 00
0180: 00 ff ff 00 00 ff 00 00 00 00 ff 00 ff 80 ff 00
0190: 00 ff 80 00 ff ff 00 80 00 80 00 00 ff ff 80 ff
01a0: ff ff 00 00 ff 00 ff 00 00 ff 00 00 80 80 00 14
01b0: ff 01 00 00 ff ff 00 00 80 80 00 00 80 00 00 0f
01c0: ff ff 00 80 00 00 00 00 00 00 00 00 00 00 00 00
01d0: 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
01e0: 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
01f0: 00
"""


def _parse(dump):
    by_addr = {}
    for line in dump.strip().splitlines():
        addr_s, _, rest = line.partition(':')
        base = int(addr_s, 16)
        for i, tok in enumerate(rest.split()):
            by_addr[base + i] = int(tok, 16)
    end = max(by_addr) + 1
    return [by_addr.get(a, 0) for a in range(end)]


_BYTES = _parse(_DUMP)

# Records 0..3 occupy 0x0001..0x01f0 (4 * 124 bytes).
FACTORY_START = 0x0001
FACTORY_DATA = _BYTES[FACTORY_START:FACTORY_START + 4 * 0x7c]
