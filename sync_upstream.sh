#!/bin/bash
#
# sync_upstream.sh — merge upstream/main into the fork, fully auto-resolved.
#
# Conflict policy: upstream wins every content conflict (-X theirs keeps
# non-conflicting local changes). Leftover structural conflicts (delete/modify,
# add/add) are forced to upstream's state as well: files upstream still has are
# taken from upstream/main, files upstream deleted are removed locally.
#
# After every merge the WeaponPaints symbol tasks are re-injected into the
# newest analysis config — upstream configs overwrite the injected find-tasks,
# and ensure_weaponpaints_symbols.py is idempotent per symbol.
#
# NOTE: uncommitted changes to tracked files block the merge (git refuses);
# commit or stash first — the script aborts with a clear message otherwise.

set -euo pipefail
cd "$(dirname "$0")"

# Paths this fork owns outright — always restored to the pre-merge state after a
# merge, regardless of conflict resolution (belt-and-suspenders on top of the
# merge=ours gitattributes entry, which needs the local git config:
#   git config merge.ours.driver true
PROTECTED_PATHS=(
    .github/workflows/deploy-pages.yml
    gamedata
    gamesymbols
)

REMOTE="${REMOTE:-upstream}"
BRANCH="${BRANCH:-main}"

git fetch "$REMOTE"
PREV="$(git rev-parse HEAD)"

if ! git diff --quiet || ! git diff --cached --quiet; then
    echo "❌ Uncommitted changes present — commit or stash first (git refuses to merge otherwise):"
    git status --short | head -20
    exit 1
fi

echo "==> Attempting merge with upstream-wins conflict resolution..."
if git merge "$REMOTE/$BRANCH" --no-ff -X theirs -m "Merge $REMOTE/$BRANCH (theirs on conflict)"; then
    echo "✅ Merge complete (no conflicts, or auto-resolved via -X theirs)."
else
    echo "==> Structural conflicts left (-X theirs cannot resolve delete/modify). Forcing upstream state..."
    unresolved="$(git diff --name-only --diff-filter=U)"
    if [ -z "$unresolved" ]; then
        echo "❌ Merge failed for an unknown reason — inspect manually." >&2
        exit 1
    fi
    for path in $unresolved; do
        if git cat-file -e "$REMOTE/$BRANCH:$path" 2>/dev/null; then
            echo "   theirs: $path"
            git checkout "$REMOTE/$BRANCH" -- "$path"
            git add "$path"
        else
            echo "   removed upstream, deleting locally: $path"
            git rm -f -q "$path"
        fi
    done
    git commit -m "Merge $REMOTE/$BRANCH (auto-resolved: upstream state forced)"
    echo "✅ Merge complete (conflicts auto-resolved)."
fi

echo "==> Re-injecting local gamedata symbols + agent-fallback skills into newest config..."
uv run ensure_local_gamedata_symbols.py || echo "  warning: seed-injection failed (run manually)"
uv run ensure_agent_fallback_skills.py || echo "  warning: fallback-skill generation failed (run manually)"

echo "==> Restoring protected fork-owned paths..."
for path in "${PROTECTED_PATHS[@]}"; do
    if git cat-file -e "$PREV:$path" 2>/dev/null && ! git diff --quiet "$PREV" HEAD -- "$path"; then
        git checkout "$PREV" -- "$path"
        git commit --amend --no-edit
        echo "   kept ours: $path"
    fi
done

echo "==> Done. ./run_linux.sh regenerates gamedata for the new gamever."
