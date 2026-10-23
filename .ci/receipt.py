"""Bind hosted build results to the public source, private input pack and APKs."""
import hashlib
import json
import os
from pathlib import Path

root = Path(__file__).resolve().parents[1]
def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

data = {
    'schema': 1,
    'source_commit': os.environ['GITHUB_SHA'],
    'run_id': os.environ['GITHUB_RUN_ID'],
    'run_attempt': os.environ['GITHUB_RUN_ATTEMPT'],
    'source_export': json.loads((root / '.ci/source.json').read_text()),
    'inputs_manifest_sha256': sha(root / '.ci/inputs.json'),
    'apk_sha256': {path.name: sha(path) for path in sorted((root / '.ci/out/apks').glob('*.apk'))},
    'checks': ['Flutter analysis/tests', 'prepared artifact digests',
               'three-book data contracts', 'complete JVM display contracts',
               'debug APK builds', 'native lint', 'instrumentation APK compilation'],
    'native_unit_tests': 'NO-SOURCE; production adapters are tested by device instrumentation',
    'device_checks': 'see device-result.json; compilation alone is not execution',
    'reference_parity_accepted': False,
    'human_checkpoints_complete': False,
    'debug_signing': 'disposable hosted-worker key; not the owner signing identity',
}
(root / '.ci/out/build-receipt.json').write_text(json.dumps(data, indent=2) + '\n')
