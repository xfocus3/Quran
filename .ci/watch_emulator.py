"""Retain the latest boot snapshot before the emulator action can tear it down."""
import os
from pathlib import Path
import subprocess
import sys
import time
from emulator_diagnostics import capture

OUT = Path('.ci/out/device')
STOP = OUT / 'boot-watch.stop'
STARTED = OUT / 'boot-watch.started'
DONE = OUT / 'boot-watch.done'


def watch():
    # Each hosted job owns exactly this emulator port. No PID killing or access
    # to any developer emulator is used. The hosted runner reaps job processes.
    adb = ['adb', '-s', 'emulator-5554']
    deadline = time.monotonic() + 900
    try:
        while time.monotonic() < deadline and not STOP.exists():
            try:
                state = subprocess.check_output([*adb, 'get-state'], text=True,
                                                stderr=subprocess.DEVNULL, timeout=5)
                if state.strip() == 'device':
                    capture(adb, OUT / 'boot-watch', 'latest', STOP.exists)
            except Exception as error:
                (OUT / 'boot-watch-error.txt').write_text(type(error).__name__ + '\n')
            for _ in range(10):
                if STOP.exists():
                    break
                time.sleep(.5)
    finally:
        DONE.touch()


def stop():
    if not STARTED.exists():
        return
    STOP.touch()
    deadline = time.monotonic() + 35
    while not DONE.exists():
        if time.monotonic() >= deadline:
            raise TimeoutError('Boot observer did not acknowledge shutdown')
        time.sleep(.25)


if __name__ == '__main__':
    if os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('RUNNER_ENVIRONMENT') != 'github-hosted':
        raise RuntimeError('Boot observation belongs to the disposable hosted worker')
    if sys.argv[1:] == ['--stop']:
        stop()
    elif not sys.argv[1:]:
        watch()
    else:
        raise ValueError('Usage: watch_emulator.py [--stop]')
