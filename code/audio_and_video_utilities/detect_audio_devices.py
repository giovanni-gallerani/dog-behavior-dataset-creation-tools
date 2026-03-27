import sounddevice as sd

def detect_audio_devices():
    devices = sd.query_devices()
    input_devs = []
    for i, d in enumerate(devices):
        if d['max_input_channels'] > 0:
            input_devs.append(f"{i}: {d['name']}")
    return input_devs

devices = detect_audio_devices()
for d in devices:
    print(d)