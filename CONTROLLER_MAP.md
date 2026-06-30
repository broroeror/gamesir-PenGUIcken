# GameSir Cyclone 2 — input map (Linux / Xbox mode)

What each physical control reports to Linux, captured live with
[`gamesir_input_map.py`](gamesir_input_map.py) (a passive evdev reader — it just
listens, it doesn't grab the device). Codes are from `linux/input-event-codes.h`.

> Put the controller in **Xbox / XInput mode** first (hold the green button ~2s).

## Standard controls — the gamepad node (`event2` / `js0`)

These are bog-standard XInput; any game or remap tool sees them normally.

| Control | Kind | Code | Constant | Range |
|---|---|---|---|---|
| A | button | 304 | `BTN_SOUTH` | press/release |
| B | button | 305 | `BTN_EAST` | press/release |
| X | button | 308 | `BTN_WEST` | press/release |
| Y | button | 307 | `BTN_NORTH` | press/release |
| LB / RB | button | 310 / 311 | `BTN_TL` / `BTN_TR` | press/release |
| View / Menu / Guide | button | 314 / 315 / 316 | `BTN_SELECT` / `BTN_START` / `BTN_MODE` | press/release |
| L3 / R3 (stick click) | button | 317 / 318 | `BTN_THUMBL` / `BTN_THUMBR` | press/release |
| Left stick X / Y | axis | 0 / 1 | `ABS_X` / `ABS_Y` | −32768 … 32767 |
| Right stick X / Y | axis | 3 / 4 | `ABS_RX` / `ABS_RY` | −32768 … 32767 |
| LT / RT (triggers) | axis | 2 / 5 | `ABS_Z` / `ABS_RZ` | 0 … 255 (analog) |
| D-pad | axis (hat) | 16 / 17 | `ABS_HAT0X` / `ABS_HAT0Y` | −1 / 0 / +1 |

## The extra buttons — L4, R4, M (firmware-controlled, not gamepad inputs)

The two back buttons and the front **M** button are **not** exposed as gamepad
inputs — they're handled in the controller's firmware:

- **M (front)** — a *modifier* that switches lighting/input profiles on the
  controller. It sends nothing to the host; pressing combos like **M + A** cycles
  profiles internally (and can re-enumerate the USB device — see below).
- **L4 / R4 (back)** — **blank in pure XInput mode** (they emit nothing). In the
  controller's other USB identity they default to throwaway keyboard macros
  (`Alt+Super`, `Alt+PrtSc`).

Because these are firmware-side, **remapping them must go through the vendor
protocol** (the same channel this app uses to write config), not through Linux
input remapping.

## Two USB identities

The controller switches between two USB identities by re-enumerating:

| Product ID | Reported name | L4 / R4 behaviour |
|---|---|---|
| `3537:0575` | "GameSir-Cyclone 2" | send keyboard macros (`Alt+Super`, `Alt+PrtSc`) |
| `3537:100b` | "Xbox 360 Controller for Windows" | blank (no host input) |

Switching profiles/mode with the **M** combo flips the product ID. **Tools should
match the controller by vendor id `0x3537` only, never a product id** — this app's
udev rule and device-open already do, so it survives the swap.

It also exposes a mouse interface (`event9`, `ID_INPUT_MOUSE`) that emits nothing
by default — desktop cursor control ("Sticks → cursor") comes from KDE's KWin Game
Controller plugin reading the joystick, not from this interface.

---

*Re-capture anytime: `python3 gamesir_input_map.py [seconds]` and press each
control. It survives profile-switch re-enumeration and prints a per-button table
plus a grouped timeline.*
