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
#
# Untracked local files that upstream now tracks also abort the merge before it
# starts ("untracked working tree files would be overwritten"). These are
# cleared automatically: byte-identical ones are simply deleted (upstream brings
# them back tracked), differing ones are copied to .sync_backup/<timestamp>/
# first and reported at the end so the richer side can be picked by hand
# (local analysis artifacts usually carry more data: func_sig, aliases).

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

# --- clear untracked files that upstream tracks (they abort the merge) --------
BACKUP_DIR=".sync_backup/$(date +%Y%m%d-%H%M%S)"
backed_up=()

echo "==> Checking untracked files against $REMOTE/$BRANCH..."
untracked_tmp="$(mktemp)"
upstream_tmp="$(mktemp)"
collide_tmp="$(mktemp)"
trap 'rm -f "$untracked_tmp" "$upstream_tmp" "$collide_tmp"' EXIT

git ls-files --others --exclude-standard | sort > "$untracked_tmp"
git ls-tree -r --name-only "$REMOTE/$BRANCH" | sort > "$upstream_tmp"
comm -12 "$untracked_tmp" "$upstream_tmp" > "$collide_tmp"

n_collide="$(wc -l < "$collide_tmp" | tr -d ' ')"
if [ "$n_collide" != "0" ]; then
    n_same=0
    while IFS= read -r path; do
        [ -n "$path" ] || continue
        if git cat-file blob "$REMOTE/$BRANCH:$path" 2>/dev/null | cmp -s - "$path"; then
            rm -f "$path"
            n_same=$((n_same + 1))
        else
            mkdir -p "$BACKUP_DIR/$(dirname "$path")"
            cp -p "$path" "$BACKUP_DIR/$path"
            rm -f "$path"
            backed_up+=("$path")
        fi
    done < "$collide_tmp"
    echo "   cleared $n_same identical, backed up ${#backed_up[@]} differing to $BACKUP_DIR"
fi

restore_backup() {
    [ "${#backed_up[@]}" -gt 0 ] || return 0
    echo "==> Restoring backed-up untracked files (merge did not complete)..." >&2
    for path in "${backed_up[@]}"; do
        mkdir -p "$(dirname "$path")"
        cp -p "$BACKUP_DIR/$path" "$path"
    done
}

echo "==> Attempting merge with upstream-wins conflict resolution..."
if git merge "$REMOTE/$BRANCH" --no-ff -X theirs -m "Merge $REMOTE/$BRANCH (theirs on conflict)"; then
    echo "✅ Merge complete (no conflicts, or auto-resolved via -X theirs)."
else
    echo "==> Structural conflicts left (-X theirs cannot resolve delete/modify). Forcing upstream state..."
    unresolved="$(git diff --name-only --diff-filter=U)"
    if [ -z "$unresolved" ]; then
        echo "❌ Merge failed with no conflicted paths — merge never started. Git's own output above has the reason (common cause: untracked or ignored working-tree files upstream also tracks)." >&2
        git merge --abort 2>/dev/null || true
        restore_backup
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

if [ "${#backed_up[@]}" -gt 0 ]; then
    echo "==> ${#backed_up[@]} untracked file(s) differed from upstream and were replaced by upstream's version."
    echo "    Backups: $BACKUP_DIR"
    echo "    Local copies often carry more data (func_sig, aliases, injected tasks) — review before discarding:"
    for path in "${backed_up[@]}"; do
        echo "      diff \"$BACKUP_DIR/$path\" \"$path\""
    done
fi

echo "==> Done. ./run_linux.sh regenerates gamedata for the new gamever."
