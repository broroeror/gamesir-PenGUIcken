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
off firmware reverse-engineering. Hardware on hand: **a 2nd Cyclone 2** (bought as
a sacrificial unit for firmware experiments) and **a GameSir G7**.

- [ ] **Firmware updates from Linux.** The headline long-term goal. Capture the
      official updater's USB traffic (DFU/bootloader entry, block transfer, verify,
      reboot) and reproduce the flashing flow. *Use the spare Cyclone 2 as the
      guinea pig* — a botched flash could brick it, so never test on the daily
      driver first.
- [ ] **Expand support to the GameSir G7.** First confirm how much of the existing
      Cyclone 2 stack (vendor channel, register map, LED/config banks) already
      applies to the G7 vs. what differs. Likely needs its own register map +
      capture set; aim to factor the protocol core so a controller is a profile of
      register addresses rather than hard-coded constants.
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
- [ ] **Reprogram View / Menu / L4 / R4 — find the vendor-protocol *target* codes.**
      Source side is now fully understood (see
      [CONTROLLER_MAP.md](CONTROLLER_MAP.md)): L4/R4/M are *firmware-controlled*, not
      gamepad inputs, and the pad has two USB identities (`3537:0575` where L4/R4
      send keyboard macros, `3537:100b` pure XInput where they're blank). So
      remapping them must go over the vendor channel — capture the official app
      assigning each to learn the target-code format.
- [ ] **Profile-switch → bank sync:** how a `SET-PROFILE` syncs bank `0x01` to a
      store. Unlocks restoring profiles 2–4 (above).
- [ ] **PS4 / Switch-mode input parsing** — the vendor channel is Xbox-only;
      other modes need their own report parser.

## ✅ Done (recent highlights)

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
