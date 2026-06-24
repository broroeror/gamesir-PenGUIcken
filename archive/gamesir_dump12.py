"""
GameSir Cyclone 2 - Raw 0x12 Dump
=================================
Settles one question: does the enhanced 0x12 report actually carry live input,
or is it streaming empty/zero payloads?

Prints the first full 0x12 report, then prints the report's non-zero bytes
only when they change. Press L4/R4/M/A/LB and move the sticks.
  - If you see byte changes -> 0x12 carries data, we can map it.
  - If pressing buttons changes NOTHING -> 0x12 is empty (input not enabled),
    and the read path is gated behind the (currently broken) command channel.

Run with: sudo python3 gamesir_dump12.py   (Ctrl+C to stop)
"""

import hid

VENDOR_PATH = b'/dev/hidraw6'


def main():
    device = hid.device()
    try:
        device.open_path(VENDOR_PATH)
    except Exception as e:
        print(f"FAILED to open {VENDOR_PATH.decode()}: {e}")
        return
    device.set_nonblocking(True)

    print("Press L4, R4, M, A, LB and move both sticks. Ctrl+C to stop.\n")
    first_shown = False
    prev = None
    try:
        while True:
            try:
                data = device.read(64, timeout_ms=200)
            except OSError:
                continue
            if not data or data[0] != 0x12:
                continue

            if not first_shown:
                print("First 0x12 report (all 64 bytes):")
                print("  " + bytes(data).hex(' '))
                print("\nNow watching for changes (non-zero bytes shown)...\n")
                first_shown = True

            body = tuple(data)
            if body != prev:
                prev = body
                nz = [(i, data[i]) for i in range(len(data)) if data[i] != 0]
                # drop byte 0 (report ID 0x12) from the "interesting" view
                nz = [(i, v) for (i, v) in nz if i != 0]
                print(f"changed -> non-zero payload bytes: {nz}")
    except KeyboardInterrupt:
        pass
    finally:
        try:
            device.close()
        except Exception:
            pass
        print("\nStopped.")


if __name__ == '__main__':
    main()
