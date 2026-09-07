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

# 3. Run pipeline
echo "==> Downloading depot..."
uv run download_depot.py -tag "$NEW_VER"

echo "==> Copying Linux binaries..."
uv run copy_depot_bin.py -gamever "$NEW_VER" -platform all-platform

# Hydrate baseline symbol YAMLs for signature reuse. bin_artifacts/<OLD_VER> is the
# published copy of the analysis - a plain copy is all the restore ever achieved, and
# it avoids the snapshot's config-digest validation (the config legitimately evolves
# after packing via ensure_local_gamedata_symbols.py injections).
if [ ! -d "bin/${OLD_VER}" ] || ! find "bin/${OLD_VER}" -name '*.yaml' | grep -q .; then
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
pkill -9 -f 'ida_pro_mcp\.idalib_server' 2>/dev/null || true
pkill -9 -f 'idalib-mcp --unsafe' 2>/dev/null || true
if [ -d "bin/${NEW_VER}" ]; then
    find "bin/${NEW_VER}" \( -name '*.id0' -o -name '*.id1' -o -name '*.id2' -o -name '*.nam' -o -name '*.til' \) -delete 2>/dev/null || true
fi
sleep 1

echo "==> Running IDA analysis..."
# -skip_error: one stubborn symbol must not abort the whole queue - failures fall out
# of the summary and can be taken manually (IDA GUI) or retried afterwards.
SKIP_ERRORS="${SKIP_ERRORS:-1}"
[ "$SKIP_ERRORS" = "1" ] && EXTRA_ANALYZE=(-skip_error) || EXTRA_ANALYZE=()

# Optional LLM for LLM_DECOMPILE preprocessing (OpenAI Responses API):
# export LLM_APIKEY=sk-...   (+ LLM_MODEL / LLM_BASEURL hvis ikke OpenAI-default)
LLM_ARGS=()
[ -n "${LLM_APIKEY:-}" ] && LLM_ARGS+=(-llm_apikey "$LLM_APIKEY")
[ -n "${LLM_MODEL:-}" ] && LLM_ARGS+=(-llm_model "$LLM_MODEL")
[ -n "${LLM_BASEURL:-}" ] && LLM_ARGS+=(-llm_baseurl "$LLM_BASEURL")
uv run ida_analyze_bin.py -gamever "$NEW_VER" -oldgamever "$OLD_VER" -platform linux "${EXTRA_ANALYZE[@]} ${LLM_ARGS[@]+"${LLM_ARGS[@]}"}"

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

# Always re-pack: a pre-existing snapshot (e.g. upstream's) lacks the injected
# WeaponPaints symbols, which the gamedata generators need in the snapshot.
echo "==> Packing game-symbol snapshot for $NEW_VER..."
uv run gamesymbol_snapshot.py pack -gamever "$NEW_VER" -snapshot "gamesymbols/${NEW_VER}.yaml"

echo "==> Analysis complete for version $NEW_VER!"
