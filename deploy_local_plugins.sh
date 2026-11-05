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

# Pull each target repo before copying into it. They get commits from elsewhere
# (matchzy 13 and CounterStrikeSharp 15 behind on 14189), and commit_push only
# pulls when it has something to push - so on a build whose files did not change
# the clones were never refreshed, and check_deploy_drift compared against stale
# working copies that could not show a gamedata edit made upstream. A pull that
# fails (diverged history, no network) warns and the deploy goes on: commit_push
# rebases before it pushes, and fails the run if that does not work either.
pull_repo() {  # pull_repo <repo>
    local repo="$1"
    [ -d "$repo/.git" ] || return 0
    if git -C "$repo" pull -q --rebase --autostash 2>/dev/null; then
        echo "  ↓ pulled: $repo ($(git -C "$repo" log -1 --format=%h))"
    else
        git -C "$repo" rebase --abort 2>/dev/null || true
        echo "  ⚠️  could not pull $repo - deploying into the local copy"
    fi
}

for r in "$HOME/customGIT/weaponpaints" "$HOME/customGIT/matchzy" \
         "$HOME/customGIT/CleanerCS2" "$HOME/customGIT/MultiAddonManager" \
         "$HOME/customGIT/cs2-menus" "$HOME/customGIT/GameBanFix" \
         "$HOME/plugins/cs2-retakes-allocator"; do
    pull_repo "$r"
done
# CounterStrikeSharp is pulled by update_css_gamedata.sh, before its merge.

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

# CleanerCS2 reads addons/cleanercs2/gamedata.json; xmake packs package/ there.
deploy "$OUT_ROOT/cleanercs2/addons/cleanercs2/gamedata.json" \
       "$HOME/customGIT/CleanerCS2/package/gamedata.json"

# cs2-menus loads configs/signatures.ini (KeyValues). Generated as .txt, the
# suffix the gamedata contract and tooling treat as KeyValues.
deploy "$OUT_ROOT/cs2-menus/configs/signatures.txt" \
       "$HOME/customGIT/cs2-menus/configs/signatures.ini"

# GameBanFix (mrc4tt fork) packs gamedata/gamebanfix.games.txt into
# addons/gamebanfix/bin/<platform>/gamedata/ (its PackageScript).
deploy "$OUT_ROOT/gamebanfix/gamedata/gamebanfix.games.txt" \
       "$HOME/customGIT/GameBanFix/gamedata/gamebanfix.games.txt"

# Took over from rosetta (/root/rosetta, retired), which was the only thing
# refreshing it. (Ray-Trace, its other target, is archived: CounterStrikeSharp
# core implements ray tracing now.)
deploy "$OUT_ROOT/cs2-retakes-allocator/Resources/RetakesAllocator_gamedata.json" \
       "$HOME/plugins/cs2-retakes-allocator/Resources/RetakesAllocator_gamedata.json"

# MultiAddonManager reads no gamedata: its signatures and offsets are constexpr
# literals in src/multiaddonmanager.cpp. patch_mam_source.py rewrites only those
# literals from the generated file; a value it cannot place (an offset that differs
# per platform, a literal it cannot find) fails the deploy instead of guessing.
MAM_SOURCE="$HOME/customGIT/MultiAddonManager/src/multiaddonmanager.cpp"
MAM_FAILED=""
if [ -f "$MAM_SOURCE" ]; then
    (cd "$REPO" && uv run --quiet patch_mam_source.py -gamever "$GAMEVER" -source "$MAM_SOURCE") \
        || { echo "  ❌ could not patch $MAM_SOURCE"; MAM_FAILED=1; }
else
    echo "  ⚠️  missing: $MAM_SOURCE - skipped"
fi

# Commit and push exactly the generated path in a plugin repo, nothing else: a
# workflow being edited or a scratch file in the same repo is left as it is.
# The plugin repos get commits from elsewhere too (matchzy was three behind on
# 14186), so a push that is refused is retried once after a rebase; --autostash
# puts any unrelated local edits back afterwards. A repo that still cannot be
# pushed fails the deploy at the end, after the others were tried - gamedata
# that sits committed but unpushed is the state check_deploy_drift cannot see.
PUSH_FAILED=""

# The branch consumers install from: origin's HEAD (main, or CleanerCS2's master),
# else the current branch's upstream. A clone left on a work branch must not catch
# the gamedata commit: CounterStrikeSharp sat on test/frame-probe (no upstream) for
# 14196, the commit landed there, "origin/<branch>..HEAD" named no ref and read as
# "nothing to push", and record_deploy failed the build three ticks running.
deploy_branch() {  # deploy_branch <repo>
    local ref
    ref="$(git -C "$1" symbolic-ref -q --short refs/remotes/origin/HEAD 2>/dev/null || true)"
    if [ -z "$ref" ]; then
        git -C "$1" remote set-head origin -a >/dev/null 2>&1 || true
        ref="$(git -C "$1" symbolic-ref -q --short refs/remotes/origin/HEAD 2>/dev/null || true)"
    fi
    [ -z "$ref" ] && ref="$(git -C "$1" rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null || true)"
    case "$ref" in
        origin/*) echo "${ref#origin/}" ;;
        *) git -C "$1" branch --show-current ;;
    esac
}

# The checkout is on another branch (somebody's work): commit the working tree's copy
# of <path> on top of origin/<deploy branch> with plumbing - a private index,
# commit-tree, push sha:refs/heads/<branch> - so the checkout, its index and its
# branch are left exactly as they were. Retried once after a fetch when the remote
# moved in between. The local deploy branch follows when it is a fast-forward.
commit_push_aside() {  # commit_push_aside <repo> <path> <deploy branch> <checked-out>
    local repo="$1" path="$2" target="$3" current="$4" try base index tree commit f blob mode
    echo "  ↪ $repo is on ${current:-a detached HEAD}, not $target: committing $path onto origin/$target, checkout untouched"
    for try in 1 2; do
        if ! git -C "$repo" fetch -q origin "$target" 2>/dev/null; then
            echo "  ❌ could not fetch origin/$target in $repo"
            PUSH_FAILED="$PUSH_FAILED $repo"
            return 0
        fi
        base="$(git -C "$repo" rev-parse "refs/remotes/origin/$target")"
        index="$(mktemp)"
        GIT_INDEX_FILE="$index" git -C "$repo" read-tree "$base"
        while IFS= read -r f; do
            [ -f "$repo/$f" ] || continue
            blob="$(git -C "$repo" hash-object -w -- "$f")"
            mode=100644; [ -x "$repo/$f" ] && mode=100755
            GIT_INDEX_FILE="$index" git -C "$repo" update-index --add --cacheinfo "$mode,$blob,$f"
        done < <(git -C "$repo" ls-files -co --exclude-standard -- "$path")
        tree="$(GIT_INDEX_FILE="$index" git -C "$repo" write-tree)"
        rm -f "$index"
        if [ "$tree" = "$(git -C "$repo" rev-parse "$base^{tree}")" ]; then
            echo "  = nothing to push: $repo (origin/$target already carries $path)"
            return 0
        fi
        commit="$(git -C "$repo" commit-tree "$tree" -p "$base" \
                  -m "gamedata: $GAMEVER (auto-generated from CS2_VibeSignatures)")"
        if git -C "$repo" push -q origin "$commit:refs/heads/$target" 2>/dev/null; then
            git -C "$repo" update-ref "refs/remotes/origin/$target" "$commit"
            if git -C "$repo" merge-base --is-ancestor "refs/heads/$target" "$commit" 2>/dev/null; then
                git -C "$repo" update-ref "refs/heads/$target" "$commit"
            fi
            echo "  ✔ pushed onto $target: $repo (${commit:0:12})"
            return 0
        fi
    done
    echo "  ❌ push failed: cd $repo && git fetch origin && git log --oneline -3 origin/$target"
    PUSH_FAILED="$PUSH_FAILED $repo"
}

commit_push() {  # commit_push <repo> <path inside repo>
    local repo="$1" path="$2" branch target
    [ -d "$repo/.git" ] || { echo "  ⚠️  not a git repo: $repo - skipped"; return 0; }
    target="$(deploy_branch "$repo")"
    branch="$(git -C "$repo" branch --show-current)"
    if [ -z "$target" ] || [ "$branch" != "$target" ]; then
        [ -n "$target" ] || { echo "  ❌ no deploy branch in $repo (no origin/HEAD, detached)"; PUSH_FAILED="$PUSH_FAILED $repo"; return 0; }
        commit_push_aside "$repo" "$path" "$target" "$branch"
        return 0
    fi
    if [ -n "$(git -C "$repo" status --porcelain -- "$path")" ]; then
        git -C "$repo" add -- "$path"
        git -C "$repo" commit -q -m "gamedata: $GAMEVER (auto-generated from CS2_VibeSignatures)" -- "$path"
        echo "  ✔ committed: $repo ($path)"
    fi
    # also pushes a commit an earlier run made but could not push
    if git -C "$repo" rev-parse -q --verify "refs/remotes/origin/$branch" >/dev/null \
       && [ -z "$(git -C "$repo" log --oneline "origin/$branch..HEAD" -- "$path")" ]; then
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
commit_push "$HOME/customGIT/CleanerCS2" package/gamedata.json
commit_push "$HOME/customGIT/cs2-menus" configs/signatures.ini
commit_push "$HOME/customGIT/GameBanFix" gamedata/gamebanfix.games.txt
commit_push "$HOME/plugins/cs2-retakes-allocator" Resources/RetakesAllocator_gamedata.json
[ -n "$MAM_FAILED" ] || commit_push "$HOME/customGIT/MultiAddonManager" src/multiaddonmanager.cpp
# CounterStrikeSharp's file is written by update_css_gamedata.sh, which has to
# run first; only its gamedata file is ours there (configs/ also holds files a
# work branch may change, which a commit onto main must not carry along).
commit_push "$HOME/CounterStrikeSharp" configs/addons/counterstrikesharp/gamedata/gamedata.json

if [ -n "$MAM_FAILED" ]; then
    echo "==> Deployed, but MultiAddonManager's source was not patched"
    exit 1
fi
if [ -n "$PUSH_FAILED" ]; then
    echo "==> Deployed, but not pushed:$PUSH_FAILED"
    exit 1
fi
echo "==> Done. All plugin repos updated."
