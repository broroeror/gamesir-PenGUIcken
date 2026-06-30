#!/usr/bin/env python3
"""
GameSir Cyclone 2 - firmware flasher (Linux)
============================================
Orchestrates a full, reversible firmware flash:

    enter loader (vendor cmd 0f 17 55 88)  ->  jl-uboot-tool write/read  ->  reset

The controller's MCU is a JieLi BR23 (AC635N/AC695N). In normal mode it's an
Xbox-mode HID gamepad (vid 0x3537); the vendor command 0f 17 55 88 reboots it
into its BR23 UBOOT loader (a USB mass-storage device, vid 0x4c4a) which exposes
SPI-NOR read/erase/write over SCSI. We drive that via the vendored, MIT-licensed
jl-uboot-tool (kagaimiq); this module adds loader-entry, a firmware *library*,
verify-after-write, and safety rails.

Brick-proof: if a write is interrupted, the BR23 mask-ROM auto-enters UBOOT on
the next power-cycle, so you can always re-flash. The ROM is untouchable. The
only irreversible op is burning the chipkey, which is never invoked here.

No sudo needed once the udev rule (70-gamesir.rules, the 0x4c4a scsi_generic
line) is installed; otherwise run with sudo.

Firmware library (firmware/):
  cyclone2_<ver>_fw.bin    flashable version, firmware region only (0x0-0x76fff);
                           PRESERVES the controller's own config/calibration.
  cyclone2_<ver>_full.bin  full 1 MB image; flashing it OVERWRITES config too.
  backups/                 full per-unit dumps made by `backup`.

Usage:
  python3 gamesir_flash.py status              show controller + loader state
  python3 gamesir_flash.py list                list the firmware library
  python3 gamesir_flash.py backup [--label L]  dump the connected controller
  python3 gamesir_flash.py flash <ver> [--full] [--file F] [--no-verify] [--yes]
  python3 gamesir_flash.py reset               kick the loader back to normal mode
"""
import argparse
import glob
import os
import subprocess
import sys
import tempfile
import time

import hid

from gs_common import find_vendor_hidraw, read_firmware_version, pad

HERE = os.path.dirname(os.path.abspath(__file__))
FW_DIR = os.path.join(HERE, 'firmware')
BACKUP_DIR = os.path.join(FW_DIR, 'backups')
JLUBOOT_DIR = os.path.join(HERE, 'jl-uboot-tool')
JLUBOOT_PY = os.path.join(JLUBOOT_DIR, 'jluboottool.py')

PRODUCT = 'cyclone2'
FLASH_SIZE = 0x100000      # 1 MB SPI-NOR
FW_REGION = 0x77000        # firmware region (header + body), excludes config sectors
ENTER_LOADER = (0x0F, 0x17, 0x55, 0x88)
LOADER_VID = '4c4a'


class FlashError(Exception):
    pass


# --- jl-uboot-tool plumbing ---------------------------------------------------
def _jluboot_python():
    """Prefer jl-uboot-tool's venv (has crcmod/pyyaml/pycryptodomex/tqdm)."""
    venv = os.path.join(JLUBOOT_DIR, 'venv', 'bin', 'python')
    return venv if os.path.exists(venv) else sys.executable


def _find_loader():
    """Return the /dev/sgN path of the JieLi loader, or None. Needs sg access."""
    sys.path.insert(0, JLUBOOT_DIR)
    try:
        from jldevfind import find_jl_devices
    except Exception as e:
        raise FlashError(f"can't import jl-uboot-tool (vendored at {JLUBOOT_DIR}): {e}")
    for d in find_jl_devices(venfilter='BR23'):
        return d['path']
    return None


def _sg_nodes():
    return set(glob.glob('/dev/sg*'))


def _jluboot(sgpath, command, inherit=True):
    """Run one jl-uboot-tool shell command (e.g. 'write 0x0 img.bin') on sgpath.
    `command` is passed as a SINGLE argv token (the tool splits it itself)."""
    py = _jluboot_python()
    argv = [py, JLUBOOT_PY, '--chip', 'br23', '--device', sgpath, command]
    kw = {} if inherit else dict(stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return subprocess.run(argv, cwd=JLUBOOT_DIR, text=True, **kw)


# --- loader entry / exit ------------------------------------------------------
def current_version():
    """bcdDevice firmware version of the connected gamepad, or None."""
    return read_firmware_version()


def _send_enter_loader_hid():
    """Send the enter-loader vendor command over a fresh hidraw handle (CLI use)."""
    node, name, _ = find_vendor_hidraw()
    if not node:
        raise FlashError("no controller found: plug in the Cyclone 2 in Xbox mode "
                         "(hold the green button ~2s), or it's already in the loader "
                         "but /dev/sg* isn't accessible (install the udev rule or use sudo).")
    try:
        d = hid.device()
        d.open_path(node.encode())
        d.write(pad(*ENTER_LOADER))
        d.close()
    except Exception as e:
        # a write error is normal if it drops off instantly
        sys.stderr.write(f"(enter-loader write: {e})\n")


def enter_loader(timeout=8.0, send=None):
    """Ensure the controller is in BR23 UBOOT; return its /dev/sgN path.

    If already in the loader, just find it. Otherwise emit the enter-loader
    command and wait for the loader to appear. `send` is an optional callable
    that emits the command over an existing channel (the GUI passes its own
    control writer so we don't open a second hidraw handle); default uses hidraw.
    """
    try:
        existing = _find_loader()
    except FlashError:
        existing = None
    if existing:
        return existing

    before = _sg_nodes()
    (send or _send_enter_loader_hid)()

    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(0.4)
        try:
            sg = _find_loader()
        except FlashError:
            sg = None
        if sg:
            return sg
    # didn't find it: distinguish "no loader" from "no permission"
    new = _sg_nodes() - before
    if new:
        nodes = ', '.join(sorted(new))
        raise FlashError(f"loader appeared ({nodes}) but jl-uboot-tool can't open it. "
                         "Install the udev rule (70-gamesir.rules) and reload, or run with sudo.")
    raise FlashError("loader did not appear after enter-loader command.")


def reset_controller(sgpath=None):
    """Kick the loader back into normal (app) mode. The reset drops the device
    off USB mid-command, so jl-uboot-tool reports a benign transfer error."""
    sg = sgpath or _find_loader()
    if not sg:
        return False
    _jluboot(sg, 'reset', inherit=False)   # swallow the expected error
    return True


# --- flash / read / verify ----------------------------------------------------
def _looks_like_raw(path):
    if path.lower().endswith('.ufw'):
        raise FlashError(f"{os.path.basename(path)} is a packaged .ufw, NOT a raw "
                         "flash image. Only raw .bin dumps can be written.")
    sz = os.path.getsize(path)
    if sz == 0 or sz > FLASH_SIZE:
        raise FlashError(f"{os.path.basename(path)} size {sz} is not a valid raw image "
                         f"(expected 1..{FLASH_SIZE} bytes).")
    return sz


def flash_image(image_path, sgpath, verify=True):
    """Write image_path at flash address 0 (erases only its own length, so a
    firmware-only image leaves the config sectors intact). Optionally verify."""
    n = _looks_like_raw(image_path)
    print(f"Flashing {os.path.basename(image_path)} ({n} bytes / 0x{n:x}) ...")
    r = _jluboot(sgpath, f"write 0x0 {image_path}")
    if r.returncode != 0:
        raise FlashError("write failed (jl-uboot-tool returned non-zero). "
                         "Power-cycle the controller -> it auto-enters UBOOT -> re-flash.")
    if verify:
        print("Verifying ...")
        if not verify_region(image_path, sgpath):
            raise FlashError("VERIFY MISMATCH! Do NOT unplug. Re-flash a known-good image now.")
        print("Verify OK - flash matches the image.")


def verify_region(image_path, sgpath):
    n = os.path.getsize(image_path)
    tmp = tempfile.mktemp(prefix='gsfw_', suffix='.bin')
    try:
        r = _jluboot(sgpath, f"read 0x0 0x{n:x} {tmp}", inherit=False)
        if r.returncode != 0 or not os.path.exists(tmp):
            return False
        with open(tmp, 'rb') as a, open(image_path, 'rb') as b:
            return a.read() == b.read()
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def read_full(out_path, sgpath, inherit=True):
    r = _jluboot(sgpath, f"read 0x0 0x{FLASH_SIZE:x} {out_path}", inherit=inherit)
    if r.returncode != 0:
        raise FlashError("flash read failed.")
    return out_path


# --- high-level operations (used by both the CLI and the GUI bridge) ----------
def flash_version(version=None, *, file=None, full=False, verify=True,
                  on_progress=None, send=None):
    """Resolve an image, enter the loader, write (+verify), and reset.

    on_progress(phase:str) is called at each phase (GUI). send is an optional
    enter-loader emitter (GUI passes its own control writer). Returns the image.
    """
    quiet = on_progress is not None
    prog = on_progress or (lambda _p: None)
    image = file or pick_firmware(version, full=full)
    n = _looks_like_raw(image)

    prog("Entering loader…")
    sg = enter_loader(send=send)
    prog(f"Writing firmware ({n // 1024} KB)…")
    r = _jluboot(sg, f"write 0x0 {image}", inherit=not quiet)
    if r.returncode != 0:
        raise FlashError("write failed. Power-cycle the controller -> it auto-enters "
                         "UBOOT -> re-flash.")
    if verify:
        prog("Verifying…")
        if not verify_region(image, sg):
            raise FlashError("VERIFY MISMATCH! Do NOT unplug. Re-flash a known-good image now.")
    prog("Resetting…")
    reset_controller(sg)
    prog("Done")
    return image


def backup_current(label=None, on_progress=None, send=None, derive_fw=True):
    """Dump the connected controller's full flash into firmware/backups/.

    Reads the version first (must be done before entering the loader). Returns the
    backup path.
    """
    prog = on_progress or (lambda _p: None)
    ver = current_version() or 'unknown'
    os.makedirs(BACKUP_DIR, exist_ok=True)
    lbl = (label + '_') if label else ''
    stamp = time.strftime('%Y%m%d-%H%M%S')
    out = os.path.join(BACKUP_DIR, f"{PRODUCT}_{lbl}{ver}_{stamp}_full.bin")

    prog("Entering loader…")
    sg = enter_loader(send=send)
    prog("Reading flash (1 MB)…")
    read_full(out, sg, inherit=on_progress is None)
    prog("Resetting…")
    reset_controller(sg)

    if derive_fw and os.path.getsize(out) == FLASH_SIZE and ver != 'unknown':
        fwpath = os.path.join(FW_DIR, f"{PRODUCT}_{ver}_fw.bin")
        if not os.path.exists(fwpath):
            with open(out, 'rb') as a, open(fwpath, 'wb') as b:
                b.write(a.read()[:FW_REGION])
    prog("Done")
    return out, ver


# --- firmware library ---------------------------------------------------------
def list_firmware():
    """Return [{path, product, version, kind}] for the flashable library."""
    out = []
    for path in sorted(glob.glob(os.path.join(FW_DIR, '*.bin'))):
        base = os.path.basename(path)[:-4]
        parts = base.split('_')
        if len(parts) >= 3 and parts[-1] in ('fw', 'full'):
            out.append({'path': path, 'product': '_'.join(parts[:-2]),
                        'version': parts[-2], 'kind': parts[-1]})
    return out


def pick_firmware(version, full=False):
    kind = 'full' if full else 'fw'
    for f in list_firmware():
        if f['version'] == version and f['kind'] == kind and f['product'] == PRODUCT:
            return f['path']
    raise FlashError(f"no {PRODUCT} {version} ({kind}) image in {FW_DIR}. "
                     f"Run `list` to see what's available, or `backup` to make one.")


# --- CLI commands -------------------------------------------------------------
def cmd_status(args):
    ver = current_version()
    print(f"Controller (normal mode): firmware {ver}" if ver else
          "No normal-mode controller detected.")
    try:
        sg = _find_loader()
        print(f"Loader present: BR23 UBOOT at {sg}" if sg else "Loader: not present.")
    except FlashError as e:
        print(f"Loader: unknown ({e})")


def cmd_list(args):
    ver = current_version()
    print(f"Connected controller: {PRODUCT} firmware {ver}\n" if ver else
          "No controller connected.\n")
    fws = list_firmware()
    if not fws:
        print(f"Firmware library ({FW_DIR}) is empty. Use `backup` to add the current image.")
        return
    print(f"Firmware library ({FW_DIR}):")
    for f in fws:
        tag = "firmware-only, keeps your settings" if f['kind'] == 'fw' else "FULL image, overwrites config"
        here = "  <- installed" if f['version'] == ver and f['kind'] == 'fw' else ""
        print(f"  {f['product']} {f['version']:<8} [{f['kind']:>4}]  {tag}{here}")


def cmd_backup(args):
    ver = current_version()
    if not ver:
        # maybe already in loader; we can still dump but won't know the version
        ver = 'unknown'
    print(f"Entering loader to back up firmware {ver} ...")
    out, ver = backup_current(label=args.label)
    print(f"Backed up {os.path.getsize(out)} bytes (firmware {ver}) -> {out}")


def cmd_flash(args):
    if args.file:
        image = args.file
        label = os.path.basename(image)
    else:
        if not args.version:
            raise FlashError("specify a <version> (see `list`) or --file <path>.")
        image = pick_firmware(args.version, full=args.full)
        label = f"{PRODUCT} {args.version} ({'full' if args.full else 'firmware-only'})"
    _looks_like_raw(image)

    cur = current_version()
    print(f"About to flash: {label}")
    print(f"  image: {image}")
    print(f"  current controller firmware: {cur or 'unknown'}")
    if args.full or (args.file and os.path.getsize(image) > FW_REGION):
        print("  ** FULL image: this OVERWRITES the controller's config/calibration. **")
    else:
        print("  firmware-only: your config/calibration is preserved.")
    if not args.yes:
        if input("Proceed? [y/N] ").strip().lower() not in ('y', 'yes'):
            raise FlashError("Aborted.")

    flash_version(version=args.version, file=args.file, full=args.full,
                  verify=not args.no_verify)
    print("Done. Controller reset to normal mode.")
    time.sleep(2)
    new = current_version()
    if new:
        print(f"Controller now reports firmware {new}.")


def cmd_reset(args):
    print("Resetting loader -> normal mode ..." if reset_controller()
          else "No loader present (nothing to reset).")


def main():
    ap = argparse.ArgumentParser(description="GameSir Cyclone 2 firmware flasher (Linux)")
    sub = ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('status').set_defaults(func=cmd_status)
    sub.add_parser('list').set_defaults(func=cmd_list)
    p = sub.add_parser('backup'); p.add_argument('--label'); p.set_defaults(func=cmd_backup)
    p = sub.add_parser('flash')
    p.add_argument('version', nargs='?')
    p.add_argument('--file', help="flash a specific .bin instead of a library version")
    p.add_argument('--full', action='store_true', help="use the full image (overwrites config)")
    p.add_argument('--no-verify', action='store_true')
    p.add_argument('--yes', action='store_true', help="skip confirmation")
    p.set_defaults(func=cmd_flash)
    sub.add_parser('reset').set_defaults(func=cmd_reset)

    args = ap.parse_args()
    try:
        args.func(args)
    except FlashError as e:
        sys.exit(f"error: {e}")
    except KeyboardInterrupt:
        sys.exit("\ninterrupted.")


if __name__ == '__main__':
    main()
