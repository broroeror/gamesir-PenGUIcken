#!/usr/bin/env python3
"""Parse a USBPcap .pcapng capture of a GameSir *firmware upgrade* and decode it.

Companion to gamesir_parse_capture.py (which handles the register/config channel).
This one is tuned for a flash capture, where three things happen that the register
parser ignores:

  1. The pad re-enumerates -- it drops off USB and a JieLi loader / U-disk device
     comes up with a different VID/PID. We track every device address and dump any
     device/string descriptors so the loader (`br23uboot`/`br27uboot`) is visible.
  2. Firmware flows over the same 0x0f vendor channel but in the firmware family:
     a 64-byte report framed `0f 00 00 3c f0 00 00 00 <payload>` (sub-family 0xf0,
     per Connect's upgradWoker.js). The JieLi sub-command is payload[8]. There are
     thousands of block-writes, so identical consecutive sub-commands are COLLAPSED
     into one `WRITE x<N> (<bytes> B)` line -- the goal is the protocol skeleton
     (handshake -> erase -> write -> crc -> finish), not a per-packet dump.
  3. If the U-disk path is used instead, firmware rides USB mass-storage BULK
     transfers; we decode the SCSI CBW/CSW (signature USBC/USBS) and the CDBs.

No external deps. Capture on the ROOT HUB (all devices) so the re-enumeration is
included -- a capture filtered to the app-mode device loses everything after the
loader switch.

Usage: python3 gamesir_fw_parse.py <capture.pcapng> [--raw] [--all-in]
       --raw     don't collapse repeated firmware sub-commands (full dump)
       --all-in  show every IN payload (default: only firmware-looking replies)
"""
import struct
import sys
from collections import Counter, OrderedDict

args = [a for a in sys.argv[1:] if not a.startswith("--")]
flags = {a for a in sys.argv[1:] if a.startswith("--")}
RAW = "--raw" in flags
ALL_IN = "--all-in" in flags
if not args:
    sys.exit("usage: gamesir_fw_parse.py <capture.pcapng> [--raw] [--all-in]")
PATH = args[0]

with open(PATH, "rb") as f:
    blob = f.read()


# --- pcapng container (same block walk as gamesir_parse_capture.py) -----------
def parse_pcapng(data):
    """Yield (timestamp_us, packet_bytes)."""
    off = 0
    le = "<"
    while off + 8 <= len(data):
        btype = struct.unpack_from(le + "I", data, off)[0]
        if btype == 0x0A0D0D0A:  # Section Header Block -> byte order
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
            yield ts, body[20:20 + cap_len]
        elif btype == 0x00000003:  # Simple Packet Block
            orig_len = struct.unpack_from(le + "I", body, 0)[0]
            yield 0, body[4:4 + orig_len]
        elif btype == 0x00000002:  # (obsolete) Packet Block
            cap_len = struct.unpack_from(le + "I", body, 8)[0]
            yield 0, body[16:16 + cap_len]
        off += blen


# --- USBPcap pseudo-header ----------------------------------------------------
# headerLen[0] irpId[2] status[10] function[14] info[16] bus[17] device[19]
# endpoint[21] transfer[22] dataLength[23]; control adds a 1-byte stage at end.
XFER = {0: "ISO", 1: "INT", 2: "CTRL", 3: "BULK"}
CTRL_STAGE = {0: "SETUP", 1: "DATA", 2: "STATUS", 3: "COMPLETE"}


def parse_usbpcap(pkt):
    if len(pkt) < 27:
        return None
    header_len = struct.unpack_from("<H", pkt, 0)[0]
    if header_len > len(pkt) or header_len < 27:
        return None
    device = struct.unpack_from("<H", pkt, 19)[0]
    endpoint = pkt[21]
    transfer = pkt[22]
    data_len = struct.unpack_from("<I", pkt, 23)[0]
    stage = pkt[27] if (transfer == 2 and header_len >= 28) else None
    payload = pkt[header_len:header_len + data_len]
    is_out = (endpoint & 0x80) == 0  # bit7 set = IN (device->host)
    return {"dev": device, "ep": endpoint, "xfer": transfer,
            "stage": stage, "out": is_out, "data": payload}


def hexs(b, limit=None):
    if limit and len(b) > limit:
        return " ".join(f"{x:02x}" for x in b[:limit]) + f" ... (+{len(b) - limit})"
    return " ".join(f"{x:02x}" for x in b)


def trim(b):
    e = len(b)
    while e > 1 and b[e - 1] == 0:
        e -= 1
    return b[:e]


# --- descriptor sniffing (device + string, wherever they appear) --------------
devices = OrderedDict()   # addr -> {"first":t, "last":t, "vid":, "pid":, "strs":set, "n":count}


def note_device(addr, ts):
    d = devices.get(addr)
    if d is None:
        d = devices[addr] = {"first": ts, "last": ts, "vid": None, "pid": None,
                             "strs": set(), "n": 0}
    d["last"] = ts
    d["n"] += 1
    return d


def sniff_descriptor(d, payload):
    if len(payload) >= 18 and payload[1] == 0x01 and payload[0] == 0x12:
        d["vid"] = struct.unpack_from("<H", payload, 8)[0]
        d["pid"] = struct.unpack_from("<H", payload, 10)[0]
    elif len(payload) >= 4 and payload[1] == 0x03 and payload[0] >= 4:
        try:
            s = payload[2:payload[0]].decode("utf-16-le", "replace").strip("\x00")
            if s and any(c.isprintable() for c in s):
                d["strs"].add(s)
        except Exception:
            pass


# --- main pass ----------------------------------------------------------------
events = []   # (ts, parsed)
t0 = None
dir_count = Counter()
for ts, pkt in parse_pcapng(blob):
    p = parse_usbpcap(pkt)
    if not p:
        continue
    if t0 is None and ts:
        t0 = ts
    d = note_device(p["dev"], ts)
    if p["data"]:
        dir_count["OUT" if p["out"] else "IN"] += 1
        # control DATA stage may carry a descriptor
        if p["xfer"] == 2 and p["stage"] == 1:
            sniff_descriptor(d, p["data"])
    events.append((ts, p))


def rel(ts):
    return (ts - t0) / 1e6 if (t0 and ts) else 0.0


print(f"file: {PATH}  ({len(blob)} bytes)")
print(f"USB packets with payload: {sum(dir_count.values())}   {dict(dir_count)}")

# --- 1. device timeline -------------------------------------------------------
print("\n=== devices seen (address = re-enumeration tell) ===")
for addr, d in devices.items():
    vp = f"{d['vid']:04x}:{d['pid']:04x}" if d["vid"] is not None else "????:????"
    strs = ("  " + " | ".join(sorted(d["strs"]))) if d["strs"] else ""
    print(f"  dev {addr:<3} {vp}  t={rel(d['first']):7.2f}->{rel(d['last']):7.2f}  "
          f"pkts={d['n']}{strs}")

# --- 2. firmware 0x0f/0xf0 channel + 3. mass-storage SCSI ---------------------
SCSI_OP = {0x00: "TEST-UNIT-READY", 0x12: "INQUIRY", 0x1a: "MODE-SENSE6",
           0x1b: "START-STOP", 0x23: "READ-FMT-CAP", 0x25: "READ-CAPACITY",
           0x28: "READ10", 0x2a: "WRITE10", 0x5a: "MODE-SENSE10"}

print("\n=== firmware traffic (0f..f0 channel collapsed; SCSI decoded) ===")
print("    t(s)  dir  what")

fw_subops = Counter()
scsi_ops = Counter()
fw_bytes_out = 0
# collapsing state for repeated firmware sub-commands
run = {"sub": None, "n": 0, "bytes": 0, "t": 0.0, "sample": b""}


def flush_run():
    global run
    if run["sub"] is None:
        return
    if run["n"] == 1 and not RAW:
        print(f"  {run['t']:7.2f}  ->   FW sub=0x{run['sub']:02x}  "
              f"[{hexs(run['sample'], 24)}]")
    else:
        print(f"  {run['t']:7.2f}  ->   FW sub=0x{run['sub']:02x}  "
              f"x{run['n']}  ({run['bytes']} B)   first=[{hexs(run['sample'], 16)}]")
    run = {"sub": None, "n": 0, "bytes": 0, "t": 0.0, "sample": b""}


for ts, p in events:
    data = p["data"]
    if not data:
        continue
    t = rel(ts)

    # --- mass-storage SCSI (U-disk path) ---
    if p["xfer"] == 3 and len(data) >= 15 and data[:4] == b"USBC":
        flush_run()
        cdb_len = data[14]
        op = data[15] if len(data) > 15 else -1
        xlen = struct.unpack_from("<I", data, 8)[0]
        dirc = "IN" if (data[12] & 0x80) else "OUT"
        scsi_ops[op] += 1
        name = SCSI_OP.get(op, f"0x{op:02x}")
        print(f"  {t:7.2f}  ->   SCSI {name:<14} {dirc} len={xlen}  "
              f"cdb=[{hexs(data[15:15 + cdb_len])}]")
        continue
    if p["xfer"] == 3 and data[:4] == b"USBS":
        flush_run()
        res = data[12] if len(data) >= 13 else -1
        print(f"  {t:7.2f}  <-   SCSI status {'OK' if res == 0 else f'FAIL({res})'}")
        continue

    # --- firmware vendor channel: 0f 00 00 3c f0 ... ---
    is_fw = (p["out"] and len(data) >= 8 and data[0] == 0x0F
             and data[3] == 0x3C and data[4] == 0xF0)
    if is_fw:
        body = data[8:]
        sub = body[0] if body else 0x00
        fw_subops[sub] += 1
        fw_bytes_out += len(trim(body))
        if RAW:
            print(f"  {t:7.2f}  ->   FW sub=0x{sub:02x}  [{hexs(trim(body), 32)}]")
            continue
        if sub == run["sub"]:
            run["n"] += 1
            run["bytes"] += len(trim(body))
        else:
            flush_run()
            run = {"sub": sub, "n": 1, "bytes": len(trim(body)), "t": t,
                   "sample": bytes(trim(body))}
        continue

    # --- replies (device -> host) ---
    if not p["out"]:
        if ALL_IN:
            flush_run()
            print(f"  {t:7.2f}  <-   IN ep{p['ep']:02x} [{hexs(trim(data), 24)}]")
        elif data and data[0] in (0x0F, 0x10):
            flush_run()
            print(f"  {t:7.2f}  <-   REPLY [{hexs(trim(data), 24)}]")
        continue

flush_run()

# --- 4. summaries -------------------------------------------------------------
print("\n=== firmware sub-command histogram (payload[8]) ===")
if fw_subops:
    for sub, c in fw_subops.most_common():
        print(f"  sub=0x{sub:02x}  x{c}")
    print(f"  total firmware bytes pushed (host->device): {fw_bytes_out}")
else:
    print("  (no 0f..f0 firmware traffic -- HID path not used, or wrong capture)")

if scsi_ops:
    print("\n=== SCSI opcode histogram (U-disk path) ===")
    for op, c in scsi_ops.most_common():
        print(f"  {SCSI_OP.get(op, f'0x{op:02x}'):<16} x{c}")
