# archive

One-off scripts and reference data from reverse-engineering the Cyclone 2.
Superseded by the main app and tools in the repo root; kept for reference.

These import `gs_common` / `gamesir_enhanced` from the repo root, so run them
from the parent directory (e.g. `sudo python3 archive/gamesir_led_map.py`) or
copy back to root if you need them.

**LED discovery (the path to per-light RGB):**
- `gamesir_led.pcapng` — USBPcap capture of the official app changing the LED;
  the source for the whole lighting protocol. Decode with `gamesir_parse_capture.py`.
- `gamesir_led_test.py` — first live solid-color test
- `gamesir_led_zones.py` — initial per-light discovery (distinct color per index)
- `gamesir_led_map.py` — definitive frame-position → light mapping
- `gamesir_led_slot_mon.py` — proved `0x20/0x0000` tracks the gesture live
- `gamesir_led_dbg.py` — solid-write readback (found the Profile-LED tail bug)
- `gamesir_led_probe.py` — early (failed) blind command-ID probing

**Input / buttons / battery discovery:**
- `gamesir_capture_buttons.py`, `gamesir_map_buttons.py`, `gamesir_probe_auto.py`
- `gamesir_find_charge.py` — found the charging flag (byte 35)
- `gamesir_dump12.py`, `gamesir_read_standard.py`, `gamesir_read_extended.py`

**Vendor channel / commands:**
- `gamesir_vendor_probe.py`, `gamesir_scan.py`
- `gamesir_cmd_test.py`, `gamesir_cmd_test2.py` — confirmed the command channel
- `gamesir_rumble_test.py`

**Older / docs:**
- `Gamesir_Cyclone2.py` — original PS4-mode reader (pre-GUI)
- `gamesir_handoff.md` — early handoff doc (since corrected; see README + memory)
