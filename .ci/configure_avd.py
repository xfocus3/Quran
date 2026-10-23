"""Set the comparison viewport before System UI starts, on hosted workers only."""
import os
from pathlib import Path

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
