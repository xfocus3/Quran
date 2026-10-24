"""Install exact hosted APKs; run production contracts and real TalkBack checks."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import traceback
from emulator_diagnostics import capture
from emulator_profile import PHYSICAL_SIZE, PHYSICAL_DENSITY
from prepare_emulator import prepare
from reader import REQUIRED as READER_CHECKS

OUT = Path('.ci/out/device')
OUT.mkdir(parents=True, exist_ok=True)
result = {'source_commit': os.environ['GITHUB_SHA'], 'passed': False,
          'reference_parity_accepted': False, 'phone_access': False,
          'android_docker': False}
adb = None


def run(*args, timeout=60):
    return subprocess.check_output(list(args), text=True, stderr=subprocess.STDOUT, timeout=timeout)


def diagnostics(stage):
    """Best-effort bounded private evidence; never replace the original failure."""
    if adb is None:
        return
    capture(adb, OUT, stage)


def require_healthy_android(stage):
    # A boot property alone precedes the observed SurfaceFlinger/System UI ANR.
    # Never dismiss that dialog or turn an unhealthy test platform into a pass.
    boot = run(*adb, 'shell', 'getprop', 'sys.boot_completed').strip()
    anr = run(*adb, 'shell', 'dumpsys', 'activity', 'lastanr')
    (OUT / f'{stage}-lastanr.txt').write_text(anr)
    if boot != '1' or '<no ANR has occurred since boot>' not in anr:
        raise ValueError('Android startup/runtime is unhealthy; inspect encrypted diagnostics')
    result.setdefault('android_health_checks', []).append(stage)


def main():
    global adb
    (OUT / 'boot-watch.stop').touch()
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
    result['provisioning'] = prepare(adb, OUT)
    run(*adb, 'root')
    run(*adb, 'wait-for-device')
    if int(shell('getprop', 'ro.build.version.sdk').strip()) != api:
        raise ValueError('Hosted Android API changed during provisioning')
    # Configure the physical viewport before boot, not by restarting System UI
    # with a display override during its first-boot initialization.
    if shell('wm', 'size').strip() != PHYSICAL_SIZE or shell('wm', 'density').strip() != PHYSICAL_DENSITY:
        raise ValueError('Hosted comparison viewport differs from the preboot configuration')
    time.sleep(30)
    require_healthy_android('startup')
    diagnostics('startup')
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
    # Reader touch/clipboard/export checks run with accessibility disabled and
    # deterministic personal state, before the separate real TalkBack sequence.
    shell('pm', 'clear', 'com.xfocus.quranly.local')
    with (OUT / 'reader.log').open('w') as log:
        subprocess.run([sys.executable, '.ci/reader.py'], stdout=log, stderr=subprocess.STDOUT,
                       check=True, timeout=2700)  # 40-minute harness plus bounded cleanup.
    reader_path = OUT / 'reader/reader-result.json'
    reader = json.loads(reader_path.read_text())
    if (reader.get('status') != 'passed' or reader.get('source_commit') != os.environ['GITHUB_SHA'] or
            reader.get('api') != api or reader.get('required_checks') != list(READER_CHECKS) or
            [row.get('name') for row in reader.get('checks', [])] != list(READER_CHECKS) or
            any(row.get('status') != 'passed' for row in reader.get('checks', [])) or
            reader.get('errors') != [] or reader.get('missing_checks') != []):
        raise ValueError('Reader construction checks incomplete')
    result['reader'] = {'status': reader['status'], 'checks': list(READER_CHECKS),
                        'receipt_sha256': hashlib.sha256(reader_path.read_bytes()).hexdigest()}
    require_healthy_android('after-reader')
    events = shell('getevent', '-pl')
    keyboard = re.search(r'add device \d+: (\S+)\s+name:\s+"AT Translated Set 2 keyboard"', events)
    if keyboard is None:
        raise ValueError('Hosted emulator has no supported physical keyboard')
    os.environ['QURAN_CI_KEYBOARD'] = keyboard.group(1)
    # The Google APIs image supplies TalkBack. Missing service is a hard failure.
    talkback_package = 'com.google.android.marvin.talkback'
    shell('pm', 'path', talkback_package)
    # Provision the test service, not the application under test. Android16
    # otherwise opens its notification permission dialog when TalkBack is
    # toggled for the distant-state setup, covering all reader controls.
    shell('pm', 'grant', talkback_package, 'android.permission.POST_NOTIFICATIONS')
    shell('pm', 'set-permission-flags', talkback_package,
          'android.permission.POST_NOTIFICATIONS', 'user-set')
    shell('pm', 'clear-permission-flags', talkback_package,
          'android.permission.POST_NOTIFICATIONS', 'user-fixed')
    permissions = shell('dumpsys', 'package', talkback_package)
    if not re.search(r'^\s+android\.permission\.POST_NOTIFICATIONS: granted=true(?:,|\s|$)',
                     permissions, re.M):
        raise ValueError('TalkBack notification permission was not provisioned')
    result['talkback_notification_permission'] = 'granted for test service only'
    # Start from clean app personal state for deterministic first/final boundaries.
    shell('pm', 'clear', 'com.xfocus.quranly.local')
    with (OUT / 'talkback.log').open('w') as log:
        subprocess.run([sys.executable, '.ci/talkback.py'], stdout=log, stderr=subprocess.STDOUT,
                       check=True, timeout=1800)
    talkback = json.loads((OUT / 'talkback-result.json').read_text())
    if talkback['status'] != 'passed' or len(talkback['checks']) != 13:
        raise ValueError('TalkBack checks incomplete')
    result['talkback'] = talkback
    require_healthy_android('after-talkback')
    result['passed'] = True


try:
    main()
except BaseException:
    result['error'] = traceback.format_exc()
finally:
    # Persist the primary outcome before any best-effort diagnostic I/O.
    (OUT / 'device-result.json').write_text(json.dumps(result, indent=2) + '\n')
    try:
        diagnostics('final')
    except Exception:
        print('::warning::Some private emulator diagnostics could not be retained')
if not result['passed']:
    print('::error::Device checks failed; inspect encrypted device-result.json')
    sys.exit(1)
print(f"Android API {result['api']}: native contracts, 15 reader and 13 real TalkBack checks passed")
