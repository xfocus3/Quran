"""Finish disposable-image provisioning, then require a distinct clean test boot.

GoogleSdkSetup can finish its initial provider setup after its input timeout.
Retain that first-boot failure; never dismiss ANRs or retry application checks.
"""
import json
import os
import subprocess
import time

from emulator_diagnostics import capture


def prepare(adb, out, timeout=300):
    if (os.environ.get('GITHUB_ACTIONS') != 'true' or
            os.environ.get('RUNNER_ENVIRONMENT') != 'github-hosted' or
            adb != ['adb', '-s', 'emulator-5554']):
        raise ValueError('Provisioning belongs to the disposable hosted emulator')

    def shell(*args):
        return subprocess.check_output([*adb, 'shell', *args], text=True,
                                       stderr=subprocess.STDOUT, timeout=10).strip()

    def state():
        return {'boot_id': shell('cat', '/proc/sys/kernel/random/boot_id'),
                'boot_completed': shell('getprop', 'sys.boot_completed'),
                'device_provisioned': shell('settings', 'get', 'global', 'device_provisioned'),
                'user_setup_complete': shell('settings', 'get', 'secure', 'user_setup_complete')}

    def ready(value):
        return (bool(value['boot_id']) and value['boot_completed'] == '1' and
                value['device_provisioned'] == '1' and value['user_setup_complete'] == '1')

    deadline = time.monotonic() + timeout
    initial = state()
    while not ready(initial):
        if time.monotonic() >= deadline:
            raise TimeoutError('Initial image provisioning did not complete')
        time.sleep(2)
        initial = state()
    # Keep the actual initial ANR, log and screenshot before the clean reboot.
    capture(adb, out, 'provisioned-first-boot')
    receipt = {'first_boot': initial, 'test_boot': None,
               'application_installed_before_reboot': False}
    path = out / 'provisioning.json'
    path.write_text(json.dumps(receipt, indent=2) + '\n')
    subprocess.check_call([*adb, 'reboot'], timeout=15)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            current = state()
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            # ADB disconnects while the same owned guest reboots.
            current = None
        if current and ready(current) and current['boot_id'] != initial['boot_id']:
            receipt['test_boot'] = current
            path.write_text(json.dumps(receipt, indent=2) + '\n')
            return receipt
        time.sleep(2)
    raise TimeoutError('Hosted emulator did not complete a distinct provisioned test boot')
