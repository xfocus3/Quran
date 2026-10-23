"""Bounded private emulator snapshots, shared by boot and device checks."""
from datetime import datetime, timezone
import subprocess


def capture(adb, out, prefix, stopping=lambda: False):
    out.mkdir(parents=True, exist_ok=True)
    commands = {
        'logcat': ['logcat', '-d', '-b', 'all', '-t', '3000'],
        'lastanr': ['shell', 'dumpsys', 'activity', 'lastanr'],
        'anr-traces': ['shell', 'dumpsys activity lastanr-traces | head -c 2097152'],
        'cpu': ['shell', 'dumpsys', 'cpuinfo'],
        'memory': ['shell', 'cat', '/proc/meminfo'],
        'window': ['shell', 'dumpsys', 'window', 'displays'],
        'properties': ['shell', 'getprop'],
        'input': ['shell', 'getevent', '-pl'],
    }
    for name, args in commands.items():
        if stopping():
            return
        path = out / f'{prefix}-{name}.txt'
        try:
            value = subprocess.check_output([*adb, *args], text=True,
                                            stderr=subprocess.STDOUT, timeout=8)
        except Exception as error:
            # Teardown can race the next sample. Keep the last successful bytes
            # rather than replacing the evidence with an availability message.
            path = path.with_suffix('.error.txt')
            value = (f'{datetime.now(timezone.utc).isoformat()}: Diagnostic unavailable: '
                     f'{type(error).__name__}; existing snapshot left unchanged.\n')
        temporary = path.with_suffix('.tmp')
        temporary.write_text(value)
        temporary.replace(path)
    if not stopping():
        try:
            image = subprocess.check_output([*adb, 'exec-out', 'screencap', '-p'],
                                            stderr=subprocess.DEVNULL, timeout=8)
            path = out / f'{prefix}-screen.png'
            temporary = path.with_suffix('.tmp')
            temporary.write_bytes(image)
            temporary.replace(path)
        except Exception:
            pass
