#!/usr/bin/env bash
set -euo pipefail

echo "==> Syncing environment with uv..."
uv sync

# 1. Fetch latest version using curl (bypasses Python SSL cert issues)
fetch_version() {
    # Method A: ISteamApps UpToDateCheck
    local ver
    ver=$(curl -sL --max-time 5 -A "Mozilla/5.0" "https://api.steampowered.com/ISteamApps/UpToDateCheck/v1/?appid=730&version=0" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    print(data['response']['required_version'])
except Exception:
    pass
" 2>/dev/null)

    if [[ -n "$ver" && "$ver" =~ ^[0-9]+$ ]]; then
        echo "$ver"
        return
    fi

    # Method B: IGCVersion_730 GetServerVersion
    ver=$(curl -sL --max-time 5 -A "Mozilla/5.0" "https://api.steampowered.com/IGCVersion_730/GetServerVersion/v1/" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    res = data.get('result', {})
    print(res.get('deploy_version') or res.get('patch_version') or '')
except Exception:
    pass
" 2>/dev/null)

    echo "$ver"
}

NEW_VER=$(fetch_version)

# Fallback: prompt if both API calls failed
if ! [[ "$NEW_VER" =~ ^[0-9]+$ ]]; then
    echo "⚠️  Could not auto-fetch version from Steam API."
    read -rp "Please enter the NEW gamever manually (e.g., 14174): " NEW_VER
fi

# Optional: pass an explicit gamever tag (e.g. "./run_LINUX.sh 14178b") to override the
# Steam-API numeric version — needed for manifest-suffix variants (14178b etc.), which the
# Steam API cannot express. Tags must exist in download.yaml.
if [ -n "${1:-}" ]; then
    NEW_VER="$1"
    grep -q "tag: \"$NEW_VER\"" download.yaml || echo "⚠️  Tag '$NEW_VER' not in download.yaml — depot lookup may fail."
    echo "==> Using explicit gamever tag: $NEW_VER"
fi
# Sanity check — gamever is numeric with optional manifest-suffix letter (14178, 14178b, 14165c, ...)
if ! [[ "$NEW_VER" =~ ^[0-9]+[a-z]?$ ]]; then
    echo "❌ Error: Invalid gamever '$NEW_VER'. Exiting."
    exit 1
fi

# 2. Determine OLD_VER (highest existing folder in bin/ lower than NEW_VER, or NEW_VER - 1)
LOCAL_PREV=$(ls -d bin/*/ 2>/dev/null | grep -oP '\d+' | sort -n | awk -v new="$NEW_VER" '$1 < new' | tail -n 1 || echo "")

if [[ -n "$LOCAL_PREV" && "$LOCAL_PREV" =~ ^[0-9]+$ ]]; then
    OLD_VER="$LOCAL_PREV"
else
    OLD_VER=$((NEW_VER - 1))
fi

echo "==> Target Version (gamever):    $NEW_VER"
echo "==> Baseline Version (oldgamever): $OLD_VER"

# Analysis configs are version-independent in content (no gamever references) and
# hand-curated upstream — sync_upstream.sh brings new-gamever configs in. When
# upstream has not published one yet, scaffold configs/${NEW_VER}.yaml from the
# newest existing config so a brand-new gamever runs without hand-editing.
if [ ! -f "configs/${NEW_VER}.yaml" ]; then
    PREV_CFG=$(ls -1 configs/*.yaml 2>/dev/null | grep -E '/[0-9]+[a-z]?\.yaml$' | sort -V | tail -n 1)
    if [ -n "$PREV_CFG" ]; then
        echo "==> No config for $NEW_VER; scaffolding from $PREV_CFG"
        cp -p "$PREV_CFG" "configs/${NEW_VER}.yaml"
    else
        echo "⚠️  No configs/*.yaml found to scaffold from — analysis will fail."
    fi
fi

# WeaponPaints gamedata (gamedata-generators/weaponpaints/) needs every
# weaponpaints.json entry analyzed per gamever. Configs are hand-authored and
# don't inherit, so inject them into configs/${NEW_VER}.yaml (idempotent per
# symbol; warns and skips if the config is absent).
uv run ensure_local_gamedata_symbols.py -config "configs/${NEW_VER}.yaml"
# Agent-fallback skills for ALLE tasks (upstream preprocessor-only inkl.) - goer
# nye gamevers selvhelbredende uden upstream-afhaengighed.
uv run ensure_agent_fallback_skills.py -config "configs/${NEW_VER}.yaml"

# 3. Run pipeline
echo "==> Downloading depot..."
uv run download_depot.py -tag "$NEW_VER"

echo "==> Copying Linux binaries..."
uv run copy_depot_bin.py -gamever "$NEW_VER" -platform all-platform

# Hydrate baseline symbol YAMLs for signature reuse. bin_artifacts/<OLD_VER> is the
# published copy of the analysis - a plain copy is all the restore ever achieved, and
# it avoids the snapshot's config-digest validation (the config legitimately evolves
# after packing via ensure_local_gamedata_symbols.py injections).
# -print -quit stops find at the first hit: piping into "grep -q ." made grep close
# the pipe, find died on SIGPIPE ("find: write error"), and under pipefail the
# non-zero status inverted the test - so a fully hydrated baseline was re-copied
# on every run and the failure printed on every run.
if [ ! -d "bin/${OLD_VER}" ] || [ -z "$(find "bin/${OLD_VER}" -name '*.yaml' -print -quit)" ]; then
    if [ -d "bin_artifacts/${OLD_VER}" ]; then
        echo "==> Hydrating baseline bin/${OLD_VER} from bin_artifacts/${OLD_VER}..."
        mkdir -p "bin/${OLD_VER}"
        cp -ru bin_artifacts/${OLD_VER}/. "bin/${OLD_VER}/"
    else
        echo "⚠️  No baseline for $OLD_VER (bin/ + bin_artifacts/ tomme) - uændrede symboler kræver agent/LLM-analyse."
    fi
else
    echo "==> Baseline bin/${OLD_VER} already hydrated"
fi

# Analyzer-version guard: en forældet ida_analyze_bin.py (fx efter delvis pull) giver
# kun kryptiske argparse-fejl - fejl tidligt og tydeligt i stedet.
grep -q '"-skip_error"' ida_analyze_bin.py 2>/dev/null || {
    echo "❌ ida_analyze_bin.py er forældet (mangler -skip_error). Koer: git pull / git checkout -- ida_analyze_bin.py"
    exit 1
}

# Reap stale idalib-mcp supervisors + IDB locks (left by interrupted prior runs or
# concurrent scripts). A stale session holding libserver.so makes windows skills fail
# with "only libserver.so is open" errors.
export CS2VIBE_MCP_PORT="${CS2VIBE_MCP_PORT:-13401}"
# Reap only what belongs to THIS run. The interactive session keeps its own
# idalib-mcp on 13337 (.mcp.json points there), and the old blanket
# "pkill -f 'idalib-mcp --unsafe'" killed that too, so every analysis run cost
# the editor its IDA connection. Two rules instead:
#   * kill the server on OUR port, and its worker child (the worker listens on a
#     random port, so it cannot be matched by port itself)
#   * kill idalib_server workers that have been orphaned (parent is init), since
#     those hold IDB locks and nothing owns them any more
reap_mcp_port() {
    local port="$1" pid ppid
    for pid in $(pgrep -f "idalib-mcp --unsafe --host 127.0.0.1 --port ${port}" 2>/dev/null); do
        pkill -9 -P "$pid" 2>/dev/null || true
        kill -9 "$pid" 2>/dev/null || true
    done
    for pid in $(pgrep -f 'ida_pro_mcp\.idalib_server' 2>/dev/null); do
        ppid=$(ps -o ppid= -p "$pid" 2>/dev/null | tr -d ' ')
        [ "$ppid" = "1" ] && kill -9 "$pid" 2>/dev/null || true
    done
    # An interrupted run leaves its supervisor ORPHANED on a port nobody reaps:
    # the loop above only reaps this run's port, and the worker below it is not an
    # orphan (its parent is the supervisor), so both survive and keep holding that
    # module's IDB. The next run then dies on "IDB lock file detected
    # (bin/<VER>/engine/libengine2.so.id0)" for a database no one is using.
    # The interactive session server is kept: it is orphaned too once its shell
    # exits, and .mcp.json points at it.
    for pid in $(pgrep -f 'idalib-mcp --unsafe' 2>/dev/null); do
        ppid=$(ps -o ppid= -p "$pid" 2>/dev/null | tr -d ' ')
        [ "$ppid" = "1" ] || continue
        tr '\0' ' ' < /proc/"$pid"/cmdline 2>/dev/null \
            | grep -qE -- "--port ${CS2VIBE_SESSION_MCP_PORT:-13337}( |$)" && continue
        echo "[idb] reaping orphaned idalib-mcp (pid ${pid}, no parent)"
        pkill -9 -P "$pid" 2>/dev/null || true
        kill -9 "$pid" 2>/dev/null || true
    done
}

# A live server holding a binary of the gamever about to be analysed would lose
# its IDB aux files to the cleanup below, so say so rather than corrupting it.
warn_if_session_holds() {
    local ver="$1"
    if pgrep -af "idalib-mcp --unsafe" 2>/dev/null | grep -q "bin/${ver}/"; then
        echo "ℹ  another idalib-mcp has a bin/${ver}/ binary open (probably the editor session)."
        echo "   Its database is left alone, but it holds that binary: a module this run"
        echo "   needs may fail with \"only <other>.so is open\" until you close it."
    fi
}

# The editor's IDA session (systemd/cs2vibe-ida-session.service, 13337) is paused
# for the length of the run and started again on exit, so it never holds a
# database this run needs; starting it again also moves it to the build this run
# produced. Only an enabled unit is started, so a machine without it is untouched.
SESSION_UNIT=cs2vibe-ida-session.service
if command -v systemctl >/dev/null 2>&1 && systemctl is-active --quiet "$SESSION_UNIT" 2>/dev/null; then
    echo "[idb] pausing the editor IDA session for this run ($SESSION_UNIT)"
    systemctl stop "$SESSION_UNIT" || true
fi
resume_session() {
    if command -v systemctl >/dev/null 2>&1 && systemctl is-enabled --quiet "$SESSION_UNIT" 2>/dev/null; then
        systemctl start --no-block "$SESSION_UNIT" 2>/dev/null || true
    fi
}
trap resume_session EXIT

reap_mcp_port "$CS2VIBE_MCP_PORT"
warn_if_session_holds "${NEW_VER}"
# Clear IDB aux files, but only for databases nobody has open.
#
# The unpacked files (.id0/.id1/.id2/.nam/.til) are what a LIVE database works
# in; .i64 is the packed form written on close. So a set with no owner is the
# wreckage of an interrupted run and must go, while a set with an owner is a
# working database - deleting that pulls the floor out from under it. Per-file
# checks are not enough: a live DB holds .id0 open but not always .til, so the
# question is which BINARY a live idalib process owns.
held_idb_bases() {
    local pid link base
    for pid in $(pgrep -f 'idalib-mcp --unsafe' 2>/dev/null) \
               $(pgrep -f 'ida_pro_mcp\.idalib_server' 2>/dev/null); do
        for link in /proc/"$pid"/fd/*; do
            base=$(readlink "$link" 2>/dev/null) || continue
            case "$base" in
                *.id0|*.id1|*.id2|*.nam|*.til|*.i64)
                    printf '%s\n' "${base%.*}" ;;
            esac
        done
        # the binary named on the command line, in case no fd is open yet
        tr '\0' '\n' < /proc/"$pid"/cmdline 2>/dev/null | tail -1 | grep -E '^/|^bin/' || true
    done | sed -E 's/\.(id[0-2]|nam|til|i64)$//' | sort -u
}

clear_free_idb_aux() {
    local ver="$1" file base held kept=0 removed=0
    [ -d "bin/${ver}" ] || return 0
    held="$(held_idb_bases)"
    while IFS= read -r file; do
        [ -n "$file" ] || continue
        base="${file%.*}"
        if printf '%s\n' "$held" | grep -qxF "$(readlink -f "$base" 2>/dev/null || echo "$base")" \
           || printf '%s\n' "$held" | grep -qxF "$base"; then
            kept=$((kept + 1))
            continue
        fi
        rm -f -- "$file" && removed=$((removed + 1))
    done <<EOF
$(find "bin/${ver}" \( -name '*.id0' -o -name '*.id1' -o -name '*.id2' -o -name '*.nam' -o -name '*.til' \) 2>/dev/null)
EOF
    echo "[idb] ${removed} stale aux file(s) removed, ${kept} left to a live database"
}

clear_free_idb_aux "${NEW_VER}"
sleep 1

echo "==> Running IDA analysis..."
# -skip_error: one stubborn symbol must not abort the whole queue - failures fall out
# of the summary and can be taken manually (IDA GUI) or retried afterwards.
SKIP_ERRORS="${SKIP_ERRORS:-1}"
[ "$SKIP_ERRORS" = "1" ] && EXTRA_ANALYZE=(-skip_error) || EXTRA_ANALYZE=()

# Optional LLM for LLM_DECOMPILE preprocessing (OpenAI-compatible chat.completions):
# export LLM_APIKEY=sk-...   (+ LLM_MODEL / LLM_BASEURL hvis ikke OpenAI-default)
LLM_ARGS=()
[ -n "${LLM_APIKEY:-}" ] && LLM_ARGS+=(-llm_apikey "$LLM_APIKEY")
[ -n "${LLM_MODEL:-}" ] && LLM_ARGS+=(-llm_model "$LLM_MODEL")
[ -n "${LLM_BASEURL:-}" ] && LLM_ARGS+=(-llm_baseurl "$LLM_BASEURL")
# Binaries analysed side by side (one idalib each, server first); auto = min(cores,
# RAM / 6 GiB, binaries). CS2VIBE_JOBS=1 is the old one-at-a-time run. Agents are
# capped separately by CS2VIBE_AGENT_JOBS (default 3), since they wait on the API.
export CS2VIBE_JOBS="${CS2VIBE_JOBS:-auto}"
uv run ida_analyze_bin.py -gamever "$NEW_VER" -oldgamever "$OLD_VER" -platform windows "${EXTRA_ANALYZE[@]}" ${LLM_ARGS[@]+"${LLM_ARGS[@]}"}

# Publish analysis artifacts (bin/<ver>/<module>/*.yaml -> bin_artifacts/<ver>/...) so
# signature reuse, snapshot pack/restore and future baselines survive local bin/ cleanup.
# cp -u keeps newer existing artifacts. Must run BEFORE the snapshot pack below, which
# validates against bin_artifacts/.
if [ -d "bin/${NEW_VER}" ]; then
    echo "==> Publishing analysis artifacts to bin_artifacts/${NEW_VER}..."
    for module_dir in bin/${NEW_VER}/*/; do
        [ -d "$module_dir" ] || continue
        module="$(basename "$module_dir")"
        mkdir -p "bin_artifacts/${NEW_VER}/${module}"
        cp -u "$module_dir"*.yaml "bin_artifacts/${NEW_VER}/${module}/" 2>/dev/null || true
    done
    echo "==> Published $(find "bin_artifacts/${NEW_VER}" -name '*.yaml' | wc -l) artifact file(s)."
fi

# Always re-pack: the linux run may have packed an incomplete (linux-only) snapshot.
echo "==> Packing game-symbol snapshot for $NEW_VER (windows-complete)..."
uv run gamesymbol_snapshot.py pack -gamever "$NEW_VER" -snapshot "gamesymbols/${NEW_VER}.yaml" -platform windows

echo "==> Publishing the review issue (symbols left for a person)..."
uv run review_issue.py publish -gamever "$NEW_VER" -platform windows || echo "    review issue not published (gh offline?) - run: uv run review_issue.py publish -gamever $NEW_VER"

echo "==> Analysis complete for version $NEW_VER!"
