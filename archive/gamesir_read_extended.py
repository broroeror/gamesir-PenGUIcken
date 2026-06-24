import hid

vendor = hid.device()
vendor.open_path(b'/dev/hidraw6')
vendor.set_nonblocking(False)  # blocking this time

print("Press ANY button including L4/R4 (Ctrl+C to stop):")
try:
    while True:
        data = vendor.read(64)
        if data and any(b != 0 for b in data):
            print(data[:10])
except KeyboardInterrupt:
    pass
finally:
    vendor.close()