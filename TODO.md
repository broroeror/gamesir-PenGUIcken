# GameSir Cyclone 2 (Linux) — TODO / Roadmap

A living checklist of known bugs, proposed changes, and open reverse-engineering
questions. Linked from the [README](README.md). This is a hobby reverse-engineering
project — **fork it and customize it however you like.**

How to use this file: check items off as they land (`- [x]`), and add new bugs or
ideas with a one-line note (a date helps). Keep entries short; deep findings go in
the README's protocol notes or the commit message.

---

## 🐞 Known bugs / rough edges

- [ ] **Couch mode doesn't always enable live.** Turning the mouse-mode toggle
      *on* (KWin `gamecontrollerEnabled true`) may not take effect until a
      logout/login; *disabling* works live. Investigate a reliable live-enable
      (D-Bus call, KWin reconfigure variants, or a scripted plugin reload).
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
- [ ] **Easy install / packaging.** An `install.sh` that drops a `.desktop`
      launcher + icon, sets up a venv, and installs the udev rule (no CLI to
      launch). Later: a `PKGBUILD` / AUR package for `pacman`-managed installs.
      Needs an app icon (PNG/SVG).
- [ ] **Restore: per-block verify detail.** The write-verify-retry already reports
      pass/fail; could add a "verify only" action or a list of any unconfirmed
      blocks.

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
