import hid

device = hid.device()
device.open_path(b'/dev/hidraw0')
device.set_nonblocking(False)

print("Press buttons one at a time (Ctrl+C to stop):")
try:
    prev = None
    while True:
        data = device.read(64)
        if data:
            # Only compare bytes 5, 6, 8, 9 (dpad, buttons, triggers)
            # Ignore everything else including gyro/accel/timestamp
            snapshot = (data[5], data[6], data[8], data[9])
            if snapshot != prev:
                prev = snapshot
                print(f"Dpad:{data[5]&0x0F:2d} B1:{data[5]:08b} B2:{data[6]:08b} B3:{data[7]:08b} LT:{data[8]:3d} RT:{data[9]:3d}")
except KeyboardInterrupt:
    pass
finally:
    device.close()