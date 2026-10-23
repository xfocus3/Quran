#!/usr/bin/env bash
set -euo pipefail
sdk="${ANDROID_HOME:?}"
bt="$sdk/build-tools/36.0.0"
jar="$sdk/platforms/android-36/android.jar"
out=.ci/out/probe
# The helper is self-instrumenting and needs no app/owner signing identity.
key_dir="$(mktemp -d "${RUNNER_TEMP:?}/quran-probe.XXXXXX")"
trap 'rm -rf "$key_dir"' EXIT
keytool -genkeypair -noprompt -alias androiddebugkey -keyalg RSA -keysize 2048 \
  -validity 2 -dname "CN=Quran CI probe" -keystore "$key_dir/probe.keystore" \
  -storepass android -keypass android
mkdir -p "$out/classes" "$out/dex"
javac -source 17 -target 17 -cp "$jar" -d "$out/classes" .ci/probe/src/qa/*.java
"$bt/d8" --lib "$jar" --min-api 35 --output "$out/dex" "$out/classes/qa/"*.class
"$bt/aapt2" link -I "$jar" --manifest .ci/probe/AndroidManifest.xml -o "$out/unsigned.apk"
zip -q -j "$out/unsigned.apk" "$out/dex/classes.dex"
"$bt/zipalign" -f 4 "$out/unsigned.apk" "$out/aligned.apk"
"$bt/apksigner" sign --ks "$key_dir/probe.keystore" --ks-key-alias androiddebugkey --ks-pass pass:android --key-pass pass:android --out "$out/probe.apk" "$out/aligned.apk"
