"""Failure-path regressions; these fixtures do not establish Android behavior."""
import json
import contextlib
import io
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'device.py'
sys.path.insert(0, str(SCRIPT.parent))
from emulator_diagnostics import capture
from prepare_emulator import prepare


class DeviceFailureTest(unittest.TestCase):
    def test_initial_anr_evidence_survives_distinct_test_boot(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            rebooted = False
            reads_after_reboot = 0

            def command(args, **kwargs):
                nonlocal reads_after_reboot
                if args[-1] == '/proc/sys/kernel/random/boot_id':
                    if rebooted:
                        reads_after_reboot += 1
                    # The old boot may still answer immediately after reboot.
                    return 'new-boot' if reads_after_reboot > 1 else 'first-boot'
                return '1'

            def reboot(args, **kwargs):
                nonlocal rebooted
                rebooted = True

            def first_boot(adb, target, prefix):
                (target / f'{prefix}-lastanr.txt').write_text('initial GoogleSdkSetup ANR')

            with patch.dict(os.environ, {'GITHUB_ACTIONS': 'true', 'RUNNER_ENVIRONMENT': 'github-hosted'}), \
                    patch('subprocess.check_output', side_effect=command), \
                    patch('subprocess.check_call', side_effect=reboot), \
                    patch('prepare_emulator.capture', side_effect=first_boot), \
                    patch('time.sleep'):
                receipt = prepare(['adb', '-s', 'emulator-5554'], out)
            self.assertEqual(receipt['first_boot']['boot_id'], 'first-boot')
            self.assertEqual(receipt['test_boot']['boot_id'], 'new-boot')
            self.assertIn('GoogleSdkSetup ANR', (out / 'provisioned-first-boot-lastanr.txt').read_text())

    def test_incomplete_provisioning_cannot_become_test_boot(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch.dict(os.environ, {'GITHUB_ACTIONS': 'true', 'RUNNER_ENVIRONMENT': 'github-hosted'}), \
                patch('subprocess.check_output', return_value='0'), \
                patch('subprocess.check_call') as reboot:
            with self.assertRaisesRegex(TimeoutError, 'provisioning did not complete'):
                prepare(['adb', '-s', 'emulator-5554'], Path(tmp), timeout=0)
            reboot.assert_not_called()

    def test_unchanged_boot_cannot_become_test_boot(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch.dict(os.environ, {'GITHUB_ACTIONS': 'true', 'RUNNER_ENVIRONMENT': 'github-hosted'}), \
                patch('subprocess.check_output', return_value='1'), \
                patch('subprocess.check_call'), patch('prepare_emulator.capture'):
            with self.assertRaisesRegex(TimeoutError, 'distinct provisioned test boot'):
                prepare(['adb', '-s', 'emulator-5554'], Path(tmp), timeout=0)
            self.assertIsNone(json.loads((Path(tmp) / 'provisioning.json').read_text())['test_boot'])

    def test_lost_adb_preserves_last_successful_boot_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            def available(args, **kwargs):
                return b'fixture' if 'exec-out' in args else 'last useful boot trace\n'
            with patch('subprocess.check_output', side_effect=available):
                capture(['adb', '-s', 'emulator-5554'], out, 'latest')
            with patch('subprocess.check_output', side_effect=subprocess.CalledProcessError(1, 'adb')):
                capture(['adb', '-s', 'emulator-5554'], out, 'latest')
            self.assertEqual((out / 'latest-lastanr.txt').read_text(), 'last useful boot trace\n')
            self.assertIn('CalledProcessError', (out / 'latest-lastanr.error.txt').read_text())

    def test_boot_observer_retains_evidence_without_device_tests_and_stops(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / '.ci/out/device'
            output.mkdir(parents=True)
            (output / 'boot-watch.started').touch()
            tools = root / 'bin'
            tools.mkdir()
            fake_adb = tools / 'adb'
            fake_adb.write_text('#!' + sys.executable + '\nimport sys\n'
                                'print("device" if sys.argv[-1] == "get-state" else "boot diagnostic fixture")\n')
            fake_adb.chmod(0o755)
            env = os.environ | {'PATH': str(tools) + os.pathsep + os.environ['PATH'],
                                'GITHUB_ACTIONS': 'true', 'RUNNER_ENVIRONMENT': 'github-hosted'}
            watcher = SCRIPT.parent / 'watch_emulator.py'
            child = subprocess.Popen([sys.executable, str(watcher)], cwd=root, env=env,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                evidence = output / 'boot-watch/latest-lastanr.txt'
                deadline = time.monotonic() + 10
                while not evidence.exists() and time.monotonic() < deadline:
                    self.assertIsNone(child.poll(), 'Observer exited before capturing boot evidence')
                    time.sleep(.05)
                self.assertIn('boot diagnostic fixture', evidence.read_text())
                self.assertFalse((output / 'device-result.json').exists())
                subprocess.run([sys.executable, str(watcher), '--stop'], cwd=root,
                               env=env, check=True, timeout=10)
                self.assertEqual(child.wait(timeout=3), 0)
                self.assertTrue((output / 'boot-watch.done').exists())
            finally:
                if child.poll() is None:
                    child.terminate()
                    child.wait(timeout=3)

    def test_diagnostic_write_error_preserves_primary_device_failure(self):
        original_write = Path.write_text

        def write(path, *args, **kwargs):
            if path.name.startswith('final-'):
                raise OSError('diagnostic fixture failure')
            return original_write(path, *args, **kwargs)

        def adb(args, **kwargs):
            if args == ['adb', 'devices']:
                return 'List of devices attached\nemulator-5554\tdevice\n'
            if args[-1] == 'ro.build.version.sdk':
                return '34\n'
            return ''

        previous = Path.cwd()
        with tempfile.TemporaryDirectory() as tmp:
            try:
                os.chdir(tmp)
                with patch.dict(os.environ, {'GITHUB_SHA': 'c' * 40}), \
                        patch('subprocess.check_output', side_effect=adb), \
                        patch.object(Path, 'write_text', write):
                    with self.assertRaises(SystemExit) as exited, contextlib.redirect_stdout(io.StringIO()):
                        runpy.run_path(str(SCRIPT), run_name='__main__')
                self.assertEqual(exited.exception.code, 1)
                result = json.loads(Path('.ci/out/device/device-result.json').read_text())
                self.assertFalse(result['passed'])
                self.assertIn('Expected Android 15 or 16', result['error'])
                self.assertNotIn('diagnostic fixture failure', result['error'])
            finally:
                os.chdir(previous)


if __name__ == '__main__':
    unittest.main()
