# CLAUDE.md

## Project
- Windows app (Python 3, `src/routerkit`, PowerShell scripts in `scripts/`): restarts a GX GPON router
  (firmware E4222-3.0.5-R) on a schedule via its web UI, with a countdown window, watchdog and dashboard.
  Version lives in `src/routerkit/__init__.py` and `CHANGELOG.md`.
- Android companion app in `android/` (Java, no libraries, Gradle: AGP 9.4.1, wrapper 9.8.2,
  compileSdk/targetSdk 34, minSdk 26, applicationId `com.sunny.routerwatch`). Alerts when the router is
  reachable but the internet is down; can reboot the router. Guide: `docs/android.md`.

## Build and test
- Windows app: `py -m unittest discover -s tests`
- Android logic: "Tests" in `docs/android.md` (javac, then `py android\tests\run_tests.py <classes dir> src\routerkit\routers\gx_gpon.py`)
- Android build: `android\gradlew.bat -p android assembleRelease lintRelease`
- Signing key: `android/keystore/routerwatch.p12` plus `password.txt` (git-ignored). Every release must be
  signed with it. Certificate SHA-256:
  `37c5c61612e487f5f0f8a070ed76c14e2b4a23ec9dbae43261eb5bae5ce4a8b8` (check with `apksigner verify --print-certs`).

## Releases
GitHub releases tagged `vX.Y.Z`, with the signed APK attached as `router-auto-restart-X.Y.Z.apk`. Release
notes include the APK SHA-256 and the signing certificate SHA-256.

## Rules
- Never commit, print, log or upload anything from a keystore folder. Before committing, confirm
  `git check-ignore android/keystore/routerwatch.p12` reports it as ignored.
- Docs use documentation addresses (192.0.2.1): no personal data, no secrets in files or command lines.
- Update `CHANGELOG.md` for every user-visible change.
- Commit, push to main and release only when all tests pass and the Android build and lint succeed.
  Never force-push or rewrite history. Report the commit/release link after each push or release.
- Ask first before accepting license agreements, installing software, anything needing admin rights,
  or deleting files outside build output.
