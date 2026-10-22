#!/usr/bin/env bash
# Download and prepare the toolchain that tools/build.sh uses (Linux x86-64; needs bash, curl,
# python3, tar). Everything is pinned to a version, commit or SHA-256. Safe to re-run: finished
# steps are skipped, so an interrupted run can simply be started again.
#
#   jdk/                Temurin JDK 17 (Adoptium release, SHA-256 checked)
#   sdk/android-34.jar  Android 34 API jar from Reginer/aosp-android-jar (pinned commit, SHA-256
#                       checked). Used only to compile against and to link resources; nothing from
#                       it is packaged into the APK.
#   sdk/aapt2           aapt2 2.20 Linux binary from the npm package aaptjs3 2.0.2 (SHA-256 checked)
#   out/dx              dx 1.16, compiled here from AOSP source (aosp-mirror/platform_dalvik)
#   out/apksig          apksigner, compiled here from AOSP apksig source (venshine/apksig mirror)
#
# usage: fetch_toolchain.sh <TC dir>
set -euo pipefail
TC=$1
mkdir -p "$TC/sdk" "$TC/out" "$TC/src"
cd "$TC"
unset JAVA_TOOL_OPTIONS || true

JDK_URL="https://github.com/adoptium/temurin17-binaries/releases/download/jdk-17.0.20.1%2B1/OpenJDK17U-jdk_x64_linux_hotspot_17.0.20.1_1.tar.gz"
JDK_SHA=3808d1d15e3ec6bd5b84057fb5d84c33d8a1536a258146bcea2e603fc726e08e
JAR_URL="https://raw.githubusercontent.com/Reginer/aosp-android-jar/262f6ae931160011572a5adfe4ec6302585e8f60/android-34/android.jar"
JAR_SHA=d6b3248f33ca93606a4581fa7c678231dd6e3e69f3b7062c8da5ed2c49bdf396
AAPT_URL="https://registry.npmjs.org/aaptjs3/-/aaptjs3-2.0.2.tgz"
AAPT_SHA=26031bd1acb577edce91675ae92daf63cf85795d4e2399333edeb994dd9197e9
AAPT2_SHA=e4dff6060827a3e401bce376e47916f2f93a89602af54973ffd3fdfc2528be3f
DALVIK=aosp-mirror/platform_dalvik@06f521f22319b3ba697e31594b005320fd4c0f06
APKSIG=venshine/apksig@c0314349dc9f9ccaf9300a39b592af478dc497e9

fetch() {   # url out sha256
    if [ -f "$2" ] && echo "$3  $2" | sha256sum -c --status; then return 0; fi
    echo "downloading $(basename "$2")"
    curl -fsSL --retry 3 -o "$2.part" "$1"
    echo "$3  $2.part" | sha256sum -c --status || { echo "SHA-256 mismatch for $1" >&2; rm -f "$2.part"; exit 1; }
    mv "$2.part" "$2"
}

# --- JDK ---
if [ ! -x jdk/bin/javac ]; then
    fetch "$JDK_URL" jdk17.tar.gz "$JDK_SHA"
    rm -rf jdk && mkdir jdk && tar xzf jdk17.tar.gz -C jdk --strip-components=1
fi
JAVAC=$TC/jdk/bin/javac

# --- android.jar and aapt2 ---
fetch "$JAR_URL" sdk/android-34.jar "$JAR_SHA"
if [ ! -x sdk/aapt2 ] || ! echo "$AAPT2_SHA  sdk/aapt2" | sha256sum -c --status; then
    fetch "$AAPT_URL" sdk/aaptjs3.tgz "$AAPT_SHA"
    rm -rf sdk/aaptjs3 && mkdir sdk/aaptjs3 && tar xzf sdk/aaptjs3.tgz -C sdk/aaptjs3
    cp sdk/aaptjs3/package/bin/x64/linux/aapt2 sdk/aapt2 && chmod +x sdk/aapt2
    echo "$AAPT2_SHA  sdk/aapt2" | sha256sum -c --status || { echo "aapt2 SHA-256 mismatch" >&2; exit 1; }
fi

# --- AOSP sources: list the files of a pinned commit, download them, compile ---
get_sources() {   # owner/repo@commit dest-dir python-filter-expression strip-prefix
    local repo=${1%@*} commit=${1#*@} dest=$2
    if [ -f "$dest/.complete" ]; then return 0; fi
    echo "downloading sources of $repo"
    mkdir -p "$dest"
    curl -fsSL --retry 3 "https://api.github.com/repos/$repo/git/trees/$commit?recursive=1" -o "$dest/tree.json"
    python3 - "$dest/tree.json" "$3" "$4" > "$dest/list.txt" <<'PY'
import json, sys
tree = json.load(open(sys.argv[1]))
assert not tree["truncated"], "file list truncated"
for t in tree["tree"]:
    p = t["path"]
    if t["type"] == "blob" and eval(sys.argv[2]):
        print(p)
PY
    while read -r p; do
        printf '%s\n%s\n' "https://raw.githubusercontent.com/$repo/$commit/$p" "$dest/${p#$4}"
    done < "$dest/list.txt" | xargs -d '\n' -n 2 -P 16 sh -c \
        'mkdir -p "$(dirname "$2")" && { [ -s "$2" ] || curl -fsSL --retry 3 -o "$2" "$1"; }' _
    local want got
    want=$(wc -l < "$dest/list.txt")
    got=$(find "$dest" -name '*.java' -size +0 | wc -l)
    [ "$want" = "$got" ] || { echo "only $got of $want source files downloaded; run again" >&2; exit 1; }
    touch "$dest/.complete"
}

if [ ! -f out/dx/com/android/dx/command/Main.class ]; then
    get_sources "$DALVIK" src/dx "p.startswith('dx/src/') and p.endswith('.java')" "dx/src/"
    find src/dx -name '*.java' > src/dx.srcs
    rm -rf out/dx && mkdir -p out/dx
    "$JAVAC" -nowarn -encoding UTF-8 -d out/dx @src/dx.srcs 2>&1 | grep -v '^Note:' || true
    [ -f out/dx/com/android/dx/command/Main.class ] || { echo "dx failed to compile" >&2; exit 1; }
fi

if [ ! -f out/apksig/com/android/apksigner/ApkSignerTool.class ]; then
    get_sources "$APKSIG" src/apksig "p.endswith('.java') and '/test' not in p.lower()" ""
    # the AOSP build adds the native Conscrypt provider; the JDK's own providers cover RSA signing
    sed -i 's#Security.addProvider(new org.conscrypt.OpenSSLProvider());#if (false) throw new UnsatisfiedLinkError(); /* no conscrypt */#' \
        src/apksig/src/apksigner/java/com/android/apksigner/ApkSignerTool.java
    find src/apksig -name '*.java' > src/apksig.srcs
    rm -rf out/apksig && mkdir -p out/apksig
    "$JAVAC" -nowarn -encoding UTF-8 -d out/apksig @src/apksig.srcs 2>&1 | grep -v '^Note:' || true
    [ -f out/apksig/com/android/apksigner/ApkSignerTool.class ] || { echo "apksig failed to compile" >&2; exit 1; }
fi

echo "toolchain ready in $TC"
"$TC/jdk/bin/java" -cp out/dx com.android.dx.command.Main --version
echo "apksigner $("$TC/jdk/bin/java" -cp out/apksig com.android.apksigner.ApkSignerTool version)"
"$TC/sdk/aapt2" version
