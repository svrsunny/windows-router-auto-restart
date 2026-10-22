#!/usr/bin/env bash
# Build the Android companion app (router-auto-restart.apk) without Gradle or Android Studio.
# See docs/android.md for the toolchain.
#
# Toolchain (TC dir):
#   jdk/                 JDK 17 (Temurin)
#   sdk/android-34.jar   Android API 34 jar (compile + resource linking)
#   sdk/aapt2            aapt2 2.20 (resource compiler / linker)
#   out/dx               dx 1.16 compiled from AOSP source (platform/dalvik, android11-release)
#   out/apksig           apksigner 0.9 compiled from AOSP apksig source
# usage: build.sh <TC dir> <work dir>
#
# Signing key: keystore/routerwatch.p12 with its password in keystore/password.txt (both git-ignored).
# If neither exists, a new key and a random password are created. RW_KS_PASS overrides the file.
# Keep both: Android only installs an update that is signed with the same key.
set -euo pipefail
TC=$1; WORK=$2
HERE=$(cd "$(dirname "$0")/.." && pwd)          # the android/ folder
APP=$HERE/app
JAR=$TC/sdk/android-34.jar
JDK=$TC/jdk
JAVAC=("$JDK/bin/javac")
JAVA="$JDK/bin/java"
KS=$HERE/keystore/routerwatch.p12
KS_PASS_FILE=$HERE/keystore/password.txt
unset JAVA_TOOL_OPTIONS || true

rm -rf "$WORK"; mkdir -p "$WORK"/{flat,gen,classes}

echo "== aapt2 compile + link"
"$TC/sdk/aapt2" compile --dir "$APP/res" -o "$WORK/flat"
"$TC/sdk/aapt2" link -I "$JAR" --manifest "$APP/AndroidManifest.xml" \
    -o "$WORK/base.apk" --java "$WORK/gen" "$WORK"/flat/*.flat

echo "== javac"
find "$APP/src" "$WORK/gen" -name '*.java' > "$WORK/srcs.txt"
"${JAVAC[@]}" -source 8 -target 8 -bootclasspath "$JAR" -encoding UTF-8 -Xlint:-options \
    -d "$WORK/classes" @"$WORK/srcs.txt"

echo "== dx"
"$JAVA" -cp "$TC/out/dx" com.android.dx.command.Main --dex --min-sdk-version=26 \
    --output="$WORK/classes.dex" "$WORK/classes"

echo "== package"
python3 - "$WORK/base.apk" "$WORK/classes.dex" "$WORK/unsigned.apk" <<'PY'
# copy aapt2's output, add classes.dex, and 4-byte-align every uncompressed entry (Android 11+ refuses
# to install a targetSdk 30+ APK whose resources.arsc isn't stored and aligned). Alignment padding uses
# the same extra field (0xd935) as apksig/zipalign, so the signer keeps it.
import struct, sys, zipfile
src, dex, dst = sys.argv[1:]
with zipfile.ZipFile(src) as zi, zipfile.ZipFile(dst, "w") as zo:
    items = [(i, zi.read(i.filename)) for i in zi.infolist()]
    d = zipfile.ZipInfo("classes.dex", date_time=items[0][0].date_time)
    d.compress_type = zipfile.ZIP_DEFLATED
    items.append((d, open(dex, "rb").read()))
    for info, data in items:
        info.extra = b""
        if info.compress_type == zipfile.ZIP_STORED:
            base = zo.fp.tell() + 30 + len(info.filename.encode("utf-8"))
            pad = (-(base + 6)) % 4
            info.extra = struct.pack("<HHH", 0xD935, 2 + pad, 4) + b"\0" * pad
        zo.writestr(info, data, compress_type=info.compress_type)
PY

echo "== sign"
mkdir -p "$(dirname "$KS")"
if [ -n "${RW_KS_PASS:-}" ]; then
    KS_PASS=$RW_KS_PASS
elif [ -f "$KS_PASS_FILE" ]; then
    KS_PASS=$(tr -d '\r\n' < "$KS_PASS_FILE")
elif [ ! -f "$KS" ]; then
    KS_PASS=$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')
    printf '%s\n' "$KS_PASS" > "$KS_PASS_FILE"
    chmod 600 "$KS_PASS_FILE" 2>/dev/null || true
else
    echo "keystore exists but no password: put it in $KS_PASS_FILE or set RW_KS_PASS" >&2
    exit 1
fi
export RW_KS_PASS_INTERNAL=$KS_PASS        # handed to keytool/apksigner by name, never on a command line
if [ ! -f "$KS" ]; then
    "$JDK/bin/keytool" -genkeypair -keystore "$KS" -storetype PKCS12 \
        -storepass:env RW_KS_PASS_INTERNAL -keypass:env RW_KS_PASS_INTERNAL \
        -alias routerwatch -keyalg RSA -keysize 2048 -validity 10000 -dname "CN=Router Auto Restart" >/dev/null
    echo "created a new signing key in $KS (back it up together with $KS_PASS_FILE)"
fi
"$JAVA" -cp "$TC/out/apksig" com.android.apksigner.ApkSignerTool sign \
    --ks "$KS" --ks-type PKCS12 --ks-pass env:RW_KS_PASS_INTERNAL --ks-key-alias routerwatch \
    --min-sdk-version 26 --out "$WORK/router-auto-restart.apk" "$WORK/unsigned.apk"
"$JAVA" -cp "$TC/out/apksig" com.android.apksigner.ApkSignerTool verify --verbose --print-certs \
    "$WORK/router-auto-restart.apk"
python3 - "$WORK/router-auto-restart.apk" <<'PY'
import struct, sys, zipfile
apk = sys.argv[1]
bad = []
with zipfile.ZipFile(apk) as z, open(apk, "rb") as f:
    for i in z.infolist():
        f.seek(i.header_offset + 26)
        n, m = struct.unpack("<HH", f.read(4))
        if i.compress_type == zipfile.ZIP_STORED and (i.header_offset + 30 + n + m) % 4:
            bad.append(i.filename)
    names = [i.filename for i in z.infolist()]
    arsc = z.getinfo("resources.arsc")
assert not bad, "unaligned stored entries: %s" % bad
assert arsc.compress_type == zipfile.ZIP_STORED, "resources.arsc must be stored"
print("alignment OK (%d entries, resources.arsc stored + 4-byte aligned)" % len(names))
PY
echo "built $WORK/router-auto-restart.apk"
