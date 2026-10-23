#!/usr/bin/env bash
set -euo pipefail
# Hosted workers only. Never remove tools or alter SDKs on a developer machine.
test "${GITHUB_ACTIONS:-}" = true
test "${RUNNER_ENVIRONMENT:-}" = github-hosted
test "${RUNNER_OS:-}" = Linux
sudo rm -rf /usr/share/dotnet /opt/ghc /usr/local/lib/android/sdk/ndk
df -h "$GITHUB_WORKSPACE"
flutter_dir="$RUNNER_TEMP/flutter"
git init --quiet "$flutter_dir"
git -C "$flutter_dir" remote add origin https://github.com/flutter/flutter.git
git -C "$flutter_dir" fetch --quiet --depth 1 origin f6ff1529fd6d8af5f706051d9251ac9231c83407
git -C "$flutter_dir" checkout --quiet --detach FETCH_HEAD
echo "$flutter_dir/bin" >> "$GITHUB_PATH"
export PATH="$flutter_dir/bin:$PATH"
flutter config --no-analytics
flutter --version
yes | sdkmanager --licenses >/dev/null || true
sdkmanager 'platforms;android-36' 'build-tools;36.0.0' 'platform-tools'
python3 -m venv "$RUNNER_TEMP/quran-ci-venv"
"$RUNNER_TEMP/quran-ci-venv/bin/pip" --disable-pip-version-check install -r .ci/requirements.txt
echo "$RUNNER_TEMP/quran-ci-venv/bin" >> "$GITHUB_PATH"
