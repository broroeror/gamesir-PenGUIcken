#!/usr/bin/env python3
"""Parse a USBPcap .pcapng capture and extract HID OUT reports (host->device).

No external deps. Understands pcapng block structure + the USBPcap pseudo-header
(LINKTYPE_USBPCAP = 249). It decodes the vendor command channel (report 0x0f,
host->device) and the controller's replies (report 0x10, device->host).

The official app fires lots of READ-REG traffic on hover/focus to refresh its UI,
so a setting-change capture is noisy. For those, the WRITE-REG lines are the
signal -- use --writes to hide the read churn, and read the WRITE-REG SUMMARY at
the end to see exactly which addresses changed and to what.

Usage: python3 gamesir_parse_capture.py [capture.pcapng] [--writes]
       --writes  show only WRITE-REG lines (drop reads/replies/profile noise)
"""
import struct
import sys
from collections import Counter

args = [a for a in sys.argv[1:] if not a.startswith("--")]
flags = {a for a in sys.argv[1:] if a.startswith("--")}
WRITES_ONLY = "--writes" in flags
PATH = args[0] if args else "gamesir_led.pcapng"

with open(PATH, "rb") as f:
    blob = f.read()


def parse_pcapng(data):
    """Yield (timestamp_us, packet_bytes) tuples."""
    off = 0
    le = "<"  # default little-endian; corrected from SHB byte-order magic
    while off + 8 <= len(data):
        btype = struct.unpack_from(le + "I", data, off)[0]
        # Section Header Block: detect byte order
        if btype == 0x0A0D0D0A:
            # byte-order magic at body offset +8
            bom = struct.unpack_from("<I", data, off + 8)[0]
            le = "<" if bom == 0x1A2B3C4D else ">"
        blen = struct.unpack_from(le + "I", data, off + 4)[0]
        if blen < 12 or off + blen > len(data):
            break
        body = data[off + 8: off + blen - 4]
        if btype == 0x00000006:  # Enhanced Packet Block
            ts_high, ts_low = struct.unpack_from(le + "II", body, 4)
            ts = (ts_high << 32) | ts_low
            cap_len = struct.unpack_from(le + "I", body, 12)[0]
            pkt = body[20:20 + cap_len]
            yield ts, pkt
        elif btype == 0x00000003:  # Simple Packet Block
            orig_len = struct.unpack_from(le + "I", body, 0)[0]
            pkt = body[4:4 + orig_len]
            yield 0, pkt
        elif btype == 0x00000002:  # (obsolete) Packet Block
            cap_len = struct.unpack_from(le + "I", body, 8)[0]
            pkt = body[16:16 + cap_len]
            yield 0, pkt
        off += blen


def parse_usbpcap(pkt):
    """Return (is_out, endpoint, transfer, payload) or None."""
    if len(pkt) < 27:
        return None
    header_len = struct.unpack_from("<H", pkt, 0)[0]
    if header_len > len(pkt):
        return None
    endpoint = pkt[21]
    transfer = pkt[22]
    data_len = struct.unpack_from("<I", pkt, 23)[0]
    payload = pkt[header_len:header_len + data_len]
    is_out = (endpoint & 0x80) == 0  # bit7 set = IN (device->host)
    return is_out, endpoint, transfer, payload


XFER = {0: "ISO", 1: "INT", 2: "CTRL", 3: "BULK"}
CMD = {0x03: "WRITE-REG", 0x04: "READ-REG", 0x07: "SET-PROFILE",
       0x0b: "GET-PROFILE", 0x20: "RUMBLE", 0xf2: "HEARTBEAT"}


def trim(b):
    """Drop trailing zero padding for display."""
    e = len(b)
    while e > 1 and b[e - 1] == 0:
        e -= 1
    return b[:e]


events = []  # (ts, is_out, payload)
all_dir = Counter()
n = 0
t0 = None
for ts, pkt in parse_pcapng(blob):
    parsed = parse_usbpcap(pkt)
    if not parsed:
        continue
    is_out, ep, xfer, payload = parsed
    if not payload:
        continue
    n += 1
    all_dir["OUT" if is_out else "IN"] += 1
    if t0 is None and ts:
        t0 = ts
    events.append((ts, is_out, payload))

print(f"file: {PATH}  ({len(blob)} bytes)")
print(f"USB packets with payload: {n}   directions: {dict(all_dir)}")
print()
mode = "WRITE-REG only" if WRITES_ONLY else "heartbeats collapsed; <- = device reply"
print(f"=== Time-ordered traffic ({mode}) ===")
print("    t(s)  dir cmd            decode")
last_hb = -99
writes = []   # (rel, bank, addr, tuple(data)) for the end-of-run summary
for ts, is_out, payload in events:
    rel = (ts - t0) / 1e6 if (t0 and ts) else 0.0

    # device -> host: read-register reply  10 05 bank addrHi addrLo len data...
    if not is_out:
        if WRITES_ONLY:
            continue
        if payload[0] == 0x10 and len(payload) >= 6 and payload[1] == 0x05:
            bank = payload[2]
            addr = (payload[3] << 8) | payload[4]
            ln = payload[5]
            data = payload[6:6 + ln]
            dh = " ".join(f"{x:02x}" for x in data)
            print(f"  {rel:7.2f}  <-  READ-REPLY     bank=0x{bank:02x} addr=0x{addr:04x} len={ln:<3} data=[{dh}]")
        elif payload[0] == 0x10 and len(payload) >= 3 and payload[1] == 0x0C:
            print(f"  {rel:7.2f}  <-  PROFILE-REPLY  profile={payload[2]}")
        continue

    # host -> device: vendor command channel
    if payload[0] != 0x0F:
        continue
    cmd = payload[1]
    name = CMD.get(cmd, f"0x{cmd:02x}")
    if cmd == 0x03:  # WRITE-REG: 0f 03 bank addrHi addrLo len data...
        bank = payload[2]
        addr = (payload[3] << 8) | payload[4]
        ln = payload[5]
        data = payload[6:6 + ln]
        writes.append((rel, bank, addr, tuple(data)))
        dh = " ".join(f"{x:02x}" for x in data)
        print(f"  {rel:7.2f}  ->  {name:<13}  bank=0x{bank:02x} addr=0x{addr:04x} len={ln:<3} data=[{dh}]")
        continue
    if WRITES_ONLY:
        continue
    if cmd == 0xf2:
        if rel - last_hb > 5:  # only show occasional heartbeat markers
            print(f"  {rel:7.2f}  ->  HEARTBEAT      (... repeating ...)")
        last_hb = rel
        continue
    if cmd == 0x04:  # READ-REG
        bank = payload[2]
        addr = (payload[3] << 8) | payload[4]
        ln = payload[5]
        print(f"  {rel:7.2f}  ->  {name:<13}  bank=0x{bank:02x} addr=0x{addr:04x} len={ln}")
    else:
        dh = " ".join(f"{x:02x}" for x in trim(payload))
        print(f"  {rel:7.2f}  ->  {name:<13}  {dh}")

# --- WRITE-REG summary: which addresses changed, and to what ---------------
# In a noisy setting-change capture this is the actual answer -- it collapses the
# writes per (bank, addr) so you see the value(s) that landed at each address.
print()
print(f"=== WRITE-REG summary ({len(writes)} writes to "
      f"{len({(b, a) for _, b, a, _ in writes})} distinct addresses) ===")
if not writes:
    print("  (no writes -- this looks like a read-only / connect-sync capture)")
else:
    seen = {}   # (bank, addr) -> [values in order, first rel time]
    order = []
    for rel, bank, addr, data in writes:
        key = (bank, addr)
        if key not in seen:
            seen[key] = {"vals": [], "t": rel}
            order.append(key)
        # collapse immediate repeats so a held slider shows its path, not spam
        if not seen[key]["vals"] or seen[key]["vals"][-1] != data:
            seen[key]["vals"].append(data)
    for bank, addr in order:
        info = seen[(bank, addr)]
        vals = info["vals"]
        shown = vals if len(vals) <= 6 else vals[:3] + ["..."] + vals[-2:]
        vh = "  ".join(v if isinstance(v, str)
                       else "[" + " ".join(f"{x:02x}" for x in v) + "]"
                       for v in shown)
        print(f"  t={info['t']:6.2f}  bank=0x{bank:02x} addr=0x{addr:04x}  "
              f"{len(vals)} distinct -> {vh}")
