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
#   AUTOPILOT_DEPLOY=safe|verified|auto|off   default safe
#       safe      deploy only when the change is a pure relocation (the gate)
#       verified  deploy whenever the battery is green and every shipped entry
#                 holds against the binaries, even if values changed
#       auto      deploy no matter what the gate says
#       off       analyse, commit and push; never deploy
#   AUTOPILOT_PUBLISH=off|nginx      default off; nginx builds pages/ and rsyncs
#   AUTOPILOT_PUBLISH_TARGET=...     required for nginx: /srv/sig or user@host:/srv/sig
#   AUTOPILOT_PUBLISH_KEEP=N         releases to keep on the target, default 5
#   AUTOPILOT_NOTIFY_URL=...         optional outgoing webhook (ntfy or Discord)
#   AUTOPILOT_NOTIFY_START=0         do not announce detection; only the outcome
#   AUTOPILOT_IMPACT_PLUGINS=a:b     plugin dirs (colon-separated) for the schema impact
#                                    report; the CounterStrikeSharp API is always checked
#   AUTOPILOT_IMPACT_CSS=path        CounterStrikeSharp checkout, default /root/CounterStrikeSharp
#   AUTOPILOT_AUTOCOMMIT=0           refuse a dirty tree instead of committing and
#                                    pushing the tracked changes before a run
#   DEPOTDOWNLOADER_STEAM_USERNAME / _PASSWORD
#   CS2VIBE_AGENT, CS2VIBE_LLM_APIKEY ...
set -uo pipefail
cd "$(dirname "$0")"
REPO="$PWD"

DEPLOY_MODE="${AUTOPILOT_DEPLOY:-safe}"

# Deploy, then prove it landed. Running the scripts is not evidence that the files
# moved: update_css_gamedata.sh merges by key and deploy_local_plugins.sh skips a
# target whose dist file is missing, both without failing. The CCSCustomHudLayout
# win64 signatures sat in the install for a whole generation that way - stale, but
# still resolving uniquely, so every entry-level check called them healthy.
deploy_all() {
    # CSS first: deploy_local_plugins.sh is the one that commits and pushes the
    # CounterStrikeSharp repo, so running it before the merge committed the
    # previous build's file and left this one uncommitted (14186).
    ./update_css_gamedata.sh "$1" || die "css deploy"
    ./deploy_local_plugins.sh "$1" || die "deploy"
    uv run check_deploy_drift.py -gamever "$1" || die "deploy drift: a target is still behind the generated gamedata"
}
PUBLISH_MODE="${AUTOPILOT_PUBLISH:-off}"
PUBLISH_TARGET="${AUTOPILOT_PUBLISH_TARGET:-}"
PUBLISH_KEEP="${AUTOPILOT_PUBLISH_KEEP:-5}"
STATE="${AUTOPILOT_STATE:-$REPO/.autopilot}"
MIN_FREE_GB="${AUTOPILOT_MIN_FREE_GB:-40}"
MAX_ATTEMPTS="${AUTOPILOT_MAX_ATTEMPTS:-2}"
AUTOCOMMIT="${AUTOPILOT_AUTOCOMMIT:-1}"
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
# What to type next, per failure. A notification that only says a step broke
# still costs an SSH session to find out which command to run, and at 03:00 the
# useful message is the one you can act on from a phone.
hint_for() {  # hint_for <failure text>
    local repo="$PWD" ver="${TAG:-<VER>}"
    case "$1" in
        *"uncommitted changes"*)
            printf 'git -C %s status --short\n' "$repo"
            printf 'then commit or "git stash", and: systemctl start cs2vibe-autopilot.service\n' ;;
        *"free, need"*)
            printf 'df -h %s\n' "$repo"
            printf 'du -sh %s/bin/* | sort -h | tail -5     # old depots are the usual culprit\n' "$repo" ;;
        *"not in PATH"*|*"no agent CLI"*)
            printf 'check Environment=PATH in: systemctl cat cs2vibe-autopilot.service\n' ;;
        *"analysing linux"*)
            printf 'cd %s && ./run_linux.sh %s          # resumes, does not start over\n' "$repo" "$ver"
            printf 'uv run missing_report.py -gamever %s -all\n' "$ver" ;;
        *"analysing windows"*)
            printf 'cd %s && ./run_windows.sh %s\n' "$repo" "$ver" ;;
        *"gamedata generation"*)
            printf 'less %s/gamedata-%s.log\n' "${STATE:-.autopilot}" "$ver"
            printf 'cd %s && uv run update_gamedata.py -gamever %s -snapshot gamesymbols/%s.yaml -outputdir gamedata/%s -debug\n' "$repo" "$ver" "$ver" "$ver" ;;
        *"verify_plugin_gamedata"*|*"do not hold against the binaries"*)
            printf 'grep -B20 "^unhealthy: [1-9]" %s/verify-%s.log\n' "${STATE:-.autopilot}" "$ver"
            printf 'cd %s && uv run verify_plugin_gamedata.py -gamever %s -gamedata <the file named above>\n' "$repo" "$ver" ;;
        *"validate"*|*"artifact"*)
            printf 'cd %s && uv run validate_artifacts.py -gamever %s -json | head -40\n' "$repo" "$ver" ;;
        *"binary lock"*)
            printf 'cd %s && uv run write_binary_lock.py -gamever %s -check      # which module differs\n' "$repo" "$ver"
            printf 're-download the pinned manifests: uv run download_depot.py -tag %s, then copy_depot_bin.py\n' "$ver" ;;
        *"anchor drift"*)
            printf 'cd %s && uv run audit_identity_drift.py -gamever %s      # DRIFT lines name the symbol and where its strings went\n' "$repo" "$ver"
            printf 'decide which build is wrong: uv run audit_identity_drift.py -gamever %s -old <an earlier VER> -symbol <name> -v\n' "$ver" ;;
        *"anchor"*)
            printf 'cd %s && uv run audit_xref_identity.py -gamever %s      # BAD lines name the symbol and where its anchor really is\n' "$repo" "$ver"
            printf 're-run its task: uv run ida_analyze_bin.py -gamever %s -platform <p> -modules <m> -skill <task> -require_warm_idb\n' "$ver" ;;
        *"audit"*)
            printf 'cd %s && uv run audit_duplicate_va.py -gamever %s\n' "$repo" "$ver" ;;
        *"ABI identity"*)
            printf 'cd %s && uv run abi_guard.py -gamever %s      # BAD lines name the symbol\n' "$repo" "$ver"
            printf '"good_sig has 0 hits" = the guard table in abi_guard.py needs the new head\n' ;;
        *"site datasets"*)
            printf 'cd %s && uv run publish_site_data.py -check && uv run publish_site_data.py\n' "$repo" ;;
        *"snapshot"*|*"pack"*|*"contract"*)
            printf 'cd %s && uv run gamesymbol_snapshot.py pack -gamever %s -snapshot gamesymbols/%s.yaml\n' "$repo" "$ver" "$ver" ;;
        push)
            printf 'cd %s && git status -sb && git pull --rebase && git push\n' "$repo" ;;
        commit)
            printf 'cd %s && git status --short\n' "$repo" ;;
        *"deploy drift"*)
            printf 'cd %s && uv run check_deploy_drift.py -gamever %s\n' "$repo" "$ver"
            printf 'the deploy scripts ran but a target still differs; the lines above name the keys\n' ;;
        *deploy*)
            printf 'cd %s && ./update_css_gamedata.sh %s && ./deploy_local_plugins.sh %s\n' "$repo" "$ver" "$ver"
            printf 'the analysis itself is committed and pushed; only the copy out failed\n' ;;
        *"site publish"*|*AUTOPILOT_PUBLISH*)
            printf 'cd %s/pages && PAGES_RELEASE_INPUT_ROOT=%s npm run build\n' "$repo" "$repo" ;;
        *)
            printf 'journalctl -u cs2vibe-autopilot -n 200 --no-pager\n' ;;
    esac
    printf 'retry the whole chain: rm -f %s/attempts-%s; systemctl start cs2vibe-autopilot.service\n' "${STATE:-.autopilot}" "$ver"
}

die() {
    log "FAILED: $*"
    notify "failed" "$*

what to run:
$(hint_for "$*")"
    exit 1
}

# Rebase onto origin, then push. A push after hours of analysis must not fail just
# because a commit landed on origin from the local PC in the meantime. A rebase
# that conflicts is aborted, so the tree is never left mid-rebase for the next run.
sync_push() {
    if ! git pull -q --rebase origin "$(git rev-parse --abbrev-ref HEAD)"; then
        git rebase --abort 2>/dev/null
        return 1
    fi
    git push -q origin HEAD
}

notify() {  # notify <outcome> <text>
    [ -x ./autopilot_notify.sh ] || return 0
    local took=""
    if [ -n "${STARTED_EPOCH:-}" ] && [ "$1" != "started" ]; then
        local seconds=$(( $(date +%s) - STARTED_EPOCH ))
        took="took $((seconds / 3600))h $(((seconds % 3600) / 60))m
"
    fi
    ./autopilot_notify.sh "$1" "${TAG:-unknown}" "${took}$2" || true
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
# Done means committed, not merely packed: run_linux.sh and run_windows.sh each pack
# the snapshot when they finish, so a build whose chain failed after analysis - or
# was finished by hand - has the file on disk with the battery, commit and deploy
# never run. Keyed on the file alone, the timer then skipped 14186 for good.
if git ls-files --error-unmatch "gamesymbols/$TAG.yaml" >/dev/null 2>&1; then
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
STARTED_EPOCH=$(date +%s)
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
# Tracked edits only (commit -a): untracked files never block a run and are never
# swept in, which is what CLAUDE.md rule 3 is about. A tree mid-merge or with
# conflicts cannot be committed, and still stops the run.
if ! git diff --quiet || ! git diff --cached --quiet; then
    [ "$AUTOCOMMIT" = 1 ] || die "the working tree has uncommitted changes; refusing to start"
    log "committing local changes before the run"
    git diff --stat | tail -1
    git commit -q -a -m "chore: local changes committed by autopilot before $TAG" \
        || die "the working tree has uncommitted changes; refusing to start"
fi
sync_push || die "push"

echo $((ATTEMPTS + 1)) > "$ATTEMPTS_FILE"
OLD_TAG=$(ls -d gamesymbols/*.yaml 2>/dev/null | sed 's|.*/||;s|\.yaml$||' |
          sort -V | awk -v new="$TAG" '$0 != new' | tail -1)
log "previous build: ${OLD_TAG:-none}"

# A build lands while you are asleep, and the run takes hours: without this the
# first sign of life is the finished message, so there is no way to tell "still
# working" from "never started". Off with AUTOPILOT_NOTIFY_START=0.
if [ "$DRY" != 1 ] && [ "${AUTOPILOT_NOTIFY_START:-1}" != "0" ]; then
    notify "started" "previous build : ${OLD_TAG:-none}
deploy mode   : $DEPLOY_MODE
attempt       : $((ATTEMPTS + 1)) of $MAX_ATTEMPTS
expect the next message when the chain finishes, or if a step fails."
fi


step() {  # step <label> <command...>
    log "==> $1"
    if ! "${@:2}"; then
        die "$1"
    fi
}

# The analysis scripts resume: a re-run skips every artifact that already exists
# and only retries what is missing. So a failed analysis step is re-run in place
# before the whole chain is given up on. On 14186 both chain attempts died this
# way - linux on 28 deferred tasks whose inputs a resume then produced, windows on
# an idalib-mcp that failed to open twice - and each cost a new 3-hour chain from
# a systemd retry, when a resume of the one step would have finished in minutes.
STEP_RESUMES="${AUTOPILOT_STEP_RESUMES:-2}"
step_resume() {  # step_resume <label> <command...>
    local n=0
    log "==> $1"
    until "${@:2}"; do
        n=$((n + 1))
        if [ "$n" -gt "$STEP_RESUMES" ]; then
            die "$1 (after $STEP_RESUMES resume(s))"
        fi
        log "    $1 failed; resuming ($n of $STEP_RESUMES)"
        sleep 30
    done
}

# ---------------------------------------------------------------- the chain
step "registering $TAG in download.yaml" ./add_gamever.sh "$TAG"
step "re-asserting this fork's config decisions" uv run ensure_local_gamedata_symbols.py
step "seeding relocation preprocessors" uv run ensure_seed_preprocessors.py
step_resume "analysing linux" ./run_linux.sh "$TAG"
step_resume "analysing windows" ./run_windows.sh "$TAG"

# ---------------------------------------------------------------- battery, as a gate
# ABI identity before the pack (CLAUDE.md rule 21): relocation reproduces a wrong
# baseline faithfully, and nothing after this point would notice. --fix rewrites
# an artifact onto the guarded head; a guard whose own pattern no longer matches
# still fails, because that needs a person to update the table.
# Every check below reads bin/$TAG. If a lock already exists, those files must be
# the ones it names - otherwise every verdict is about some other build.
if [ -f "binary_locks/$TAG.json" ]; then
    step "checking bin/ against the binary lock" uv run write_binary_lock.py -gamever "$TAG" -check
fi
step "checking ABI identity" uv run abi_guard.py -gamever "$TAG" --fix
# The general form of the same question: does every relocated function still
# reference the string (or byte pattern) its finder anchors on? A sig that outlived
# its function matches uniquely in another one - JoinTeam.linux sat on the wrong
# function 14182-14188 and crashed MatchZy servers. The run already discards such a
# relocation; this catches one that reached the artifacts any other way.
step "checking each function still holds its anchor" uv run audit_xref_identity.py -gamever "$TAG"
# And every function artifact, anchored or not, against the previous gamever: its
# strings must carry over. DRIFT = the previous strings now sit together in another
# function, so one of the two builds names the wrong one. The run already discards
# such a relocation (CS2VIBE_RELOC_DRIFT_CHECK=0 turns that off).
step "checking each function against the previous gamever (anchor drift)" uv run audit_identity_drift.py -gamever "$TAG"
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

# The artifacts being sound is not the same claim as the SHIPPED files being
# sound: a generator can leave a key at a frozen template value, and
# validate_artifacts never looks at a plugin file. Checking only
# CounterStrikeSharp is how CS2Fixes went four gamevers unverified. Every
# shipped file, every entry re-scanned against the binaries, and "unhealthy"
# must be zero - this is the gate that answers "are the offsets and signatures
# actually intact".
log "==> verifying every shipped plugin file"
# Only what this fork still generates. The directories of the five disabled
# plugins survive from older builds, and their data is stale on purpose - the
# first run of this check died on cs2kz's own 4 unhealthy entries, which would
# have blocked every future build for data nobody here ships. MODULE_ENABLED is
# the same source of truth the published site uses.
DISABLED=$(uv run python -c "import publish_site_data as P; print(' '.join(sorted(P.disabled_plugins())))" 2>/dev/null || echo "")
[ -n "$DISABLED" ] && log "    skipping disabled generators: $DISABLED"
VERIFY_LOG="$STATE/verify-$TAG.log"
: > "$VERIFY_LOG"
UNHEALTHY_TOTAL=0
VERIFIED_FILES=0
while IFS= read -r plugin_file; do
    [ -n "$plugin_file" ] || continue
    plugin_dir=${plugin_file#gamedata/$TAG/}
    plugin_dir=${plugin_dir%%/*}
    case " $DISABLED " in *" $plugin_dir "*) continue ;; esac
    if ! uv run verify_plugin_gamedata.py -gamever "$TAG" -gamedata "$plugin_file" >> "$VERIFY_LOG" 2>&1; then
        tail -20 "$VERIFY_LOG"
        die "verify_plugin_gamedata failed on $plugin_file"
    fi
    VERIFIED_FILES=$((VERIFIED_FILES + 1))
    bad=$(grep -oP '^unhealthy:\s*\K\d+' "$VERIFY_LOG" | tail -1 || echo 0)
    if [ "${bad:-0}" != "0" ]; then
        log "    ${plugin_file}: $bad unhealthy entr(ies)"
        UNHEALTHY_TOTAL=$((UNHEALTHY_TOTAL + bad))
    fi
done <<EOF
$(find "gamedata/$TAG" -type f \( -name '*.json' -o -name '*.jsonc' -o -name '*.txt' \) ! -name '*.metadata.json' | sort)
EOF
if [ "$UNHEALTHY_TOTAL" != "0" ]; then
    die "$UNHEALTHY_TOTAL shipped gamedata entr(ies) do not hold against the binaries"
fi
log "    $VERIFIED_FILES shipped file(s) checked, every entry holds"

uv run detect_aliases.py -gamever "$TAG" -platform linux || true
uv run detect_aliases.py -gamever "$TAG" -platform windows || true
uv run missing_report.py -gamever "$TAG" -all > "$STATE/missing-$TAG.txt" 2>&1 || true

# The site's history and diagnostics panels read committed datasets rather than
# recomputing in the browser, so they are refreshed here while the binaries are
# still on disk. -skip-validator is not passed: the validator section is the
# evidence that this build was checked.
step "publishing the site datasets" uv run publish_site_data.py -gamever "$TAG"

# Bind the build to its manifests and binary hashes. Nothing else writes these per
# build, and without one anything that maps a build through binary_locks/ (the
# cs2-signatures tracker's reference lookup) silently skips it - locks stopped at
# 14181 that way. -force: a re-run of the same tag rewrites identical content.
if [ -f "binary_locks/$TAG.json" ]; then
    # A re-run must analyse the SAME files: overwriting the lock here is how a
    # bin/ holding another build's binaries would go unnoticed (bin/14171 held
    # 14170's, bin/14167 and bin/14168 files no manifest matched).
    step "checking the binary lock" uv run write_binary_lock.py -gamever "$TAG" -check
else
    step "writing the binary lock" uv run write_binary_lock.py -gamever "$TAG"
fi

# Schema impact: which schema fields CounterStrikeSharp and the plugins actually use
# were removed or renamed by this build. Gamedata says nothing about that - a plugin
# can break on a renamed m_ field with every signature healthy. Informational, never a
# gate: schema is resolved by name at runtime, so a break is a plugin fix, not a
# reason to hold gamedata back. The summary line goes into the final notification.
IMPACT_OUT="$STATE/impact-$TAG.txt"
IMPACT_LINE=""
if [ -n "${OLD_TAG:-}" ]; then
    log "==> schema impact $OLD_TAG -> $TAG"
    impact_args=(-old "$OLD_TAG" -new "$TAG")
    [ -n "${AUTOPILOT_IMPACT_CSS:-}" ] && impact_args+=(-css "$AUTOPILOT_IMPACT_CSS")
    IFS=':' read -r -a impact_dirs <<< "${AUTOPILOT_IMPACT_PLUGINS:-}"
    for dir in "${impact_dirs[@]}"; do
        [ -n "$dir" ] && [ -d "$dir" ] && impact_args+=(-plugins "$dir")
    done
    uv run schema_dump.py impact "${impact_args[@]}" > "$IMPACT_OUT" 2>&1
    case $? in
        0) IMPACT_LINE="schema: $(grep -m1 '^summary:' "$IMPACT_OUT" | sed 's/^summary: //')" ;;
        1) IMPACT_LINE="SCHEMA BREAK: $(grep -m1 '^summary:' "$IMPACT_OUT" | sed 's/^summary: //') (see $IMPACT_OUT)" ;;
        *) IMPACT_LINE="schema impact skipped: $(tail -1 "$IMPACT_OUT")" ;;
    esac
    log "    $IMPACT_LINE"
fi

# The two things that otherwise cost an SSH session: which keys actually moved,
# and where to look at the result. Read from the metadata companions the
# generator just wrote, so it is what the plugins really got.
changed_keys_block() {
    uv run python - "$TAG" <<'PYEOF' 2>/dev/null || true
import glob, json, os, sys

import publish_site_data as P

tag = sys.argv[1]
# Only plugins this fork still generates: the disabled ones keep their old
# metadata on disk, and counting it would report keys no plugin here receives
# (13 files instead of the 8 that ship).
disabled = P.disabled_plugins()
names, files = [], 0
for path in sorted(glob.glob(os.path.join("gamedata", tag, "**", "*.metadata.json"), recursive=True)):
    if os.path.relpath(path, os.path.join("gamedata", tag)).split(os.sep)[0] in disabled:
        continue
    try:
        document = json.load(open(path, encoding="utf-8"))
    except Exception:
        continue
    touched = set()
    for entry in document.get("entries", []):
        for change in entry.get("changes") or []:
            path_parts = change.get("path") or []
            if path_parts:
                touched.add(str(path_parts[0]))
    if touched:
        files += 1
        names.extend(sorted(touched))

unique = sorted(set(names))
if not unique:
    print("no key changed value")
else:
    head = ", ".join(unique[:5])
    rest = f" and {len(unique) - 5} more" if len(unique) > 5 else ""
    print(f"{len(unique)} key(s) changed across {files} file(s): {head}{rest}")
PYEOF
}

# printf, not a quoted "\n\n": inside double quotes those are two literal
# characters, which is exactly how the first version reached Discord.
final_body() {
    printf '%s\n%s\n\n%s\n\n%s\n' "$(changed_keys_block)" "$IMPACT_LINE" "$(cat "$GATE_OUT")" "$(site_links)"
}

site_links() {
    printf 'https://sig.miksen.me/game-data   the files, per build\n'
    printf 'https://sig.miksen.me/check       drop your own file to compare it\n'
}

# ---------------------------------------------------------------- record it
log "==> committing"
git add -A -- "configs/$TAG.yaml" "bin_artifacts/$TAG" "gamesymbols/$TAG.yaml" "gamedata/$TAG" \
    gamedata/history.json "diagnostics/$TAG.json" \
    "binary_locks/$TAG.json" download.yaml ida_preprocessor_scripts .claude/skills 2>/dev/null || true
if git diff --cached --quiet; then
    log "    nothing to commit"
else
    git commit -q -m "feat($TAG): analysed by autopilot

Verification battery green: 0 gamedata warnings, 0 validator errors, no
duplicate-VA clusters." || die "commit"
    # publishedAt is the date of the first commit that added gamedata/<build>/,
    # which did not exist when the datasets were built above - so the newest
    # build always went out as null and -check failed until the NEXT build's run
    # repaired it. Now that the commit exists, re-derive the history only.
    if uv run publish_site_data.py -history-only >/dev/null \
            && ! git diff --quiet -- gamedata/history.json; then
        git commit -q -m "chore($TAG): record publish date in site history" \
            -- gamedata/history.json || die "commit"
    fi
    uv run publish_site_data.py -check || die "site datasets stale after commit"
    sync_push || die "push"
    log "    committed and pushed"
fi

# ---------------------------------------------------------------- publish the site
# Independent of the plugin deploy gate below: that gate decides whether a build
# is safe to put under a live server's plugins, which says nothing about showing
# the numbers on a web page. GitHub Pages needs none of this - it builds from the
# pushed commit - so the default is off and this only runs when asked.
publish_site() {
    local target="$1" stamp release
    stamp="$TAG-$(date -u +%Y%m%dT%H%M%SZ)"

    if [ ! -d "$REPO/pages/node_modules" ]; then
        log "    installing pages dependencies"
        ( cd "$REPO/pages" && npm ci --silent ) || return 1
    fi
    log "    building"
    ( cd "$REPO/pages" && PAGES_RELEASE_INPUT_ROOT="$REPO" npm run build --silent ) || return 1

    # The same checks the workflow runs, because moving off Pages must not mean
    # publishing unverified assets: both verifiers re-read every emitted file and
    # match it against its index, and -check catches a stale committed dataset.
    log "    verifying the emitted assets"
    ( cd "$REPO/pages" && npm run verify:gamesymbols --silent && npm run verify:gamedata --silent ) || return 1
    uv run publish_site_data.py -check || return 1

    # Published as a new release directory with the serving symlink flipped at the
    # end, so a visitor never sees a half-copied site and a rollback is one
    # symlink. nginx must therefore have its root on <target>/current.
    local remote="" base=""
    case "$target" in
        *:*) remote="${target%%:*}"; base="${target#*:}" ;;
        *)   base="$target" ;;
    esac
    release="$base/releases/$stamp"

    if [ -n "$remote" ]; then
        ssh "$remote" "mkdir -p '$base/releases'" || return 1
        rsync -a --delete "$REPO/pages/dist/" "$remote:$release/" || return 1
        ssh "$remote" "ln -sfn '$release' '$base/current.new' && mv -T '$base/current.new' '$base/current' \
            && ls -1dt '$base'/releases/* | tail -n +$((PUBLISH_KEEP + 1)) | xargs -r rm -rf" || return 1
    else
        mkdir -p "$base/releases" || return 1
        rsync -a --delete "$REPO/pages/dist/" "$release/" || return 1
        ln -sfn "$release" "$base/current.new" || return 1
        mv -T "$base/current.new" "$base/current" || return 1
        ls -1dt "$base"/releases/* | tail -n +$((PUBLISH_KEEP + 1)) | xargs -r rm -rf
    fi
    log "    serving $release"
}

case "$PUBLISH_MODE" in
    off) : ;;
    nginx)
        [ -n "$PUBLISH_TARGET" ] || die "AUTOPILOT_PUBLISH=nginx needs AUTOPILOT_PUBLISH_TARGET"
        log "==> publishing the site to $PUBLISH_TARGET"
        if [ "$DRY" = 1 ]; then
            log "    dry run: would build pages/, verify the assets and rsync to $PUBLISH_TARGET"
        elif ! publish_site "$PUBLISH_TARGET"; then
            die "site publish"
        fi
        ;;
    *) die "unknown AUTOPILOT_PUBLISH: $PUBLISH_MODE" ;;
esac

# ---------------------------------------------------------------- deploy decision
GATE_OUT="$STATE/gate-$TAG.txt"
uv run autopilot_safe_gate.py -gamever "$TAG" > "$GATE_OUT" 2>&1
GATE=$?
cat "$GATE_OUT"

case "$DEPLOY_MODE" in
    off)
        log "deploy mode 'off': stopping here"
        notify "analysed" "$(final_body)"
        ;;
    verified)
        # What the gate refuses is CHANGE, not breakage: a new key or a moved
        # slot holds a build back even when every shipped entry verifies. This
        # mode trusts the battery instead - generation clean, every artifact
        # checked against the binaries, no duplicate VAs, and every shipped
        # entry re-scanned with unhealthy zero - and deploys on that.
        log "deploy mode 'verified': battery green and every shipped entry holds, deploying"
        deploy_all "$TAG"
        notify "deployed" "$(final_body)"
        ;;
    auto)
        log "deploy mode 'auto': deploying regardless of the gate"
        deploy_all "$TAG"
        notify "deployed" "$(final_body)"
        ;;
    safe|*)
        if [ "$GATE" = 0 ]; then
            log "gate says SAFE: deploying"
            deploy_all "$TAG"
            notify "deployed" "$(final_body)"
        elif [ "$GATE" = 10 ]; then
            log "gate says HOLD: analysed and pushed, deploy is yours"
            notify "held" "$(final_body)"
        else
            die "the safe gate could not decide"
        fi
        ;;
esac

rm -f "$ATTEMPTS_FILE"
log "done with $TAG"
