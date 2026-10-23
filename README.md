# Quran

Work in progress: an offline Android 15+ Quran reader, with three Arabic tafsirs.
The current reader is still under reference review. A successful build does not
establish full visual or behavioral matching or completion of the planned app.

Implementation and independent review run locally through Sandcastle, using REA
and retained evidence first. GitHub Actions runs the expensive deterministic
checks on standard hosted Ubuntu runners: Flutter analysis/tests, complete
prepared-data checks, APK builds, native Android instrumentation and real emulator
accessibility navigation on API 35 and 36.

This repository starts with a clean source snapshot. Private repository history,
phone records, original APKs, credentials, signing keys and reference captures
are excluded. The required content/fonts/images are provided to trusted manual
jobs in an authenticated encrypted input pack, pinned by SHA-256. Generated APKs,
screenshots and detailed reports are encrypted before artifact upload. Only the
task-specific decryption key is stored as an Actions secret. Public pull requests
receive checks without private inputs or secrets.

Run **Android verification** from the Actions tab on `main`. Decrypt its result
artifact locally with `.ci/vault.py`; inspect the commit-bound receipt, logs and
device evidence. Artifacts expire after one day and no dependency or emulator
state cache is uploaded. The builds use disposable debug signing; final release
signing and owner comparison remain separate checkpoints.

The original-APK extraction tests require retained local reference artifacts and
are not run on hosted workers. The prepared-data and Android production-adapter
tests do run there. Human Arabic pronunciation, touch gestures and original-app
visual/behavioral comparison still require separate review.

Toolchains: Flutter 3.38.5 (pinned revision), Java 17, Android compile/target 36,
minimum API 35. No local Android Docker or real phone is required for hosted tests.

Standard hosted runner compute is free for public repositories. Larger runners
are not used. Artifact storage has separate limits; download and delete completed
encrypted artifacts promptly.
