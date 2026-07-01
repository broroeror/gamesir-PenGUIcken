#!/usr/bin/env python3
"""Parse a USBPcap capture of the GameSir G7 (vid 3537:10ba) config traffic.

The G7 speaks GameSir's register protocol, but wrapped in a sequenced envelope
on report 0x0f (interrupt ep 0x02), unlike the Cyclone's bare `0f 03 …`:

    0f 00 <seq> 3c | <cmd> <args…>          (64-byte report; 0x3c = inner len 60)
    └── envelope ──┘ └── inner command ──┘

Inner WRITE-REG (cmd 0x03) is identical to the Cyclone:
    03 <bank> <addrHi> <addrLo> <len> <data…>

Usage: python3 gamesir_g7_parse.py <capture.pcapng> [--all]
       --all  show every inner command (not just writes) + IN replies
"""
import struct
import sys
from collections import OrderedDict

args = [a for a in sys.argv[1:] if not a.startswith("--")]
ALL = "--all" in sys.argv[1:]
if not args:
    sys.exit("usage: gamesir_g7_parse.py <capture.pcapng> [--all]")
PATH = args[0]
blob = open(PATH, "rb").read()


def parse_pcapng(data):
    off, le = 0, "<"
    while off + 8 <= len(data):
        bt = struct.unpack_from(le + "I", data, off)[0]
        if bt == 0x0A0D0D0A:
            bom = struct.unpack_from("<I", data, off + 8)[0]
            le = "<" if bom == 0x1A2B3C4D else ">"
        bl = struct.unpack_from(le + "I", data, off + 4)[0]
        if bl < 12 or off + bl > len(data):
            break
        body = data[off + 8: off + bl - 4]
        if bt == 6:
            th, tl = struct.unpack_from(le + "II", body, 4)
            cl = struct.unpack_from(le + "I", body, 12)[0]
            yield ((th << 32) | tl), body[20:20 + cl]
        off += bl


def parse_usbpcap(pkt):
    if len(pkt) < 27:
        return None
    hl = struct.unpack_from("<H", pkt, 0)[0]
    if hl > len(pkt) or hl < 27:
        return None
    ep, xf = pkt[21], pkt[22]
    dl = struct.unpack_from("<I", pkt, 23)[0]
    return ep, (ep & 0x80) == 0, pkt[hl:hl + dl]


CMD = {0x03: "WRITE-REG", 0x04: "READ-REG"}
t0 = None
writes = []         # (rel, bank, addr, tuple(data))
print(f"file: {PATH}  ({len(blob)} bytes)")
print("    t(s)  dir  decode")
for ts, pkt in parse_pcapng(blob):
    p = parse_usbpcap(pkt)
    if not p:
        continue
    ep, out, pl = p
    if not pl:
        continue
    rel = (ts - t0) / 1e6 if t0 else 0.0
    # host->device vendor envelope: 0f 00 seq 3c <inner>
    if out and len(pl) >= 5 and pl[0] == 0x0F and pl[3] == 0x3C:
        if t0 is None:
            t0 = ts; rel = 0.0
        inner = pl[4:]
        cmd = inner[0]
        if cmd == 0x03 and len(inner) >= 5:                 # WRITE-REG
            bank = inner[1]; addr = (inner[2] << 8) | inner[3]
            ln = inner[4]; data = inner[5:5 + ln]
            writes.append((rel, bank, addr, tuple(data)))
            dh = " ".join(f"{x:02x}" for x in data)
            print(f"  {rel:7.2f}  ->   WRITE-REG  bank=0x{bank:02x} "
                  f"addr=0x{addr:04x} len={ln:<2} data=[{dh}]")
        elif ALL:
            ih = " ".join(f"{x:02x}" for x in inner[:12])
            print(f"  {rel:7.2f}  ->   inner 0x{cmd:02x}  [{ih}]")
    elif ALL and not out and pl and pl[0] in (0x0F, 0x09):
        ih = " ".join(f"{x:02x}" for x in pl[:16])
        print(f"  {rel:7.2f}  <-   IN [{ih}]")

# --- per-(bank,addr) summary: the values that landed at each register ---------
print(f"\n=== WRITE-REG summary ({len(writes)} writes, "
      f"{len({(b, a) for _, b, a, _ in writes})} addresses) ===")
seen = OrderedDict()
for rel, bank, addr, data in writes:
    k = (bank, addr)
    seen.setdefault(k, {"t": rel, "vals": []})
    v = seen[k]["vals"]
    if not v or v[-1] != data:
        v.append(data)
for (bank, addr), info in seen.items():
    vals = info["vals"]
    shown = vals if len(vals) <= 8 else vals[:4] + ["…"] + vals[-3:]
    vh = "  ".join(v if isinstance(v, str) else
                   "[" + " ".join(f"{x:02x}" for x in v) + "]" for v in shown)
    print(f"  t={info['t']:7.2f}  bank=0x{bank:02x} addr=0x{addr:04x}  "
          f"{len(vals):>2} vals -> {vh}")
