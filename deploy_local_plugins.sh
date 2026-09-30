#!/bin/bash
#
# deploy_local_plugins.sh — copy generated gamedata outputs into the local plugin
# repos, so each plugin repo's gamedata file stays current with the newest analysis.
#
# Usage: ./deploy_local_plugins.sh [GAMEVER]   (default: newest under gamedata/)
#
# Each changed file is then committed and pushed in its plugin repo (that path
# only). Run update_css_gamedata.sh first: it writes the CounterStrikeSharp file
# this script commits.

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
    # Byte-exact except for the final newline. A plugin repo's web editor strips
    # it on save, which made an untouched file look changed on every run and get
    # rewritten for one byte no JSON parser can see. `sed -e '$a\\'` appends the
    # newline only when it is missing, so nothing else is forgiven.
    if [ -f "$target" ] \
       && [ "$(sed -e '$a\' "$dist" | sha256sum | cut -d' ' -f1)" \
          = "$(sed -e '$a\' "$target" | sha256sum | cut -d' ' -f1)" ]; then
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

# Commit and push exactly the generated path in a plugin repo, nothing else: a
# workflow being edited or a scratch file in the same repo is left as it is.
# The plugin repos get commits from elsewhere too (matchzy was three behind on
# 14186), so a push that is refused is retried once after a rebase; --autostash
# puts any unrelated local edits back afterwards. A repo that still cannot be
# pushed fails the deploy at the end, after the others were tried - gamedata
# that sits committed but unpushed is the state check_deploy_drift cannot see.
PUSH_FAILED=""
commit_push() {  # commit_push <repo> <path inside repo>
    local repo="$1" path="$2" branch
    [ -d "$repo/.git" ] || { echo "  ⚠️  not a git repo: $repo - skipped"; return 0; }
    if [ -n "$(git -C "$repo" status --porcelain -- "$path")" ]; then
        git -C "$repo" add -- "$path"
        git -C "$repo" commit -q -m "gamedata: $GAMEVER (auto-generated from CS2_VibeSignatures)" -- "$path"
        echo "  ✔ committed: $repo ($path)"
    fi
    branch="$(git -C "$repo" branch --show-current)"
    [ -n "$branch" ] || { echo "  ⚠️  detached HEAD in $repo - not pushed"; PUSH_FAILED="$PUSH_FAILED $repo"; return 0; }
    # also pushes a commit an earlier run made but could not push
    if [ -z "$(git -C "$repo" log --oneline "origin/$branch..HEAD" -- "$path" 2>/dev/null)" ]; then
        echo "  = nothing to push: $repo"
        return 0
    fi
    if git -C "$repo" push -q origin "$branch" 2>/dev/null; then
        echo "  ✔ pushed: $repo"
        return 0
    fi
    if git -C "$repo" pull -q --rebase --autostash origin "$branch" 2>/dev/null \
       && git -C "$repo" push -q origin "$branch" 2>/dev/null; then
        echo "  ✔ pushed after rebase: $repo"
        return 0
    fi
    git -C "$repo" rebase --abort 2>/dev/null || true
    echo "  ❌ push failed: cd $repo && git status -sb && git pull --rebase && git push"
    PUSH_FAILED="$PUSH_FAILED $repo"
}

commit_push "$HOME/customGIT/weaponpaints" gamedata/weaponpaints.json
commit_push "$HOME/customGIT/matchzy" gamedata/matchzy.json
# CounterStrikeSharp's file is written by update_css_gamedata.sh, which has to
# run first; only configs/ is ours there.
commit_push "$HOME/CounterStrikeSharp" configs/

if [ -n "$PUSH_FAILED" ]; then
    echo "==> Deployed, but not pushed:$PUSH_FAILED"
    exit 1
fi
echo "==> Done. All plugin repos updated."
