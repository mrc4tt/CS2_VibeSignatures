#!/usr/bin/env bash
#
# runtime_smoke.sh - run CS2SDKTest inside a live CS2 dedicated server.
#
# Where sdk_abi_check.sh compares header layouts with the binaries, this loads
# the hl2sdk fork into the running game: CS2SDKTest (zqunagi/CS2SDKTest, pinned
# below, with runtime/cs2sdktest/patches/ applied) is built against hl2sdk_cs2 and
# the newest mrc4tt/metamod-source release, then calls every interface it covers
# under a fault guard and checks our CounterStrikeSharp gamedata for the gamever
# against the live server. Outcomes are compared with runtime/cs2sdktest/baseline.txt.
#
# The server is a slim Linux install in $CST_HOME/server (about 11G instead of 73G):
# runtime/cs2sdktest/slim.txt plus the pak01 archives the build turns out to need.
# A boot that dies on a missing archive adds it to $CST_HOME/slim_archives.txt,
# downloads it and boots again. Needs DepotDownloader, curl, jq, cmake, clang and
# ~/.steam/sdk64/steamclient.so.
#
# Usage:
#   ./runtime_smoke.sh                 newest configs/<gamever>.yaml
#   ./runtime_smoke.sh 14192
#   ./runtime_smoke.sh 14192 --accept  take the outcomes of this run as the baseline
#   ./runtime_smoke.sh --no-update     no depot download, release fetch or source update
#   CST_HOME=<dir> SDK_DIR=<hl2sdk checkout> ./runtime_smoke.sh
#
# Exit: 0 nothing new, 1 regressions or a run that crashed, 2 no usable setup or build.

set -uo pipefail
cd "$(dirname "$0")"

CST_REPO="https://github.com/zqunagi/CS2SDKTest"
CST_COMMIT="1860617474ac6206534920b0fe8df42accf440c7"
MMS_REPO="mrc4tt/metamod-source"

GAMEVER=""
ACCEPT=0
UPDATE=1
for arg in "$@"; do
    case "$arg" in
        --accept) ACCEPT=1 ;;
        --no-update) UPDATE=0 ;;
        -h|--help) sed -n '3,26p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        -*) echo "unknown option $arg" >&2; exit 2 ;;
        *) GAMEVER="$arg" ;;
    esac
done
[ -n "$GAMEVER" ] || GAMEVER=$(ls configs/*.yaml | sed 's|configs/||; s|\.yaml$||' | sort -V | tail -1)

fail() { echo "$*" >&2; exit 2; }

RUNTIME="$PWD/runtime/cs2sdktest"
BASELINE="$RUNTIME/baseline.txt"
CSS_JSON="$PWD/gamedata/$GAMEVER/CounterStrikeSharp/config/addons/counterstrikesharp/gamedata/gamedata.json"
CST_HOME="${CST_HOME:-$HOME/cs2test}"
SDK_DIR=$(realpath "${SDK_DIR:-hl2sdk_cs2}")
SERVER="$CST_HOME/server"
GAME="$SERVER/game"
CSGO="$GAME/csgo"
SRC="$CST_HOME/src"
LOGS="$CST_HOME/logs"
RESULTS="$CST_HOME/results"

for tool in DepotDownloader curl jq cmake make clang++ git python3; do
    command -v "$tool" > /dev/null || fail "$tool not found"
done
[ -f "$HOME/.steam/sdk64/steamclient.so" ] || fail "missing ~/.steam/sdk64/steamclient.so (copy it from steamcmd's linux64/)"
[ -f "$SDK_DIR/public/tier0/platform.h" ] || fail "no hl2sdk checkout at $SDK_DIR"
mkdir -p "$SRC" "$LOGS"
touch "$CST_HOME/slim_archives.txt"

depot_update() {
    cat "$RUNTIME/slim.txt" "$CST_HOME/slim_archives.txt" > "$CST_HOME/slim.txt"
    DepotDownloader -app 730 -os linux -filelist "$CST_HOME/slim.txt" -dir "$SERVER" -max-downloads 16 \
        > "$LOGS/depot.log" 2>&1 || fail "depot download failed, see $LOGS/depot.log"
    chmod +x "$GAME/cs2.sh" "$GAME/bin/linuxsteamrt64/cs2"
}

# 1. Server
[ "$UPDATE" = 1 ] && depot_update
[ -f "$CSGO/steam.inf" ] || fail "no server in $SERVER, run without --no-update"
PATCH=$(sed -n 's/^PatchVersion=//p' "$CSGO/steam.inf" | tr -d '.\r')
[ "$PATCH" = "${GAMEVER%%[a-z]*}" ] || fail "server is $PATCH but gamever is $GAMEVER"

# 2. Metamod from the newest fork release, loaded through gameinfo.gi
if [ "$UPDATE" = 1 ]; then
    release=$(curl -fsSL "https://api.github.com/repos/$MMS_REPO/releases/latest") || fail "no $MMS_REPO release"
    MMS_TAG=$(jq -r .tag_name <<< "$release")
    MMS_URL=$(jq -r '.assets[].browser_download_url | select(endswith("-linux.tar.gz"))' <<< "$release")
    [ -n "$MMS_URL" ] || fail "$MMS_REPO $MMS_TAG has no linux build"
    if [ "$(cat "$CST_HOME/metamod.tag" 2>/dev/null)" != "$MMS_TAG" ]; then
        curl -fsSL "$MMS_URL" | tar -xz -C "$CSGO" || fail "could not install metamod $MMS_TAG"
        echo "$MMS_TAG" > "$CST_HOME/metamod.tag"
    fi
fi
MMS_TAG=$(cat "$CST_HOME/metamod.tag" 2>/dev/null) || fail "metamod not installed, run without --no-update"
if ! grep -q 'csgo/addons/metamod' "$CSGO/gameinfo.gi"; then
    awk '/Game_LowViolence/ && !done { print "\t\t\tGame\tcsgo/addons/metamod\r"; done = 1 } { print }' \
        "$CSGO/gameinfo.gi" > "$CSGO/gameinfo.gi.new" && mv "$CSGO/gameinfo.gi.new" "$CSGO/gameinfo.gi"
fi

# 3. Sources: metamod-source at the release tag, CS2SDKTest at the pin plus our patches
if [ "$UPDATE" = 1 ]; then
    [ -d "$SRC/metamod-source" ] || git clone -q "https://github.com/$MMS_REPO" "$SRC/metamod-source"
    git -C "$SRC/metamod-source" fetch -q --tags origin \
        && git -C "$SRC/metamod-source" checkout -q "$MMS_TAG" \
        && git -C "$SRC/metamod-source" submodule update -q --init --recursive \
        || fail "could not check out metamod-source $MMS_TAG"
    [ -d "$SRC/CS2SDKTest" ] || git clone -q "$CST_REPO" "$SRC/CS2SDKTest"
    git -C "$SRC/CS2SDKTest" fetch -q origin "$CST_COMMIT" || fail "could not fetch CS2SDKTest $CST_COMMIT"
fi
git -C "$SRC/CS2SDKTest" checkout -q --force "$CST_COMMIT" && git -C "$SRC/CS2SDKTest" clean -fdq \
    || fail "could not check out CS2SDKTest $CST_COMMIT"
for p in "$RUNTIME"/patches/*.patch; do
    [ -e "$p" ] || continue
    git -C "$SRC/CS2SDKTest" apply "$p" || fail "patch $(basename "$p") does not apply"
done

# 4. Build and install the plugin with this gamever's gamedata
BUILD="$SRC/CS2SDKTest/build/linux-x64-make-release"
(cd "$SRC/CS2SDKTest" && cmake --preset linux-x64-make-release \
    -DCS2SDKTEST_S2SDK_DIR="$SDK_DIR" -DCS2SDKTEST_METAMOD_DIR="$SRC/metamod-source") > "$LOGS/cmake.log" 2>&1 \
    || fail "cmake failed, see $LOGS/cmake.log"
cmake --build "$BUILD" -j "$(nproc)" > "$LOGS/build.log" 2>&1 || {
    grep -E 'error:' "$LOGS/build.log" | head -20 >&2
    fail "build failed against $(git -C "$SDK_DIR" log -1 --format='%h %s'), see $LOGS/build.log"
}
rm -rf "$CSGO/addons/cs2sdktest"
cp -r "$BUILD/package/addons/." "$CSGO/addons/"
if [ -f "$CSS_JSON" ]; then
    python3 -I cs2sdktest_runtime.py gamedata "$CSS_JSON" "$SRC/CS2SDKTest/configs/gamedata.toml" \
        "$CSGO/addons/cs2sdktest/configs/gamedata.toml" > "$LOGS/gamedata.log" || fail "gamedata conversion failed"
    echo "gamedata: $(grep -c ' -> ' "$LOGS/gamedata.log") values differ from upstream, see $LOGS/gamedata.log"
else
    echo "no CSS gamedata for $GAMEVER, testing upstream's gamedata.toml"
fi

# 5. Run; a boot that dies on a missing pak01 archive downloads it and boots again
echo "running CS2SDKTest: server $PATCH, metamod $MMS_TAG, sdk $(git -C "$SDK_DIR" log -1 --format='%h %s')"
for _ in $(seq 1 100); do
    rm -rf "$RESULTS" && mkdir -p "$RESULTS"
    (cd "$GAME" && ulimit -c 0 && CST_AUTORUN=1 CST_RESULT_DIR="$RESULTS" timeout "${CST_TIMEOUT:-300}" \
        ./cs2.sh -dedicated -insecure +ip 127.0.0.1 -port 27099 +game_type 0 +game_mode 1 +map de_dust2 \
        +bot_quota 1 +sv_hibernate_when_empty 0 +mp_warmup_pausetimer 1 +mp_freezetime 0) > "$LOGS/server.log" 2>&1
    missing=$(grep -oE 'packed store "[^"]+/pak01_[0-9]+\.vpk"' "$LOGS/server.log" | head -1 \
        | sed -E 's|.*/game/(.+/pak01_[0-9]+)\.vpk"|\1|')
    [ -n "$missing" ] || break
    [ "$UPDATE" = 1 ] || fail "server needs game/$missing.vpk, run without --no-update"
    echo "server needs game/$missing.vpk, downloading it"
    echo "regex:^game/$missing\\.vpk\$" >> "$CST_HOME/slim_archives.txt"
    depot_update
done

ARGS=("$RESULTS" "$BASELINE")
[ "$ACCEPT" = 1 ] && ARGS+=(--accept)
python3 -I cs2sdktest_runtime.py compare "${ARGS[@]}"
