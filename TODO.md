# GameSir Cyclone 2 (Linux) — TODO / Roadmap

A living checklist of known bugs, proposed changes, and open reverse-engineering
questions. Linked from the [README](README.md). This is a hobby reverse-engineering
project — **fork it and customize it however you like.**

How to use this file: check items off as they land (`- [x]`), and add new bugs or
ideas with a one-line note (a date helps). Keep entries short; deep findings go in
the README's protocol notes or the commit message.

---

## 🐞 Known bugs / rough edges

- [x] **Couch mode doesn't always enable live.** *Fixed:* the toggle now calls
      `org.kde.KWin.Plugins.LoadPlugin`/`UnloadPlugin` over D-Bus (instead of a
      bare `reconfigure`), so enabling takes effect immediately. The `kwinrc`
      flag is still written for persistence / System Settings consistency.
- [ ] **Restore only covers the active profile + lighting.** Banks `0x02`–`0x04`
      (the stored, non-active profiles) appear read-only when written directly, so
      Restore can't push them. Likely fix: switch to profile N so it loads into
      bank `0x01`, write there, repeat — depends on the profile-switch→bank-sync
      behaviour below.
- [ ] *(environment, not this app)* **KWin 6.7 logout SIGSEGV** in
      `RenderLoop::activeWindowControlsVrrRefreshRate()` during compositor
      teardown, on multi-output + hybrid NVIDIA/AMD. Workaround: System Settings →
      Display → Adaptive Sync → *Never*. Worth reporting upstream to KDE.
- [x] **UI scaling: elements cut off on some pages.** *Fixed:* the `compact`
      reparent threshold on **Sticks/Triggers** (`AxisConfigPage`) was mistuned
      (560) so the Trajectory/Hair card stayed in the overflowing left column even
      at the default window size — raised to 660 so it moves into the centre slack
      before clipping. **Lights** threshold raised (600→700) and the controller
      render is now capped (200 px) when the viewport is short. All three pages now
      fit at the default 1040×720; Sticks/Triggers fit down to the 840×620 minimum
      too. The densest page (Lights) may still need a small scroll at the absolute
      minimum size, which the existing `ScrollView` handles. *(Verified by rendering
      each page offscreen at 620 & 720.)* The Settings overlay (with Firmware) fits
      fine as-is.
- [x] **Top bar crowded / settings gear pushed off-screen.** *Fixed:* the top bar
      is now responsive — profile pills collapse to `P1`..`P4` below 1200 px (full
      `Profile N` labels when wider), the wrong-mode warning is a compact ⚠ chip
      with the guidance on hover (it can no longer grow the bar), and the
      `Sticks → cursor` label + firmware text hide below 1000 px. The settings gear
      stays reachable at 840 / 1040 / 1240 (verified by offscreen render). This also
      made room for the new controller picker.

## ✨ Enhancements / proposed changes

- [ ] **Bind the mouse-mode toggle to a controller button** via the controller's
      macro/keybind system (the original stretch goal). Needs a USB capture of the
      official app's macro/keybind screen to learn the command format.
- [x] **Easy install / packaging.** `install.sh` drops a `.desktop` launcher +
      icon and installs the udev rule (no CLI to launch); `packaging/PKGBUILD`
      builds locally with `makepkg -si` (no AUR account needed). *(Shipped in M6.)*
- [ ] *(blocked, external)* **Publish the package to the AUR.** Waiting on AUR
      account creation, which is **disabled upstream** for the maintainer right now.
      Not on the critical path — both install routes above work without it. Revisit
      when aur.archlinux.org account registration reopens.
- [ ] **Housekeeping: reduce the file count.** The repo has ~25 top-level
      `gamesir_*.py` files — many are one-off RE scripts (`gamesir_regdump`,
      `gamesir_regread`, `gamesir_regwrite_test`, `gamesir_input_diag`,
      `gamesir_dump_backup`, `gamesir_enhanced`, the old `gamesir_gui.py`, etc.)
      that the Qt app no longer imports. Audit what the app actually depends on,
      move dev/RE-only tools into a `tools/` (or further into `archive/`), and
      collapse overlapping helpers (`gs_common`/`gs_state` vs the `gamesir_*`
      modules). Goal: a lean runtime surface + a clearly-separated RE toolbox.
- [ ] **Restore: per-block verify detail.** The write-verify-retry already reports
      pass/fail; could add a "verify only" action or a list of any unconfirmed
      blocks.
- [ ] **Cross-platform portability (macOS / Windows).** The core — PySide6 + hidapi
      + the pure-Python protocol — already runs anywhere. The one Linux-coupled
      chokepoint is device discovery in `gs_common.find_vendor_nodes()`, which globs
      `/sys/class/hidraw` and opens `/dev/hidraw*`. Swap it for `hid.enumerate()`
      (select by vendor id `0x3537` + interface) and macOS/Windows are unblocked —
      ~one function, Linux behaviour unchanged. Other Linux flavors already work (the
      udev rule is distro-agnostic). Mouse-mode, the evdev diagnostics, and the
      installer stay Linux/KDE-only and degrade gracefully. Needs a Mac/Windows box
      to actually test.

## 🚀 Long-term / big bets

These are the project's north-star goals — larger efforts, several of which chain
off firmware reverse-engineering. Hardware on hand: **two Cyclone 2s** (one bought
as a sacrificial unit for firmware experiments) and a **GameSir G7 Pro**
(`3537:1022`). *(Note: the G7 config captures were taken on a plain **G7**
`3537:10ba`, a different model from the G7 Pro — see the G7 items below.)*

- [x] **Firmware updates from Linux.** *Done.* The MCU is a JieLi **BR23**
      (AC635N/AC695N); the vendor command `0f 17 55 88` reboots it into its BR23
      UBOOT loader (USB mass-storage, vid `0x4c4a`), which exposes SPI-NOR
      read/erase/write over SCSI. We drive that with the vendored, MIT-licensed
      **jl-uboot-tool** (kagaimiq). `gamesir_flash.py` adds loader entry, a local
      firmware library, verify-after-write and safety rails; `gamesir_loader.py`
      just enters the loader. There's an in-app **Settings → Firmware** panel
      (pick a version → flash, or back up current). Default flash is
      *firmware-region only* (`0x0–0x76fff`) so calibration/settings survive;
      verified 3.26↔3.52 both ways. Brick-proof: a bad write drops to UBOOT on the
      next power-cycle (mask-ROM), so you can always re-flash. No `sudo` once the
      `0x4c4a` udev rule is installed. *(The `.ufw` packages are encrypted; we flash
      raw images dumped from controllers you own — none are redistributed.)*
- [~] **Expand support to the GameSir G7 (family).** *Substantially done.*
      - [x] **Protocol factored into per-controller profiles** — `controller_profile.py`
        (`ControllerProfile` + `CYCLONE`/`G7`/`G7_PRO`), detection by USB product id,
        and the bridge/backup/writer now address the *active* profile instead of
        hard-coded Cyclone constants (Cyclone behaviour verified byte-identical).
      - [x] **Multi-controller picker** (single-active, switchable) + **press-to-select**
        (press a button on a pad to switch to it), deduping identical units by USB
        port since serials are empty. Verified live with 2 Cyclones + a G7 Pro.
      - [x] **G7 config protocol RE'd** (from plain-G7 `0x10ba` USB captures): same
        register protocol wrapped in a `0f 00 <seq> 3c` envelope; full trigger/stick/
        remap/vibration/report-rate map + button target codes (see
        `gamesir_g7_parse.py` and the assistant memory). Write path implemented.
      - [x] **G7-family live input over evdev** — the G7 Pro is a standard HID gamepad
        (not GIP), so input is read from evdev and mapped into state (handles the
        modern axis layout: RS on Z/RZ, triggers on GAS/BRAKE).
      - [ ] **G7 Pro config protocol** — the Pro (`0x1022`) has a vendor `0xfff0`
        collection (`hidraw14`) whose protocol is NOT captured; needs G7 Pro USB
        captures before its editor fields can work (its profile currently exposes no
        config). May differ from the plain G7's map. *Also gates the paddles:* the
        L4/R4/L5/R5 back buttons emit NO evdev events (firmware-only, like the
        Cyclone's L4/R4/M — verified), so showing/remapping them needs this channel.
      - [x] **G7 stick orientation** — *verified correct.* LS up → `ly=0`, down →
        `ly=255` (matches the QML's `center + ay·r` mapping); X works by the same
        evdev min=left convention. No per-profile invert needed.
      - [~] **G7 battery** — N/A over USB: a wired G7 Pro exposes no
        `/sys/class/power_supply` node, so there's nothing to read (shows 0). Would
        only apply to a wireless/dongle connection; revisit if that's ever used.
- [ ] **Deep firmware-package RE (once updates work).** With a known-good flashing
      path, dissect a firmware image to inventory undocumented features /
      capabilities we could expose (extra LED modes, motion, button behaviours,
      and the audio path below).
- [ ] **Audio responsiveness via the headset jack.** Investigate forcing system
      audio out through the controller's 3.5 mm jack (and/or driving the
      audio-reactive LEDs from real audio). Probably depends on the firmware RE
      above to understand the audio routing; pair with the host-side PipeWire
      capture work already noted for audio-reactive lighting.

## 🔬 Open reverse-engineering questions (need USB captures)

- [ ] **Verify the RT trigger block** (currently inferred as the LT block mirrored
      at `+0x1c`) against a capture of an RT-setting change.
- [ ] **Audio-reactive lighting: reverse the host-streaming format.** The enable
      flag (`0x20` / `0x026d`) is known, but the effect is *host-driven* — the
      controller has no mic, so the PC must stream audio levels to it. Needs a live
      USBPcap of the official app with audio-reactive **on** over music with loud/
      quiet/loud dynamics to learn the streaming command, then a PipeWire monitor →
      amplitude → stream pipeline. (Distinct from, and a prerequisite signal for,
      the long-term "audio via the headset jack" bet.)
- [~] **Reprogram View / Menu / L4 / R4 — vendor-protocol *target* codes.**
      *Target codes now known* from the G7 captures (the G7 reuses the same register
      protocol + a 7-byte-per-button remap-slot table): `LB=05, RB=06, LS=07, RS=08,
      A=09, B=0a, X=0b, Y=0c, LT=13, RT=14`, written as `[01 <target>]` to a source
      slot (`[00 00]` clears). Confirmed A/X live on the G7 and match the Cyclone's
      previously-inferred codes. Remaining: capture the **Cyclone** applying an L4/R4
      and View/Menu remap to confirm those *source*-slot addresses on the Cyclone
      specifically (the G7 slot bases may differ) and that it accepts the writes.
- [ ] **Profile-switch → bank sync:** how a `SET-PROFILE` syncs bank `0x01` to a
      store. Unlocks restoring profiles 2–4 (above).
- [ ] **PS4 / Switch-mode input parsing** — the vendor channel is Xbox-only;
      other modes need their own report parser.

## ✅ Done (recent highlights)

- [x] **Multi-controller support** — profile abstraction (`controller_profile.py`),
      live picker + press-to-select, and the whole config/backup/write stack now
      follows the *active* controller. G7 config protocol reverse-engineered; G7 Pro
      recognised with live input over evdev. Responsive top bar so the gear always
      fits. *(This session; branch `multi-controller-picker`.)*
- [x] **Controller input map captured & documented**
      ([CONTROLLER_MAP.md](CONTROLLER_MAP.md)) with a new re-enumeration-resilient
      evdev reader (`gamesir_input_map.py`): standard controls are XInput on
      `event2`; L4/R4/M are firmware-only; the pad has two USB identities.
- [x] **Live mouse-mode enable** (D-Bus `LoadPlugin`) + clearer **"Sticks → cursor"**
      label with a hover help icon explaining the KWin plugin.
- [x] **Backup Save dialog auto-names** the file (dated default); **`install.sh`
      prompts before each sudo step** and declines gracefully (non-TTY → no).
- [x] Mouse-mode root cause found: it's **KWin's Game Controller plugin** (Plasma
      6.7), not the controller. In-app toggle (off / couch mode) on KDE, with an
      EVIOCGRAB fallback elsewhere.
- [x] **Backup / Restore** verified end-to-end, with write-verify-retry and an
      inline confirm button (no fragile modal).
- [x] No-`sudo` udev rule; wired/wireless firmware labelling; human-readable
      labelled JSON export.
- [x] Custom sensitivity-curve editor; per-slot keyframe add/remove; lighting
      effect presets + power settings.

---

*Hardware: GameSir Cyclone 2 in Xbox / XInput mode (hold the green button ~2s).
See [README.md](README.md) for setup and protocol notes.*
