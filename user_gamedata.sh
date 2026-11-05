#!/usr/bin/env bash
# Bring every stored user gamedata file (sig.miksen.me "keep it updated") up to date
# for one build. autopilot runs this after a build is finished; by hand:
#
#   ./user_gamedata.sh 14197            # update, write history, notify webhooks
#   ./user_gamedata.sh 14197 -dry-run   # report only
#   ./user_gamedata.sh 14197 -no-ida    # known values and relocation, no hunter
#
# Never fails the build that called it: a file that cannot be updated keeps its text
# and says why on its manage page. See user_gamedata.py for the proof each stage needs.
set -uo pipefail
cd "$(dirname "$0")"
VER="${1:?usage: user_gamedata.sh <gamever> [user_gamedata.py flags]}"
shift
ROOT="${CS2VIBE_USER_FILES:-/var/lib/cs2vibe-files}"
if [ ! -d "$ROOT/files" ] || [ -z "$(ls -A "$ROOT/files" 2>/dev/null)" ]; then
    echo "[user] no stored files in $ROOT"
    exit 0
fi
uv run user_gamedata.py -gamever "$VER" -root "$ROOT" "$@"
