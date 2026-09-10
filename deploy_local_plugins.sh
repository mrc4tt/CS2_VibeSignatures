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
    # No .bak: every target here is tracked in its plugin repo, so the previous
    # version is one `git show HEAD:<path>` away. Warn only if the target has
    # uncommitted edits, because those are the one thing git cannot give back.
    if [ -f "$target" ] && git -C "$(dirname "$target")" rev-parse --git-dir >/dev/null 2>&1 \
       && ! git -C "$(dirname "$target")" diff --quiet -- "$target" 2>/dev/null; then
        echo "  ⚠️  overwriting uncommitted changes in $target (not recoverable from git)"
    fi
    cp -p "$dist" "$target"
    echo "  ✔ deployed: $target"
}

deploy "$OUT_ROOT/weaponpaints/gamedata/weaponpaints.json" \
       "$HOME/customGIT/weaponpaints/gamedata/weaponpaints.json"

deploy "$OUT_ROOT/matchzy/gamedata/matchzy.json" \
       "$HOME/customGIT/matchzy/gamedata/matchzy.json"

# CounterStrikeSharp fork (deployed by update_css_gamedata.sh, commit here)
CSS_REPO="$HOME/CounterStrikeSharp"
if [ -d "$CSS_REPO/.git" ]; then
    cd "$CSS_REPO"
    if git diff --quiet -- configs/ && ! git ls-files --others --exclude-standard | grep -q .; then
        echo "  = unchanged: $CSS_REPO"
    else
        git add configs/
        git commit -m "gamedata: $GAMEVER (auto-generated from CS2_VibeSignatures)"
        git push origin main 2>/dev/null || git push origin master 2>/dev/null || echo "  ⚠️ push fejlede — koer manuelt: cd $CSS_REPO && git push"
        echo "  ✔ deployed: $CSS_REPO → github.com/mrc4tt/CounterStrikeSharp"
    fi
    cd - > /dev/null
fi

echo "==> Done. All plugin repos updated."
