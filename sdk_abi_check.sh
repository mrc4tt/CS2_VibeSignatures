#!/usr/bin/env bash
#
# sdk_abi_check.sh - check the hl2sdk fork's headers against a gamever's binaries.
#
# Moves the hl2sdk_cs2 submodule to the fork's cs2 head (mrc4tt/hl2sdk), runs the
# cpp_tests battery (run_cpp_tests.py: clang vtable/record layouts of the SDK headers
# against bin_artifacts/<gamever>) and compares the mismatches with
# cpp_tests/abi_baseline.txt. The tests run are cpp_tests/fork_tests.yaml, not the
# config's own cpp_tests: block, which upstream configs keep on the old header layout.
#
# The baseline holds the mismatches already looked at: mostly the SDK and the finder
# YAMLs naming the same slot differently. A NEW mismatch is what a game update that
# inserted or removed a virtual looks like - on 1.41.9.2 IVEngineServer2 gained
# IsSpawnGroupLoadedForClient and seven slots after it moved - and is the signal to
# fix the header in the fork (see hl2sdk's AGENTS.md "Verifying"), not to wait for
# alliedmodders/s2sdk.
#
# Usage:
#   ./sdk_abi_check.sh                 newest configs/<gamever>.yaml, fork head
#   ./sdk_abi_check.sh 14192
#   ./sdk_abi_check.sh 14192 --accept  take the current mismatches as the baseline
#   ./sdk_abi_check.sh --no-update     test the submodule as it is checked out
#   SDK_REF=<commit> ./sdk_abi_check.sh   test that fork commit instead of the head
#
# Exit: 0 nothing new, 1 new mismatches, 2 compile failures or no usable setup.

set -uo pipefail
cd "$(dirname "$0")"

GAMEVER=""
ACCEPT=0
UPDATE=1
for arg in "$@"; do
    case "$arg" in
        --accept) ACCEPT=1 ;;
        --no-update) UPDATE=0 ;;
        -h|--help) sed -n '3,25p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        -*) echo "unknown option $arg" >&2; exit 2 ;;
        *) GAMEVER="$arg" ;;
    esac
done
[ -n "$GAMEVER" ] || GAMEVER=$(ls configs/*.yaml | sed 's|configs/||; s|\.yaml$||' | sort -V | tail -1)

CONFIG="configs/$GAMEVER.yaml"
SNAPSHOT="gamesymbols/$GAMEVER.yaml"
BASELINE="cpp_tests/abi_baseline.txt"
FORK_TESTS="cpp_tests/fork_tests.yaml"
SDK_REMOTE="https://github.com/mrc4tt/hl2sdk"
SDK_BRANCH="cs2"
for f in "$CONFIG" "$SNAPSHOT"; do
    [ -f "$f" ] || { echo "missing $f" >&2; exit 2; }
done

# xwin's MSVC STL refuses clang older than 19
CLANG=""
for c in $(compgen -c clang++- | grep -E '^clang\+\+-[0-9]+$' | sort -t- -k2 -n -r) clang++; do
    v=$("$c" -dumpversion 2>/dev/null | cut -d. -f1) || continue
    if [ "${v:-0}" -ge 19 ]; then CLANG="$c"; break; fi
done
[ -n "$CLANG" ] || { echo "no clang++ 19 or newer found" >&2; exit 2; }

if [ "$UPDATE" = 1 ]; then
    git -C hl2sdk_cs2 remote set-url origin "$SDK_REMOTE"
    if [ -n "${SDK_REF:-}" ]; then
        git -C hl2sdk_cs2 fetch -q origin "$SDK_BRANCH" && git -C hl2sdk_cs2 checkout -q "$SDK_REF"
    else
        git -C hl2sdk_cs2 fetch -q origin "$SDK_BRANCH" && git -C hl2sdk_cs2 checkout -q FETCH_HEAD
    fi || { echo "could not move hl2sdk_cs2 to ${SDK_REF:-origin/$SDK_BRANCH}" >&2; exit 2; }
fi
SDK_HEAD=$(git -C hl2sdk_cs2 log -1 --format='%h %s')

# The client tests (CNetworkGameClient*, IVEngineClient2) read Wend4r/sourcesdk, since
# hl2sdk carries no client interfaces. It stays on its pinned commit: unlike the fork,
# a move there is somebody else's change, so it is a submodule bump, not a check run.
if [ ! -f Wend4r_sourcesdk/public/iclient.h ]; then
    git submodule update --init --depth 1 Wend4r_sourcesdk \
        || { echo "could not check out the Wend4r_sourcesdk submodule" >&2; exit 2; }
fi

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

# Headers that hold a protobuf message by value (networkgameserverbase.h through
# gamesessionconfiguration.h) need the generated .pb.h; build them with the SDK's own
# protoc so they match its protobuf headers
rm -rf cpp_tests/protos && mkdir -p cpp_tests/protos
hl2sdk_cs2/devtools/bin/linux/protoc -Ihl2sdk_cs2/common -Ihl2sdk_cs2/thirdparty/protobuf-3.21.8/src \
    --cpp_out=cpp_tests/protos hl2sdk_cs2/common/*.proto > "$tmp/protoc.log" 2>&1 \
    || { echo "could not generate the hl2sdk_cs2 protos:" >&2; cat "$tmp/protoc.log" >&2; exit 2; }

# clang takes the newest GCC under /usr/lib/gcc even when only an older one has its
# libstdc++ headers installed (Ubuntu 24.04: gcc 14 without libstdc++-14-dev). Point
# the linux tests at the newest GCC that has them, when the default finds none.
GCC_DIR=""
if ! echo '#include <cstdlib>' | "$CLANG" -x c++ -fsyntax-only --target=x86_64-pc-linux-gnu - 2> /dev/null; then
    for d in $(ls -d /usr/lib/gcc/x86_64-linux-gnu/* 2> /dev/null | sort -V -r); do
        if [ -d "/usr/include/c++/$(basename "$d")" ] || [ -d "/usr/include/x86_64-linux-gnu/c++/$(basename "$d")" ]; then
            GCC_DIR="$d"
            break
        fi
    done
fi

# The config with its cpp_tests: block (always the last top-level key) swapped for the
# fork's own list
{
    sed '/^cpp_tests:/,$d' "$CONFIG"
    grep -v '^#' "$FORK_TESTS" | awk -v gcc="$GCC_DIR" '
        /- name:/ { linux = 0 }
        /target: x86_64-[^ ]*-linux-gnu/ { linux = 1 }
        { print }
        linux && gcc != "" && /additional_compiler_options:/ {
            indent = $0; sub(/[^ ].*/, "", indent)
            print indent "  - --gcc-install-dir=" gcc
        }'
} > "$tmp/config.yaml"

uv run run_cpp_tests.py -gamever "$GAMEVER" -snapshot "$SNAPSHOT" -configyaml "$tmp/config.yaml" \
    -clang "$CLANG" > "$tmp/run.log" 2>&1

failures=$(grep -oP '^Compile failures: \K\d+' "$tmp/run.log" || echo "?")
if [ "$failures" != "0" ]; then
    echo "sdk abi $GAMEVER: $failures compile failure(s) on hl2sdk $SDK_HEAD"
    grep -E '^\[FAIL\]| error: ' "$tmp/run.log" | sed "s|$PWD/||" | head -20
    exit 2
fi

# "<test> | <difference>" for every vtable slot or record member difference, under the
# test it belongs to. "Reference index ..." lines repeat the "Index ..." ones per YAML.
awk '
    /^\[(PASS|FAIL|RUN )\] / { name = $2; sub(/:$/, "", name) }
    /^  - / && !/^  - Reference index / { sub(/^  - /, ""); print name " | " $0 }
' "$tmp/run.log" | sort -u > "$tmp/current.txt"

if [ "$ACCEPT" = 1 ]; then
    {
        echo "# Accepted cpp_tests mismatches (sdk_abi_check.sh --accept)."
        echo "# gamever $GAMEVER, hl2sdk $SDK_HEAD"
        cat "$tmp/current.txt"
    } > "$BASELINE"
    echo "sdk abi $GAMEVER: baseline written, $(wc -l < "$tmp/current.txt") accepted mismatch(es)"
    exit 0
fi

touch "$BASELINE"
grep -v '^#' "$BASELINE" | sort -u > "$tmp/baseline.txt"
comm -23 "$tmp/current.txt" "$tmp/baseline.txt" > "$tmp/new.txt"
comm -13 "$tmp/current.txt" "$tmp/baseline.txt" > "$tmp/gone.txt"

echo "sdk abi $GAMEVER on hl2sdk $SDK_HEAD: $(wc -l < "$tmp/new.txt") new, $(wc -l < "$tmp/gone.txt") gone, $(wc -l < "$tmp/baseline.txt") accepted"
if [ -s "$tmp/gone.txt" ]; then
    echo "no longer mismatching (run --accept once the header change is in):"
    sed 's/^/  /' "$tmp/gone.txt"
fi
if [ -s "$tmp/new.txt" ]; then
    echo "NEW mismatches - a slot moved or a layout changed; fix the header in hl2sdk:"
    sed 's/^/  /' "$tmp/new.txt"
    exit 1
fi
exit 0
