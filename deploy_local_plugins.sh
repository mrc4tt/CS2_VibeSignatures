#!/bin/bash
#
# deploy_local_plugins.sh — copy generated gamedata outputs into the local plugin
# repos, so each plugin repo's gamedata file stays current with the newest analysis.
#
# Usage: ./deploy_local_plugins.sh [GAMEVER]   (default: newest under gamedata/)
#
# After running, commit the change inside each plugin repo yourself (they have
# their own git history on git.miksen.me).

set -euo pipefail
REPO="$(cd "$(dirname "$0")" && pwd)"

GAMEVER="${1:-}"
if [ -z "$GAMEVER" ]; then
    GAMEVER="$(ls -1 "$REPO/gamedata" | grep -E '^[0-9]+[a-z]?$' | sort -V | tail -1)"
fi
OUT_ROOT="$REPO/gamedata/$GAMEVER"
[ -d "$OUT_ROOT" ] || { echo "❌ no gamedata output for $GAMEVER"; exit 1; }
echo "==> Deploying gamedata/$GAMEVER outputs to local plugin repos"

deploy() {  # deploy <dist-file> <target-file>
    local dist="$1" target="$2"
    [ -f "$dist" ] || { echo "  ⚠️  missing dist: $dist - skipped"; return; }
    mkdir -p "$(dirname "$target")"
    if [ -f "$target" ] && cmp -s "$dist" "$target"; then
        echo "  = unchanged: $target"
        return
    fi
    cp -p "$target" "$target.bak.$(date +%Y%m%d_%H%M%S)" 2>/dev/null || true
    cp -p "$dist" "$target"
    echo "  ✔ deployed: $target"
}

deploy "$OUT_ROOT/weaponpaints/gamedata/weaponpaints.json" \
       "$HOME/customGIT/weaponpaints/gamedata/weaponpaints.json"

deploy "$OUT_ROOT/matchzy/gamedata/matchzy.json" \
       "$HOME/customGIT/matchzy/gamedata/matchzy.json"

echo "==> Done. Commit the updates inside each plugin repo."
