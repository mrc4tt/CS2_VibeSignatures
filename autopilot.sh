#!/usr/bin/env bash
#
# autopilot.sh - take a new CS2 build through the whole pipeline unattended.
#
# Runs on the analysis box (the one with IDA, the depot binaries and the disk).
# Detection is a Steam query, so there is nothing inbound to expose: the machine
# asks, nobody tells it. One instance at a time, because run_linux.sh and
# run_windows.sh reap each other's idalib-mcp sessions (CLAUDE.md rule 10).
#
# The verification battery is a gate, not a report: anything red stops the chain
# before a single file reaches a plugin repo. Deploying is decided separately by
# autopilot_safe_gate.py, which holds any build that is more than a rebuild
# relocation.
#
# Usage:
#   ./autopilot.sh              # detect, and do nothing if there is no new build
#   ./autopilot.sh 14182        # force one specific tag
#   ./autopilot.sh -n           # dry run: detect and report, touch nothing
#
# Environment (read from .env by systemd, or exported by hand):
#   AUTOPILOT_DEPLOY=safe|auto|off   default safe
#   AUTOPILOT_NOTIFY_URL=...         optional outgoing webhook
#   DEPOTDOWNLOADER_STEAM_USERNAME / _PASSWORD
#   CS2VIBE_AGENT, CS2VIBE_LLM_APIKEY ...
set -uo pipefail
cd "$(dirname "$0")"
REPO="$PWD"

DEPLOY_MODE="${AUTOPILOT_DEPLOY:-safe}"
STATE="${AUTOPILOT_STATE:-$REPO/.autopilot}"
MIN_FREE_GB="${AUTOPILOT_MIN_FREE_GB:-40}"
MAX_ATTEMPTS="${AUTOPILOT_MAX_ATTEMPTS:-2}"
DRY=0
TAG=""
for arg in "$@"; do
    case "$arg" in
        -n|--dry-run) DRY=1 ;;
        *) TAG="$arg" ;;
    esac
done
mkdir -p "$STATE"

log() { printf '%s %s\n' "$(date -Is)" "$*"; }
die() { log "FAILED: $*"; notify "failed" "$*"; exit 1; }

notify() {  # notify <outcome> <text>
    [ -x ./autopilot_notify.sh ] || return 0
    ./autopilot_notify.sh "$1" "${TAG:-unknown}" "$2" || true
}

# ---------------------------------------------------------------- single instance
exec 9>"$STATE/lock"
if ! flock -n 9; then
    log "another autopilot run holds the lock; nothing to do"
    exit 0
fi

# ---------------------------------------------------------------- detect
if [ -z "$TAG" ]; then
    TAG=$(curl -sL --max-time 10 -A "Mozilla/5.0" \
        "https://api.steampowered.com/ISteamApps/UpToDateCheck/v1/?appid=730&version=0" |
        python3 -c "import sys,json;print(json.load(sys.stdin)['response']['required_version'])" 2>/dev/null || true)
fi
if ! [[ "$TAG" =~ ^[0-9]+[a-z]?$ ]]; then
    log "could not determine the current build from Steam; leaving it for the next tick"
    exit 0
fi
if [ -f "gamesymbols/$TAG.yaml" ]; then
    log "build $TAG is already analysed; nothing to do"
    exit 0
fi

# ---------------------------------------------------------------- backoff
ATTEMPTS_FILE="$STATE/attempts-$TAG"
ATTEMPTS=$(cat "$ATTEMPTS_FILE" 2>/dev/null || echo 0)
if [ "$ATTEMPTS" -ge "$MAX_ATTEMPTS" ]; then
    log "build $TAG has failed $ATTEMPTS times; not trying again (rm $ATTEMPTS_FILE to reset)"
    exit 0
fi

log "new build detected: $TAG (attempt $((ATTEMPTS + 1)) of $MAX_ATTEMPTS)"
if [ "$DRY" = 1 ]; then
    log "dry run: would run add_gamever, run_linux, run_windows, the battery, then deploy mode '$DEPLOY_MODE'"
    exit 0
fi

# ---------------------------------------------------------------- preflight
FREE_GB=$(df -BG --output=avail "$REPO" | tail -1 | tr -dc '0-9')
[ "${FREE_GB:-0}" -ge "$MIN_FREE_GB" ] || die "only ${FREE_GB}G free, need ${MIN_FREE_GB}G for a depot download plus IDBs"
command -v DepotDownloader >/dev/null || die "DepotDownloader is not in PATH"
command -v uv >/dev/null || die "uv is not in PATH"
[ -n "${CS2VIBE_AGENT:-}" ] || command -v claude >/dev/null || command -v opencode >/dev/null \
    || die "no agent CLI found and CS2VIBE_AGENT is unset"
git diff --quiet || die "the working tree has uncommitted changes; refusing to start"

echo $((ATTEMPTS + 1)) > "$ATTEMPTS_FILE"
OLD_TAG=$(ls -d gamesymbols/*.yaml 2>/dev/null | sed 's|.*/||;s|\.yaml$||' |
          sort -V | awk -v new="$TAG" '$0 != new' | tail -1)
log "previous build: ${OLD_TAG:-none}"

step() {  # step <label> <command...>
    log "==> $1"
    if ! "${@:2}"; then
        die "$1"
    fi
}

# ---------------------------------------------------------------- the chain
step "registering $TAG in download.yaml" ./add_gamever.sh "$TAG"
step "re-asserting this fork's config decisions" uv run ensure_local_gamedata_symbols.py
step "seeding relocation preprocessors" uv run ensure_seed_preprocessors.py
step "analysing linux" ./run_linux.sh "$TAG"
step "analysing windows" ./run_windows.sh "$TAG"

# ---------------------------------------------------------------- battery, as a gate
step "packing the snapshot" uv run gamesymbol_snapshot.py pack -gamever "$TAG" -snapshot "gamesymbols/$TAG.yaml"
step "checking the snapshot against the config" uv run gamesymbol_snapshot.py check-contract \
    -gamever "$TAG" -snapshot "gamesymbols/$TAG.yaml"

GEN_LOG="$STATE/gamedata-$TAG.log"
log "==> generating gamedata"
if ! uv run update_gamedata.py -gamever "$TAG" -snapshot "gamesymbols/$TAG.yaml" \
        -outputdir "gamedata/$TAG" > "$GEN_LOG" 2>&1; then
    tail -20 "$GEN_LOG"
    die "gamedata generation"
fi
WARNINGS=$(grep -oP 'Unique warning diagnostics:\s*\K\d+' "$GEN_LOG" | tail -1 || echo 0)
[ "${WARNINGS:-0}" = "0" ] || { tail -20 "$GEN_LOG"; die "gamedata generation reported $WARNINGS warning diagnostics"; }
log "    $(grep -oP 'Total: \K.*' "$GEN_LOG" | tail -1)"

step "validating every artifact against the binaries" uv run validate_artifacts.py -gamever "$TAG"
step "auditing for batch contamination" uv run audit_duplicate_va.py -gamever "$TAG"
uv run detect_aliases.py -gamever "$TAG" -platform linux || true
uv run detect_aliases.py -gamever "$TAG" -platform windows || true
uv run missing_report.py -gamever "$TAG" -all > "$STATE/missing-$TAG.txt" 2>&1 || true

# The site's history and diagnostics panels read committed datasets rather than
# recomputing in the browser, so they are refreshed here while the binaries are
# still on disk. -skip-validator is not passed: the validator section is the
# evidence that this build was checked.
step "publishing the site datasets" uv run publish_site_data.py -gamever "$TAG"

# ---------------------------------------------------------------- record it
log "==> committing"
git add -A -- "configs/$TAG.yaml" "bin_artifacts/$TAG" "gamesymbols/$TAG.yaml" "gamedata/$TAG" \
    gamedata/history.json "diagnostics/$TAG.json" \
    download.yaml ida_preprocessor_scripts .claude/skills 2>/dev/null || true
if git diff --cached --quiet; then
    log "    nothing to commit"
else
    git commit -q -m "feat($TAG): analysed by autopilot

Verification battery green: 0 gamedata warnings, 0 validator errors, no
duplicate-VA clusters." || die "commit"
    git push -q || die "push"
    log "    committed and pushed"
fi

# ---------------------------------------------------------------- deploy decision
GATE_OUT="$STATE/gate-$TAG.txt"
uv run autopilot_safe_gate.py -gamever "$TAG" > "$GATE_OUT" 2>&1
GATE=$?
cat "$GATE_OUT"

case "$DEPLOY_MODE" in
    off)
        log "deploy mode 'off': stopping here"
        notify "analysed" "$(cat "$GATE_OUT")"
        ;;
    auto)
        log "deploy mode 'auto': deploying regardless of the gate"
        ./deploy_local_plugins.sh "$TAG" || die "deploy"
        ./update_css_gamedata.sh "$TAG" || die "css deploy"
        notify "deployed" "$(cat "$GATE_OUT")"
        ;;
    safe|*)
        if [ "$GATE" = 0 ]; then
            log "gate says SAFE: deploying"
            ./deploy_local_plugins.sh "$TAG" || die "deploy"
            ./update_css_gamedata.sh "$TAG" || die "css deploy"
            notify "deployed" "$(cat "$GATE_OUT")"
        elif [ "$GATE" = 10 ]; then
            log "gate says HOLD: analysed and pushed, deploy is yours"
            notify "held" "$(cat "$GATE_OUT")"
        else
            die "the safe gate could not decide"
        fi
        ;;
esac

rm -f "$ATTEMPTS_FILE"
log "done with $TAG"
