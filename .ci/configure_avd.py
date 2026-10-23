"""Set the comparison viewport before System UI starts, on hosted workers only."""
import os
from pathlib import Path
import subprocess
import sys

if os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('RUNNER_ENVIRONMENT') != 'github-hosted':
    raise RuntimeError('AVD configuration belongs to the disposable hosted worker')

path = Path(os.environ['ANDROID_AVD_HOME']) / 'quran-ci.avd/config.ini'
settings = {'hw.lcd.width': '720', 'hw.lcd.height': '1280', 'hw.lcd.density': '320'}
lines = [line for line in path.read_text().splitlines()
         if line.partition('=')[0].strip() not in settings]
path.write_text('\n'.join(lines + [f'{key}={value}' for key, value in settings.items()]) + '\n')
out = Path('.ci/out/device')
out.mkdir(parents=True, exist_ok=True)
(out / 'avd-config.ini').write_text(path.read_text())
# Start before the action launches/waits for Android, so even a boot timeout
# leaves a bounded snapshot. All child streams stay in the encrypted output.
(out / 'boot-watch.started').touch()
with (out / 'boot-watch.log').open('w') as log:
    subprocess.Popen([sys.executable, '.ci/watch_emulator.py'], stdin=subprocess.DEVNULL,
                     stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
