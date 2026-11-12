#!/usr/bin/env bash
# Builds DumpSource2 (ValveResourceFormat/DumpSource2, GPL-3.0), the tool GameTracking-CS2
# makes its DumpSource2/ folder with: it loads the game's modules offline, without a server,
# and writes every convar and command (flags, default, range, help), the interfaces, the
# logging channels, the networked classes and the entities. source2_dump.py runs it on each
# build's Linux binaries.
#
#   tools/build_dumpsource2.sh [<dir>]    default: $DUMPSOURCE2_DIR or ~/tools/DumpSource2
#
# Pinned to one commit so a dump never changes because the tool did. Running the binary also
# needs libva2 and libvdpau1 on the host, which libclient.so links against.

set -euo pipefail

REPO=https://github.com/ValveResourceFormat/DumpSource2
COMMIT=30068204a2a2b37e510ca8c4867d6cbaf4e5c410
DIR="${1:-${DUMPSOURCE2_DIR:-$HOME/tools/DumpSource2}}"

if [[ ! -d "$DIR/.git" ]]; then
	git clone -q "$REPO" "$DIR"
fi
git -C "$DIR" fetch -q origin "$COMMIT" 2>/dev/null || git -C "$DIR" fetch -q origin
git -C "$DIR" checkout -q "$COMMIT"
git -C "$DIR" submodule update -q --init --recursive --depth 1

cmake -S "$DIR" -B "$DIR/build" -DCMAKE_BUILD_TYPE=Release \
	-DCMAKE_C_COMPILER="${CC:-clang-20}" -DCMAKE_CXX_COMPILER="${CXX:-clang++-20}" > /dev/null
cmake --build "$DIR/build" --target DumpSource2-CS2 -j"$(nproc)" > /dev/null
echo "$DIR/build/DumpSource2-CS2"
