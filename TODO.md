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
- [ ] **Capture View / Menu / L4 / R4 remap *target* codes** (only their source
      addresses are mapped so far).
- [ ] **Profile-switch → bank sync:** how a `SET-PROFILE` syncs bank `0x01` to a
      store. Unlocks restoring profiles 2–4 (above).
- [ ] **PS4 / Switch-mode input parsing** — the vendor channel is Xbox-only;
      other modes need their own report parser.

## ✅ Done (recent highlights)

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
