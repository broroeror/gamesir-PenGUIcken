# GameSir Cyclone 2 — Linux control app

A Linux GUI for the GameSir Cyclone 2 controller, driven over the controller's
vendor (hidraw) interface, reverse-engineered from scratch. It covers:

- **Live input view** — sticks, triggers, all buttons (incl. the L4/R4/M/Home/
  Share extras), D-pad, battery + charging, firmware version, and a mode warning.
- **Profiles** — read the active profile and switch (1–4); rumble test.
- **Lighting** — per-light RGB, captured effect presets, brightness/speed,
  audio-reactive / pick-up-to-wake / sleep timeout, and a **custom keyframe
  animation editor** (add/remove keyframes, randomize, play/pause).
- **Config editor** — deadzones, anti-deadzones, stick trajectory, sensitivity
  curves (presets **and** a draggable custom-curve editor), trigger tuning
  (hair-trigger + response curve), vibration, poll rate, and button remap.
- **Backup / Restore** — snapshot all 4 profiles + lighting to a JSON file and
  write it back later.
- **Mouse-mode toggle** — turn KDE/KWin's gamepad-drives-the-cursor behaviour
  off (normal gamepad) or on (sticks-as-cursor "couch mode") from the app, plus a
  non-KDE EVIOCGRAB fallback (Wayland; see Status).

![status: input, battery, profiles, RGB + keyframes, full config editor, remap, and JSON backup/restore working]

**Version:** `0.1.0-alpha.2` — the full Qt/QML app (lighting + keyframe editor,
config editor, button remap, backup/restore, one-command install). Known-good
snapshot (git tag `v0.1.0-alpha.2`).
Remaining bugs, proposed changes, and open reverse-engineering questions live in
**[TODO.md](TODO.md)** — a living checklist. This is a hobby reverse-engineering
project; fork it and customize it however you like.

## The app

There are two frontends over the same reverse-engineered core:

- **`gamesir_qt.py`** — the **Qt/QML app** (PySide6): a polished, KDE-native UI
  with a live controller render, per-zone RGB + keyframes, stick/trigger curves,
  button remap, vibration, backup/restore, and a mouse-mode toggle. This is the
  one you install below.
- **`gamesir_gui.py`** — the original Dear PyGui app, kept as a lean fallback.

## Install (Qt app)

On **Arch / KDE**, one command after cloning:

```sh
git clone <repo-url> && cd "GameSir Linux"
./install.sh
```

`install.sh` installs into your home (`~/.local`), so the only step that needs
`sudo` is the one-time udev rule that lets you open the controller without root.
Afterwards **GameSir Cyclone 2** appears in your app launcher (or run
`gamesir-cyclone2`). Remove it with `./uninstall.sh`.

Prefer the Arch-native route? A [`packaging/PKGBUILD`](packaging/PKGBUILD) is
included to publish to the AUR (`yay -S gamesir-cyclone2-git`).

## Requirements

- Python 3
- [`hidapi`](https://pypi.org/project/hidapi/) (`import hid`)
- [`PySide6`](https://pypi.org/project/PySide6/) — for the Qt app
  (Arch: `python-pyside6`)
- [`dearpygui`](https://pypi.org/project/dearpygui/) — only for the legacy app
- `xrandr` (optional; legacy app's window placement)

```sh
# Arch
sudo pacman -S --needed python python-pyside6 python-hidapi
# or via pip
pip install hidapi PySide6
```

## Running

The controller must be in **Xbox / XInput mode (hold the green button ~2s)** —
the vendor protocol is inert in PS4/DS4 and Switch modes. The app warns you in
the header when the controller isn't in Xbox mode.

**Recommended — without `sudo`.** Install the included udev rule once so your
user can open the controller's `hidraw` nodes directly (and its `input` event
nodes, for the mouse-mode fix below) - scoped to GameSir's USB vendor id, nothing
else. Run this **from the repo directory** (where `70-gamesir.rules` lives):

```sh
sudo cp 70-gamesir.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger
```

Then run (no replug needed — the trigger re-applies the access ACL):

```sh
python3 gamesir_gui.py
```

The rule uses `TAG+="uaccess"`, which grants access to the user logged in at the
local desktop. **The `70-` prefix matters**: udev runs rules in filename order,
and `73-seat-late.rules` is what actually applies the `uaccess` ACL — a rule
numbered `73`+ sets the tag too late and the ACL is silently never granted. On a
headless/remote box with no local seat, `uaccess` doesn't apply; use a group
instead (`MODE="0660", GROUP="input"`) and add yourself to it.

To confirm it worked, the controller's node should show your ACL:
`getfacl /dev/hidraw0` → a `user:<you>:rw-` line.

**Fallback — with `sudo`.** If you'd rather not install the rule, the `hidraw`
nodes are root-owned by default, so:

```sh
sudo python3 gamesir_gui.py
```

Note that under `sudo`, `~` resolves to `/root`, so the default Backup path lands
in `/root/` — another reason to prefer the udev-rule route.

## How it works (protocol notes)

The controller exposes a **vendor HID interface** (USB VID `0x3537`) carrying a
64-byte command/report channel. Everything below requires **Xbox mode** and a
**sustained heartbeat** (`0x0F 0xF2` every ~0.5s).

- **Input**: enhanced report `0x12` streams sticks, triggers, IMU, battery
  (byte 36 %, byte 35 bit0 = charging), and the extra buttons (L4/R4/M/Home/
  Share in byte 60) that the standard PS4 report can't see.
- **Commands** (output report `0x0F`, padded to 64):
  - Heartbeat `0F F2`
  - Get/Set profile `0F 0B` → `10 0C <p>` / `0F 07 <p>`
  - Rumble `0F 20 66 55 <L> <R>`
  - Read register `0F 04 <bank> <addrHi> <addrLo> <len>` → `10 05 <bank> <hi> <lo> <len> <data…>`
  - Write register `0F 03 <bank> <addrHi> <addrLo> <len> <data…>`
- **Lighting** lives in register **bank `0x20`**:
  - `0x0000` = active slot selector (0–3; also a reliable live readback of the
    M+stick gesture)
  - slot record at `0x0001 + slot*0x7c` (124 bytes): `[type, 05, param, brightness]`
    then a palette of RGB triplets rendered as repeated **5-triplet frames**
  - Frame position → light: **0=Left grip, 1=Right grip, 2=(no LED), 3=Profile,
    4=Home**. A solid/per-light color = type `0x01`, tile one identical frame
    across the whole record (zeroing the tail drops the Profile LED).
  - Animated **effect presets** are distinct `type` bytes captured from the app
    (`rgb_profiles_test.pcapng`): `0x05` Flow, `0x08` Rainbow, `0x02` Pulse,
    `0x06` Alarm, `0x01`+palette Standoff. Stored verbatim in `gamesir_led.py`
    (`PATTERNS`); `set_pattern` writes one to the active slot, overriding the
    brightness byte from the slider.
  - **Custom keyframe animations** reuse the `0x05` palette engine: the record
    header is `[count, 0x05, speed, brightness]` — **byte 0 is the keyframe
    count** (1–8), so the editor recovers it on readback. Each keyframe is one
    5-triplet frame; `decode_record` is the inverse of `set_keyframes`.
    `gamesir_kf_cache.py` keeps a local copy of the exact colors/count so a slot
    we wrote round-trips perfectly even though the device only stores 8 tiled
    frames.
  - **Play / pause** the running animation is vendor command `0F 0D <state>
    <frame>` (captured from the app): byte 2 = `1` play / `0` pause, byte 3 = the
    **1-based keyframe to freeze on** — so Pause holds the frame you're viewing
    instead of snapping to frame 1.
- **Firmware version** comes straight from the USB device descriptor's
  `bcdDevice` (hidapi `release_number`), BCD-encoded `JJ.MN` — no USB command or
  network call. The official app's Info button reads the same field.
- **Mode switching** (Xbox ↔ Switch ↔ PlayStation) is a hardware button combo
  that triggers a full USB **re-enumeration**, not a sendable command. Only Xbox
  mode exposes the vendor channel; outside it the `0x12` stream goes all-zero,
  which the app detects as "not in Xbox mode."

Gotcha: the controller **drops a command sent immediately after another** —
space out periodic queries (the GUI alternates them).

Full hardware notes live in the assistant memory file
`gamesir-vendor-interface-findings.md`.

## File layout

**App (runtime)** — the GUI is split into focused modules:
- `gamesir_gui.py` — the view layer: panel construction, per-frame updates, callbacks
- `gs_state.py` — the shared live `state` dict (dependency-free)
- `gamesir_reader.py` — background connect/read loop that fills `state`
- `gamesir_control.py` — command channel: `send_cmd`, profile, rumble, register read/write
- `gamesir_led.py` — lighting domain (bank `0x20`): `set_lights`, slot select, keyframes, factory restore
- `gamesir_config.py` — per-profile config register map (deadzones / curves / vibration / poll rate …)
- `gamesir_backup.py` — full-setup export/restore: read every profile + lighting, (de)serialize JSON
- `gamesir_kf_cache.py` — local cache of exact keyframe colors/count per slot (authoritative across profile switches)
- `gamesir_mousegrab.py` — suppresses the emulated mouse/keyboard (EVIOCGRAB) for the mouse-mode fix
- `gamesir_window.py` — viewport placement (xrandr primary-monitor geometry; X11/XWayland)
- `gs_common.py` — vendor-interface discovery + helpers (incl. firmware/`bcdDevice` read)
- `gamesir_enhanced.py` — `0x12` enhanced-report parser
- `gamesir_led_factory.py` — captured lighting baseline for "Restore presets"

**Tools:**
- `gamesir_regdump.py` — dump/diff a register range (`sudo python3 gamesir_regdump.py <bank-decimal> <start-hex> <end-hex>`; bank 0x20 = `32`)
- `gamesir_regread.py` — read a single register
- `gamesir_regwrite_test.py` — safe write-register validator (read-modify-readback-restore on one byte)
- `gamesir_profile_axis.py` — read-only probe of how profiles map to banks
- `gamesir_parse_capture.py` — decode a USBPcap `.pcapng` into vendor commands (no deps). `--writes` filters to WRITE-REG only and prints a per-address summary — ideal for noisy setting-change captures
- `gamesir_input_diag.py` — mouse-mode isolator: grabs the controller's evdev nodes one at a time so you can see which one (the joystick node) the compositor is reading to drive the cursor (`sudo python3 gamesir_input_diag.py`)

**`USBPcap Controller  Tests/`** — the official-app captures the config map was
reverse-engineered from (connect-sync, persistence, remap, deadzones, curves,
poll rate, vibration). Parse any with `gamesir_parse_capture.py`.

**`archive/`** — one-off probes, button/LED discovery scripts, the original
PS4-mode reader, the pre-refactor monolithic GUI (`gamesir_gui_monolithic.py`),
the outdated handoff doc, and the LED USB capture (`gamesir_led.pcapng`). Kept
for reference; these expect the repo root on the import path
(`from gs_common import …`).

## Status & next steps

Working: live input, battery, firmware readout, Xbox-mode warning, profile
read/switch, rumble, full per-light RGB, **effect presets**, lighting power
settings (audio-reactive / pick-up-to-wake / sleep), a **custom keyframe
animation editor** (per-slot, add/remove 1–8 frames, randomize, play/pause), a
**config editor** (deadzones, anti-deadzones, stick trajectory + sensitivity
curve incl. a **draggable custom-curve editor**, trigger deadzones +
hair-trigger + response curve, vibration L/R, poll rate), and **button remap** —
all reading the active profile's current values and writing edits live.

**Backup / Restore:** Export snapshots all 4 profiles + lighting to a labelled
JSON file; Restore writes it back. Both are **verified end-to-end on hardware.**
Restore is **write-verify-retry**: every block is read back after writing and
re-sent if it didn't take (the controller silently drops back-to-back commands,
so a blind write loses blocks - e.g. the first lighting record), retrying up to a
few passes and reporting a clear pass/fail status. Picking a restore file reveals
an inline **"Write loaded backup to controller"** button (no modal popup - those
proved unreliable across window managers). Note: banks `0x02`-`0x04` (the stored,
non-active profiles) appear read-only on this controller, so only the **active
profile + lighting** are guaranteed to restore; the status line says so if the
stored profiles can't be confirmed.

**Mouse-mode fix (KDE/KWin Game Controller plugin):** after the 2.4GHz dongle
re-pairs/replugs, moving the sticks starts driving the desktop cursor (and the
buttons click). This is **not** the controller emulating a mouse — it's **KWin's
"Game Controller" plugin** (Plasma 6.7, a 2025 GSoC feature) mapping sticks →
pointer and triggers → clicks, reading the joystick evdev node **directly**.
(Diagnosed by grabbing the controller's evdev nodes one at a time — only the
*joystick* node stops the cursor; the emulated mouse/keyboard nodes read zero.
`fuser` confirms `kwin_wayland` holds the joystick node, and a
`LIBINPUT_IGNORE_DEVICE` rule was tested and does **not** help — KWin reads it
out-of-band, not through libinput.)

**Recommended fix — disable the plugin** (permanent, and games are unaffected
because they read evdev directly; the plugin even auto-disables when another app
uses the pad):

```sh
kwriteconfig6 --file kwinrc --group Plugins --key gamecontrollerEnabled false
qdbus6 org.kde.KWin /KWin reconfigure   # or just log out/in
```

`gamecontrollerEnabled true/false` is effectively the mouse-mode on/off switch
(there's also a **System Settings → Game Controller** toggle).

**In-app fallback (non-KDE / on-demand):** the **Stop mouse mode** toggle takes an
exclusive `EVIOCGRAB` on the joystick node so the compositor can't read it, and
re-applies the grab across replugs. It's desktop-agnostic, but while it's on,
evdev games (Steam/SDL) won't see the pad either (the legacy `/dev/input/jsN`
node and the hidraw app still work) — so prefer the plugin toggle on KDE. (Run
`gamesir_input_diag.py` to reproduce the one-node-at-a-time isolation yourself.)

**Config architecture (settled by USB capture):** byte 2 of the read/write command
is a **bank** selector. Edits target **bank `0x01`, a live working copy of the
*active* profile** — the official app writes every config/remap change there
regardless of profile number. Banks `0x02`–`0x05` are stores/aux the app only reads
(`0x02`–`0x04` are the default profile stores; `0x05` is a different aux bank), and
`0x20` is lighting. The register offsets (vibration `0x20`/`0x21`, poll rate `0x2e`,
trigger block `~0x1f1`, stick block `~0x227`, remap records below) live in
`gamesir_config.py` and the assistant memory file. **Writes auto-persist to flash —
no commit command needed.**

**Remap:** each input has a 7-byte record; only `[enabled, target_code]` matter
(clear = `[00 00]`). Source addresses and target codes are mapped in
`gamesir_config.py` (`REMAP_SLOTS` / `REMAP_TARGETS`).

The **right-stick block** is **captured** (`15_rs_testing.pcapng`): it's the
left-stick block mirrored at `+0x20` (trajectory `0x0247`, deadzone min/max
`0x0249`/`0x024a`, anti-dz min/max `0x024b`/`0x024c`, curve `0x024e`). That
capture also revealed the **left stick has a deadzone *max*** at `0x022a` we'd
been missing — the editor now shows deadzone min+max for both sticks.

The **RT trigger block** is exposed as LT mirrored at `+0x1c` (the RT remap
address confirms that stride) — **inferred, pending verification** against a
capture of an RT-setting change.

Open items: verify the inferred RT block; View/Menu/L4/R4 *target* codes (not
yet captured as targets); how a profile switch syncs bank `0x01` to a store (a
`SET-PROFILE` + re-read test); and PS4/Switch-mode input parsing.

## License & disclaimer

Released under the [MIT License](LICENSE) — use, modify, and redistribute
freely.

This is an independent, hobby reverse-engineering project. It is **not
affiliated with, endorsed by, or supported by GameSir**, and "GameSir" and
"Cyclone 2" are trademarks of their respective owners. The protocol was
reverse-engineered for interoperability; the repository contains only original
code (no vendor firmware, USB captures, or third-party assets). Provided **as
is, without warranty** — you use it, and poke at your controller's registers,
at your own risk.
