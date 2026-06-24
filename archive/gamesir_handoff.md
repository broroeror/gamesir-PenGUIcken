# GameSir Cyclone 2 Linux App - Claude Code Handoff

## Project Overview
Building a Linux configuration/visualization app for the GameSir Cyclone 2 controller.
The controller runs in PS4 mode on Linux via the `hid_playstation` kernel driver.
All code lives at: `~/Documents/Programming/GameSir Linux/`

## System
- CachyOS Linux, KDE Plasma, Wayland
- Python 3.14
- Controller connected via 2.4GHz USB dongle

## HID Device Info
- Standard input: `/dev/hidraw0` — vendor 0x054C (Sony spoof), product 0x09CC
- Vendor interface: `/dev/hidraw6` — vendor 0x3577, product 0x0575 (GameSir native)
- Run all scripts with `sudo` (or add udev rule)

## Input Report Format (hidraw0, 64 bytes)
```
Byte 0:  Report ID (always 1)
Byte 1:  Left Stick X  (0-255, center=128)
Byte 2:  Left Stick Y  (0-255, center=128, UP = low values)
Byte 3:  Right Stick X (0-255, center=128)
Byte 4:  Right Stick Y (0-255, center=128, UP = low values)
Byte 5:  B1 — lower nibble = D-pad, upper nibble = face buttons
Byte 6:  B2 — shoulder/trigger/stick buttons
Byte 7:  Timestamp (increments by 4, ignore for input)
Byte 8:  Left Trigger  (0-255 analog)
Byte 9:  Right Trigger (0-255 analog)
Bytes 10+: Gyro, accelerometer, other sensor data
```

## B1 Button Map (byte 5)
```
D-pad (lower nibble, byte 5 & 0x0F):
  15 = neutral
   0 = up
   2 = right
   4 = down
   6 = left
   1/3/5/7 = diagonals

Face buttons (upper nibble):
  bit 7 (0x80) = Y
  bit 6 (0x40) = B   ← NOTE: B and X are swapped vs PS4 layout
  bit 5 (0x20) = A
  bit 4 (0x10) = X   ← NOTE: B and X are swapped vs PS4 layout
```

## B2 Button Map (byte 6)
```
bit 0 (0x01) = LB  (Left Bumper)
bit 1 (0x02) = RB  (Right Bumper)
bit 2 (0x04) = LT  (Left Trigger digital, mirrors analog byte 8)
bit 3 (0x08) = RT  (Right Trigger digital, mirrors analog byte 9)
bit 4 (0x10) = View  (Back/Select)
bit 5 (0x20) = Menu  (Start)
bit 6 (0x40) = LS   (Left Stick click)
bit 7 (0x80) = RS   (Right Stick click)
```

## NOT YET MAPPED
- L4, R4 back buttons — appear at byte 59 of vendor report (hidraw6) per reverse engineering
  gist, but hid_playstation driver blocks vendor interface access in PS4 mode
- Home button — byte unknown
- Share/Capture button — byte unknown  
- Profile button — triggers profile switching (4 profiles supported)

## Vendor Interface (hidraw6) — Partial
The GameSir vendor interface requires a heartbeat every second to activate enhanced mode:
- Heartbeat command: `[0x00, 0x0F, 0xF2]`
- Enhanced input reports come back as report ID 0x12
- L4/R4/M buttons are at byte index 59 of the 0x12 report (0-indexed, skipping report ID)
- Currently blocked by hid_playstation driver conflict in PS4 mode
- May work in Xbox mode (untested) — worth investigating

## Protocol Reference
Full reverse engineering gist: https://gist.github.com/NaokoAF/da4c166ed80e569276beee5a57bdeba9

Key commands (sent to hidraw6, report ID 0x0F):
- Heartbeat: `0xF2`
- Set Profile: `0x07 XX` (XX = 1,2,3,4)
- Get Profile: `0x0B` (controller replies with 0x0C XX)
- Rumble: `0x20 0x66 0x55 XX YY` (XX=left, YY=right motor)
- Write Register: `0x03 XX YY YY ZZ` (profile, address big-endian, length)
- Read Register: `0x04 XX YY YY ZZ`

## Current Files

### gamesir_cyclone2.py — Core input reader (working)
Clean, documented input parser. Reads from hidraw0, parses all confirmed buttons,
prints human-readable output only when something changes. Use `parse_report(data)`
to get a state dict.

### gamesir_gui.py — Live input visualizer (working, needs improvements)
Dear PyGui app showing:
- Left/Right stick plots (scatter series in -1.1 to 1.1 space)
- LT/RT progress bars
- Face button circles (Y/A/X/B)
- Bumper/system button rectangles (LB, RB, View, Menu, LS, RS)
- D-pad text display

## Pending GUI Tasks

### 1. Font fix (immediate — makes text much more readable)
Add after `dpg.create_context()`:
```python
with dpg.font_registry():
    default_font = dpg.add_font('/usr/share/fonts/TTF/DejaVuSans.ttf', 16)
dpg.bind_font(default_font)
```

### 2. Add missing button placeholders to UI
Currently not displayed: Home, Share/Capture, Profile button
Add as greyed-out placeholders with "?" or "—" label since inputs aren't mapped yet

### 3. Profile indicator
Display current profile (1-4) — can query via vendor interface `0x0B` command
or just show a static indicator for now

### 4. General UI polish
- Button labels are slightly misaligned in drawlist
- Consider adding a connection status indicator
- Window currently opens off-screen on ultra-wide — add positioning logic:
  `dpg.set_viewport_pos(x, y)` after `dpg.show_viewport()`

## Dependencies
```
python-hid (pacman: python-hid)
dearpygui 2.2 (pip: python3 -m pip install dearpygui --break-system-packages)
```

## Running
```bash
sudo python3 ~/Documents/Programming/GameSir\ Linux/gamesir_gui.py
```

## Future Features (not started)
- Button remapping (requires register write commands to vendor interface)
- Per-profile configuration
- Deadzone adjustment
- Trigger sensitivity curves  
- RGB LED control (supported by protocol, commands not yet mapped)
- L4/R4 support (requires detaching hid_playstation driver or Xbox mode investigation)
- udev rule so sudo isn't needed:
  Create `/etc/udev/rules.d/99-gamesir-cyclone2.rules`:
  `SUBSYSTEM=="hidraw", ATTRS{idVendor}=="3577", ATTRS{idProduct}=="0575", MODE="0666"`
  Then: `sudo udevadm control --reload-rules && sudo udevadm trigger`
