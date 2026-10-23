#!/usr/bin/env bash
set -euo pipefail
mkdir -p .ci/out/apks .ci/out/logs
run() {
  local stage="$1"
  shift
  echo "Running $stage"
  if ! "$@" >".ci/out/logs/$stage.log" 2>&1; then
    echo "::error::$stage failed; inspect the encrypted result logs."
    return 1
  fi
}
run inputs python .ci/vault.py verify .ci/inputs.json .
run prepared python tools/prepare_artifacts.py verify-prepared
run flutter-dependencies flutter pub get --enforce-lockfile
run flutter-analysis flutter analyze --no-pub
run flutter-tests flutter test --no-pub --machine
run data-tests python -m unittest discover -s tests -p 'test_phase4.py' -v
run display-tests python -m unittest discover -s tests -p 'test_tafsir_display.py' -v
run apks flutter build apk --debug --no-pub --target-platform android-arm64,android-x64 --split-per-abi
run native-checks bash -c 'cd android && ./gradlew --no-daemon testDebugUnitTest lintDebug assembleDebugAndroidTest'
cp build/app/outputs/flutter-apk/app-arm64-v8a-debug.apk .ci/out/apks/
cp build/app/outputs/flutter-apk/app-x86_64-debug.apk .ci/out/apks/
cp build/app/outputs/apk/androidTest/debug/app-debug-androidTest.apk .ci/out/apks/
python .ci/receipt.py
