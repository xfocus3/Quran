"""Install exact hosted APKs; run production contracts and real TalkBack checks."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import traceback

OUT = Path('.ci/out/device')
OUT.mkdir(parents=True, exist_ok=True)
result = {'source_commit': os.environ['GITHUB_SHA'], 'passed': False,
          'reference_parity_accepted': False, 'phone_access': False,
          'android_docker': False}


def run(*args, timeout=60):
    return subprocess.check_output(list(args), text=True, stderr=subprocess.STDOUT, timeout=timeout)


def main():
    devices = [line.split()[0] for line in run('adb', 'devices').splitlines()[1:]
               if '\tdevice' in line]
    if len(devices) != 1 or not devices[0].startswith('emulator-'):
        raise ValueError('Exactly one hosted emulator required')
    serial = devices[0]
    os.environ['QURAN_CI_SERIAL'] = serial
    adb = ['adb', '-s', serial]
    def shell(*args, timeout=60):
        return run(*adb, 'shell', *args, timeout=timeout)
    api = int(shell('getprop', 'ro.build.version.sdk').strip())
    if api not in (35, 36):
        raise ValueError('Expected Android 15 or 16')
    result['api'] = api
    run(*adb, 'root')
    run(*adb, 'wait-for-device')
    shell('wm', 'size', '720x1280')
    shell('wm', 'density', '320')
    shell('settings', 'put', 'system', 'font_scale', '1.0')
    shell('settings', 'put', 'global', 'airplane_mode_on', '1')
    shell('svc', 'wifi', 'disable')
    shell('svc', 'data', 'disable')
    installed = {}
    for name, package in [('app-x86_64-debug.apk', 'com.xfocus.quranly.local'),
                          ('app-debug-androidTest.apk', 'com.xfocus.quranly.local.test')]:
        apk = Path('.ci/out/apks') / name
        expected = hashlib.sha256(apk.read_bytes()).hexdigest()
        run(*adb, 'install', '-r', '-t', str(apk), timeout=180)
        remote = shell('pm', 'path', package).strip().removeprefix('package:')
        if shell('sha256sum', remote).split()[0] != expected:
            raise ValueError('Installed APK differs from build')
        installed[package] = expected
    result['installed_sha256'] = installed
    # Use the production adapter on-device, not a mock or a compile-only task.
    native = shell('am', 'instrument', '-w',
        'com.xfocus.quranly.local.test/com.xfocus.quranly.local.TafsirContractInstrumentation', timeout=1200)
    (OUT / 'native.txt').write_text(native)
    values = dict(re.findall(r'^INSTRUMENTATION_RESULT: ([^=\r\n]+)=(.*)$', native, re.M))
    contract = json.loads(Path('docs/phase-4/content-contract.json').read_text())
    expected = {'result': 'passed', 'identities': '18708', 'contexts': '7',
                'source_bom_characters': '113', 'stage': 'complete'}
    expected.update({'raw_sha256_' + book: row['raw_rows_sha256']
                     for book, row in contract['books'].items()})
    if any(values.get(k) != v for k, v in expected.items()) or 'INSTRUMENTATION_CODE: -1' not in native:
        raise ValueError('Native contract failed; inspect encrypted native.txt')
    result['native'] = values
    with (OUT / 'probe-build.log').open('w') as log:
        subprocess.run(['bash', '.ci/build_probe.sh'], stdout=log, stderr=subprocess.STDOUT, check=True)
    run(*adb, 'install', '-r', '-t', '.ci/out/probe/probe.apk')
    events = shell('getevent', '-pl')
    keyboard = re.search(r'add device \d+: (\S+)\s+name:\s+"AT Translated Set 2 keyboard"', events)
    if keyboard is None:
        raise ValueError('Hosted emulator has no supported physical keyboard')
    os.environ['QURAN_CI_KEYBOARD'] = keyboard.group(1)
    # The Google APIs image supplies TalkBack. Missing service is a hard failure.
    shell('pm', 'path', 'com.google.android.marvin.talkback')
    # Start from clean app personal state for deterministic first/final boundaries.
    shell('pm', 'clear', 'com.xfocus.quranly.local')
    with (OUT / 'talkback.log').open('w') as log:
        subprocess.run([sys.executable, '.ci/talkback.py'], stdout=log, stderr=subprocess.STDOUT,
                       check=True, timeout=1800)
    talkback = json.loads((OUT / 'talkback-result.json').read_text())
    if talkback['status'] != 'passed' or len(talkback['checks']) != 13:
        raise ValueError('TalkBack checks incomplete')
    result['talkback'] = talkback
    result['passed'] = True


try:
    main()
except BaseException:
    result['error'] = traceback.format_exc()
finally:
    (OUT / 'device-result.json').write_text(json.dumps(result, indent=2) + '\n')
if not result['passed']:
    print('::error::Device checks failed; inspect encrypted device-result.json')
    sys.exit(1)
print(f"Android API {result['api']}: native contracts and 13 real TalkBack checks passed")
