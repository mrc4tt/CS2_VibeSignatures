#!/usr/bin/env bash
#
# update_hl2sdk_submodules.sh - keep every repository's mrc4tt/hl2sdk submodule on
# the newest commit of the branch its .gitmodules names, and commit + push the bump.
#
# The hl2sdk fork itself (~/hl2sdk) is not touched: this only moves the gitlink in
# the repositories that USE it (CounterStrikeSharp, CS2_VibeSignatures, ...).
#
# Usage:
#   ./update_hl2sdk_submodules.sh                 check and update every repository found
#   ./update_hl2sdk_submodules.sh --check         report only; exit 1 when one is behind
#   ./update_hl2sdk_submodules.sh --no-push       commit, but leave the push to you
#   ./update_hl2sdk_submodules.sh ~/CounterStrikeSharp   only the repositories given
#
# Without arguments it looks one level below $HOME and $HOME/customGIT for a
# .gitmodules naming mrc4tt/hl2sdk. CI runner checkouts (any path with /_work/)
# are skipped: the runner owns them and resets them on every job.
#
# A repository is left alone, with the reason printed, when its branch cannot be
# fast-forwarded to its upstream, the submodule has local changes, HEAD is
# detached, or the newest commit is not a descendant of the recorded one (a bump
# must never move the SDK backwards or sideways).
set -uo pipefail

SDK_URL_RE='github\.com[:/]mrc4tt/hl2sdk(\.git)?/?$'
CHECK=0
PUSH=1
REPOS=()
for arg in "$@"; do
    case "$arg" in
        --check)   CHECK=1 ;;
        --no-push) PUSH=0 ;;
        -h|--help) sed -n '2,24p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        -*)        echo "unknown option: $arg" >&2; exit 2 ;;
        *)         REPOS+=("$(realpath "$arg")") ;;
    esac
done

if [ ${#REPOS[@]} -eq 0 ]; then
    for dir in "$HOME"/* "$HOME"/customGIT/*; do
        [ -f "$dir/.gitmodules" ] || continue
        case "$dir" in */_work/*) continue ;; esac
        git config -f "$dir/.gitmodules" --get-regexp '^submodule\..*\.url$' 2>/dev/null \
            | grep -Eq "$SDK_URL_RE" && REPOS+=("$dir")
    done
fi
[ ${#REPOS[@]} -gt 0 ] || { echo "no repository uses mrc4tt/hl2sdk as a submodule"; exit 0; }

behind=0
failed=0

# The superproject's branch first: a bump committed on a stale branch could not be
# pushed, and the branch may already carry a newer pointer from elsewhere.
sync_superproject() {  # $1=repo
    local repo="$1" branch upstream
    branch=$(git -C "$repo" symbolic-ref -q --short HEAD) || { echo "  skip: HEAD is detached"; return 1; }
    upstream=$(git -C "$repo" rev-parse -q --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null) || {
        echo "  note: $branch has no upstream; working on the local branch"
        return 0
    }
    # --no-recurse-submodules: a submodule pinned to a commit its remote no longer
    # serves (CounterStrikeSharp's metamod-source) would fail the whole fetch.
    git -C "$repo" fetch -q --no-recurse-submodules "${upstream%%/*}" || { echo "  skip: fetch of $upstream failed"; return 1; }
    if ! git -C "$repo" merge-base --is-ancestor "$upstream" HEAD; then
        if [ "$CHECK" = 1 ]; then
            echo "  note: $branch is behind $upstream (not pulled in --check)"
        elif ! git -C "$repo" merge -q --ff-only "$upstream" 2>/dev/null; then
            echo "  skip: $branch cannot fast-forward to $upstream (diverged, or local changes in the way)"
            return 1
        else
            echo "  pulled $branch up to $upstream"
        fi
    fi
}

for repo in "${REPOS[@]}"; do
    echo "== $repo"
    [ -d "$repo/.git" ] || [ -f "$repo/.git" ] || { echo "  skip: not a git repository"; continue; }
    sync_superproject "$repo" || { failed=1; continue; }

    while read -r key url; do
        name=${key#submodule.}; name=${name%.url}
        echo "$url" | grep -Eq "$SDK_URL_RE" || continue
        path=$(git -C "$repo" config -f .gitmodules "submodule.$name.path")
        branch=$(git -C "$repo" config -f .gitmodules "submodule.$name.branch" || echo cs2)
        sub="$repo/$path"

        latest=$(git ls-remote "$url" "refs/heads/$branch" | cut -f1)
        [ -n "$latest" ] || { echo "  $path: skip, $url has no branch $branch"; failed=1; continue; }
        recorded=$(git -C "$repo" ls-tree HEAD -- "$path" | awk '{print $3}')

        if [ "$recorded" = "$latest" ]; then
            echo "  $path: up to date (${latest:0:8}, $branch)"
            # Pointer is current; make the checkout match it when that is safe.
            if [ "$CHECK" = 0 ] && [ -e "$sub/.git" ] && [ "$(git -C "$sub" rev-parse HEAD 2>/dev/null)" != "$latest" ] \
                && [ -z "$(git -C "$sub" status --porcelain --untracked-files=no)" ]; then
                git -C "$repo" submodule update -q --init -- "$path" && echo "  $path: checkout moved to ${latest:0:8}"
            fi
            continue
        fi

        behind=1
        if [ "$CHECK" = 1 ]; then
            echo "  $path: BEHIND - recorded ${recorded:0:8}, $branch is at ${latest:0:8}"
            continue
        fi

        [ -e "$sub/.git" ] || git -C "$repo" submodule update -q --init -- "$path" \
            || { echo "  $path: skip, could not initialise the submodule"; failed=1; continue; }
        if [ -n "$(git -C "$sub" status --porcelain --untracked-files=no)" ]; then
            echo "  $path: skip, the submodule has local changes"; failed=1; continue
        fi
        # From the URL .gitmodules names, not a remote: the checkout's remote may be
        # called anything (CounterStrikeSharp's is "fork").
        git -C "$sub" fetch -q "$url" "$branch" || { echo "  $path: skip, fetch failed"; failed=1; continue; }
        if [ -n "$recorded" ] && ! git -C "$sub" merge-base --is-ancestor "$recorded" "$latest" 2>/dev/null; then
            echo "  $path: skip, ${latest:0:8} is not a descendant of the recorded ${recorded:0:8}"; failed=1; continue
        fi

        log=$(git -C "$sub" log --oneline --no-decorate "${recorded:+$recorded..}$latest" | head -20)
        count=$(git -C "$sub" rev-list --count "${recorded:+$recorded..}$latest")
        git -C "$sub" checkout -q --detach "$latest" || { echo "  $path: skip, checkout failed"; failed=1; continue; }
        git -C "$repo" add -- "$path"
        # Only this path: whatever else is staged or modified stays as it was.
        printf 'chore(hl2sdk): bump %s to mrc4tt/hl2sdk %s %s\n\n%s commit(s):\n%s\n' \
            "$path" "$branch" "${latest:0:8}" "$count" "$log" \
            | git -C "$repo" commit -q -F - -- "$path" \
            || { echo "  $path: commit failed"; failed=1; continue; }
        echo "  $path: bumped ${recorded:0:8} -> ${latest:0:8} ($count commit(s))"

        if [ "$PUSH" = 1 ] && git -C "$repo" rev-parse -q --verify '@{u}' >/dev/null 2>&1; then
            if git -C "$repo" push -q 2>/dev/null \
                || { git -C "$repo" pull -q --rebase --autostash --no-recurse-submodules && git -C "$repo" push -q; }; then
                echo "  pushed"
            else
                echo "  push FAILED - the commit is local; push it by hand"; failed=1
            fi
        fi
    done < <(git -C "$repo" config -f .gitmodules --get-regexp '^submodule\..*\.url$')
done

if [ "$CHECK" = 1 ]; then exit "$behind"; fi
exit "$failed"
