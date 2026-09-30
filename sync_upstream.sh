#!/bin/bash
#
# sync_upstream.sh — merge upstream/main into the fork without losing the fork.
#
#   ./sync_upstream.sh              start a merge
#   ./sync_upstream.sh --continue   finish one that stopped for hand resolution
#
# The earlier version merged with `-X theirs`, so upstream won every conflicting
# hunk in every file. That was right while upstream produced the artifacts and
# this fork only patched configs. It stopped being right once the fork analysed
# gamevers itself: replayed without -X on 2026-09-30 the merge had 3060
# conflicted files, of which 3040 were this fork's own artifacts (1284 on 14182
# alone), and in ida_analyze_bin.py upstream's import block replaced the fork's,
# dropping `import functools` — the module no longer imported and nothing said
# so until the test suite was run by hand.
#
# So the merge is a plain one now, and each conflicted path is resolved by the
# class it falls in:
#
#   PROTECTED_PATHS      ours, exactly. Upstream's additions inside are removed.
#   ADDITIVE_PATHS       ours for every file the fork already has; files only
#                        upstream has arrive. A gamever this fork never analysed
#                        therefore still comes in whole.
#   THEIRS_ON_CONFLICT   upstream wins the conflicting hunks, local changes
#                        outside them are kept. Only for files whose fork-side
#                        state is replayed from a table afterwards
#                        (ensure_local_gamedata_symbols.py).
#   everything else      code. The script stops, leaves the conflict markers and
#                        waits for --continue. Nothing is guessed.
#
# Two gates follow. Before the merge commit: no conflict markers left, the two
# analysis modules import, and no undefined name in any Python file both sides
# changed — failing here leaves an uncommitted merge, so `git merge --abort`
# undoes it cleanly. After the commit and the table replay: the test suite.
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
export LC_ALL=C

# Paths this fork owns outright — restored to the pre-merge state, regardless of
# how the merge resolved them (belt-and-suspenders on top of the merge=ours
# gitattributes entries, which need the local git config:
#   git config merge.ours.driver true
#
# `pages` is here because this fork rewrites the site app. Protection is exact:
# files upstream adds inside a protected path are removed again, so the path
# never ends up half ours and half theirs. The trade is that upstream's own
# pages work never arrives on its own, which is why the script prints what it
# declined and how to cherry-pick it.
PROTECTED_PATHS=(
    .github/workflows/deploy-pages.yml
    # The hl2sdk submodule. This fork points it at mrc4tt/hl2sdk branch cs2
    # (hzqst's cs2_vibe vtable fixes merged onto a current alliedmodders/cs2)
    # while upstream points it at HLND2T/hl2sdk branch cs2_vibe. Both the URL
    # in .gitmodules and the gitlink itself are plain content to a merge, so
    # without this every sync would hand the vtable headers back -- and
    # cpp_tests derives vfunc_index from exactly those headers.
    .gitmodules
    hl2sdk_cs2
    gamedata
    gamesymbols
    pages
    # Generators this fork disabled (MODULE_ENABLED = False). A silent flip back
    # to True would put five unwanted plugins back into every gamedata run
    # without anything failing.
    gamedata-generators/swiftlys2/gamedata.py
    gamedata-generators/plugify-plugin-s2sdk/gamedata.py
    gamedata-generators/modsharp-public/gamedata.py
    gamedata-generators/cs2surf/gamedata.py
    gamedata-generators/cs2kz-metamod/gamedata.py
)

# What the fork's own runs produce. An artifact the fork has was validated
# against the binary by the fork's battery; upstream's version of the same file
# is a second opinion, not a correction, and is listed at the end for review.
ADDITIVE_PATHS=(
    bin_artifacts
    binary_locks
)

# Upstream wins the conflicting hunks. The fork's config decisions live in the
# tables of ensure_local_gamedata_symbols.py and are replayed after the merge,
# so nothing here is lost by losing a hunk.
THEIRS_ON_CONFLICT=(
    configs
    download.yaml
)

REMOTE="${REMOTE:-upstream}"
BRANCH="${BRANCH:-main}"

MODE=start
case "${1:-}" in
    "") ;;
    --continue) MODE=continue ;;
    *) echo "usage: $0 [--continue]" >&2; exit 64 ;;
esac

in_list() {
    # in_list <path> <entry>... — path is an entry or lies below one
    local path="$1" entry
    shift
    for entry in "$@"; do
        [ "$path" = "$entry" ] && return 0
        case "$path" in "$entry"/*) return 0 ;; esac
    done
    return 1
}

# ls-tree, not `cat-file -e <rev>:<path>`: a submodule gitlink names a commit
# that lives in the submodule's object store, so cat-file calls it absent. That
# is how hl2sdk_cs2 was once deleted as "removed upstream" and then skipped by
# the restore as "absent before the merge".
in_tree() { [ -n "$(git ls-tree "$1" -- "$2")" ]; }

tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT

BACKUP_DIR=".sync_backup/$(date +%Y%m%d-%H%M%S)"
backed_up=()

restore_backup() {
    [ "${#backed_up[@]}" -gt 0 ] || return 0
    echo "==> Restoring backed-up untracked files (merge did not complete)..." >&2
    for path in "${backed_up[@]}"; do
        mkdir -p "$(dirname "$path")"
        cp -p "$BACKUP_DIR/$path" "$path"
    done
}

report_backup() {
    [ "${#backed_up[@]}" -gt 0 ] || return 0
    echo "==> ${#backed_up[@]} untracked file(s) differed from upstream and were replaced by upstream's version."
    echo "    Backups: $BACKUP_DIR"
    echo "    Local copies often carry more data (func_sig, aliases, injected tasks) — review before discarding:"
    for path in "${backed_up[@]}"; do
        echo "      diff \"$BACKUP_DIR/$path\" \"$path\""
    done
}

# ------------------------------------------------------------------------------
# start: fetch, clear colliding untracked files, merge, resolve by class
# ------------------------------------------------------------------------------
if [ "$MODE" = start ]; then
    if git rev-parse -q --verify MERGE_HEAD >/dev/null; then
        echo "❌ A merge is already in progress. Finish it with: $0 --continue" >&2
        echo "   or drop it with: git merge --abort" >&2
        exit 1
    fi

    git fetch "$REMOTE"

    if ! git diff --quiet || ! git diff --cached --quiet; then
        echo "❌ Uncommitted changes present — commit or stash first (git refuses to merge otherwise):"
        git status --short | head -20
        exit 1
    fi

    if git merge-base --is-ancestor "$REMOTE/$BRANCH" HEAD; then
        echo "✅ Already up to date with $REMOTE/$BRANCH."
        exit 0
    fi

    # --- clear untracked files that upstream tracks (they abort the merge) ----
    echo "==> Checking untracked files against $REMOTE/$BRANCH..."
    git ls-files --others --exclude-standard | sort > "$tmpdir/untracked"
    git ls-tree -r --name-only "$REMOTE/$BRANCH" | sort > "$tmpdir/upstream"
    comm -12 "$tmpdir/untracked" "$tmpdir/upstream" > "$tmpdir/collide"

    if [ -s "$tmpdir/collide" ]; then
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
        done < "$tmpdir/collide"
        echo "   cleared $n_same identical, backed up ${#backed_up[@]} differing to $BACKUP_DIR"
    fi

    echo "==> Merging $REMOTE/$BRANCH (plain merge, conflicts resolved by path class)..."
    git merge "$REMOTE/$BRANCH" --no-ff --no-commit > "$tmpdir/merge.log" 2>&1 || true
    if ! git rev-parse -q --verify MERGE_HEAD >/dev/null; then
        grep -v '^Auto-merging ' "$tmpdir/merge.log" | tail -20 >&2
        echo "❌ The merge never started. Git's own output above has the reason (common cause: untracked or ignored working-tree files upstream also tracks)." >&2
        restore_backup
        exit 1
    fi
    report_backup
fi

if ! git rev-parse -q --verify MERGE_HEAD >/dev/null; then
    echo "❌ No merge in progress — nothing to continue. Start one with: $0" >&2
    exit 1
fi

PREV="$(git rev-parse HEAD)"
UP="$(git rev-parse MERGE_HEAD)"
BASE="$(git merge-base "$PREV" "$UP")"

# --- resolve what has a policy; collect what does not -------------------------
git diff --name-only --diff-filter=U | sort > "$tmpdir/conflicted"
git ls-tree -r --name-only "$PREV" | sort > "$tmpdir/prev_files"

: > "$tmpdir/ours_keep"
n_ours=0; n_theirs=0
hand=()
while IFS= read -r path; do
    [ -n "$path" ] || continue
    if in_list "$path" "${PROTECTED_PATHS[@]}" "${ADDITIVE_PATHS[@]}"; then
        # Ours. A file the fork does not have (deleted here, modified upstream)
        # stays deleted: the deletion was the fork's decision.
        if grep -Fxq -- "$path" "$tmpdir/prev_files"; then
            printf '%s\n' "$path" >> "$tmpdir/ours_keep"
        else
            git rm -f -q -- "$path"
        fi
        n_ours=$((n_ours + 1))
    elif in_list "$path" "${THEIRS_ON_CONFLICT[@]}"; then
        if [ "$(git ls-files -u -- "$path" | wc -l)" = 3 ]; then
            # A content conflict: redo the three-way merge of this one file with
            # upstream winning the conflicting hunks only.
            git show ":1:$path" > "$tmpdir/base"
            git show ":2:$path" > "$tmpdir/ours"
            git show ":3:$path" > "$tmpdir/theirs"
            git merge-file -q --theirs "$tmpdir/ours" "$tmpdir/base" "$tmpdir/theirs"
            cat "$tmpdir/ours" > "$path"
            git add -- "$path"
        elif in_tree "$UP" "$path"; then
            git checkout "$UP" -- "$path"
        else
            git rm -f -q -- "$path"
        fi
        n_theirs=$((n_theirs + 1))
    else
        hand+=("$path")
    fi
done < "$tmpdir/conflicted"

if [ -s "$tmpdir/ours_keep" ]; then
    GIT_LITERAL_PATHSPECS=1 git checkout "$PREV" --pathspec-from-file="$tmpdir/ours_keep"
fi
[ "$((n_ours + n_theirs))" -gt 0 ] && echo "   conflicts resolved by policy: $n_ours kept ours, $n_theirs upstream's hunks"

if [ "${#hand[@]}" -gt 0 ]; then
    echo
    echo "⏸  ${#hand[@]} conflicted path(s) have no policy — this is code, resolve it by hand:"
    for path in "${hand[@]}"; do
        if [ -f "$path" ]; then
            echo "     $path  ($(grep -c '^<<<<<<< ' "$path" || true) hunk(s))"
        else
            echo "     $path  (deleted on one side, or a submodule)"
        fi
    done
    echo
    echo "   Each hunk shows both sides between <<<<<<< and >>>>>>>. Keep what the fork"
    echo "   added AND what upstream added; an import block is the usual place where"
    echo "   both are needed. Then:"
    echo "     git add <each file>"
    echo "     $0 --continue"
    echo "   To give up instead: git merge --abort"
    exit 2
fi

# --- restore fork-owned paths (before the commit, so the merge commit is right)
echo "==> Restoring fork-owned paths..."
declared=()
for path in "${PROTECTED_PATHS[@]}"; do
    in_tree "$PREV" "$path" || { echo "   skipped (absent before the merge): $path"; continue; }
    git diff --cached --quiet "$PREV" -- "$path" && continue

    # A gitlink is one entry, not a tree: restore the entry and re-check-out the
    # submodule, which the merge may have moved or removed.
    if [ "$(git ls-tree "$PREV" -- "$path" | awk '{print $1}')" = "160000" ]; then
        git checkout "$PREV" -- "$path"
        git submodule update --init -- "$path" >/dev/null 2>&1 \
            || echo "     warning: submodule checkout failed, run: git submodule update --init -- $path" >&2
        echo "   kept ours (submodule gitlink): $path"
        declared+=("$path")
        continue
    fi

    # Exact restore: bring back everything the fork had, then remove what
    # upstream added inside the path. Done per file rather than by deleting the
    # directory, which would also take ignored content with it (pages/node_modules).
    git checkout "$PREV" -- "$path"
    git diff --cached --no-renames --name-only --diff-filter=A "$PREV" -- "$path" > "$tmpdir/added"
    if [ -s "$tmpdir/added" ]; then
        GIT_LITERAL_PATHSPECS=1 git rm -f -q --pathspec-from-file="$tmpdir/added"
    fi
    echo "   kept ours: $path"
    declared+=("$path")
done

for path in "${ADDITIVE_PATHS[@]}"; do
    in_tree "$PREV" "$path" || continue
    git checkout "$PREV" -- "$path"
    n_new="$(git diff --cached --no-renames --name-only --diff-filter=A "$PREV" -- "$path" | wc -l | tr -d ' ')"
    # Declined = upstream changed the file since the common ancestor and its
    # version is not the one the fork keeps.
    git diff --no-renames --name-only "$BASE" "$UP" -- "$path" | sort > "$tmpdir/up_changed"
    git diff --no-renames --name-only --diff-filter=M "$PREV" "$UP" -- "$path" | sort > "$tmpdir/differs"
    n_declined="$(comm -12 "$tmpdir/up_changed" "$tmpdir/differs" | wc -l | tr -d ' ')"
    echo "   kept ours, added upstream's new files: $path  (+$n_new new, $n_declined upstream change(s) declined)"
    if [ "$n_declined" != 0 ]; then
        echo "     list:   comm -12 <(git diff --name-only $BASE $UP -- $path | sort) <(git diff --name-only --diff-filter=M $PREV $UP -- $path | sort)"
        echo "     adopt:  git checkout $UP -- $path/<file>"
    fi
done

if [ "${#declared[@]}" -gt 0 ]; then
    echo
    echo "==> What upstream changed in the protected paths, and this merge declined:"
    for path in "${declared[@]}"; do
        stat="$(git diff --stat "$PREV" "$UP" -- "$path" | tail -1)"
        [ -n "$stat" ] || continue
        echo "   $path: ${stat# }"
        echo "     review: git diff $PREV $UP -- $path"
        echo "     adopt:  git checkout $UP -- $path/<file>"
    done
    echo "   Keeping ours is the policy for these paths, not a verdict on upstream's"
    echo "   version. Cherry-pick anything worth having."
fi

# --- gate 1: the merged tree, before anything is committed --------------------
gate_failed() {
    echo
    echo "❌ $1" >&2
    echo "   The merge is NOT committed. Fix it, git add, then: $0 --continue" >&2
    echo "   To give up instead: git merge --abort" >&2
    exit 3
}

echo "==> Gate 1: merged tree..."
if ! git diff --quiet; then
    echo "   unstaged changes (resolved by hand but not added?):" >&2
    git diff --name-only | head -20 >&2
    gate_failed "Unstaged changes in the merge."
fi

# Files the merge touched, outside the two big data trees.
git diff --cached --no-renames --name-only --diff-filter=AM "$PREV" -- . \
    ':(exclude)bin_artifacts' ':(exclude)pages' ':(exclude)gamedata' ':(exclude)gamesymbols' \
    > "$tmpdir/touched"
markers="$(xargs -r -d '\n' grep -lE '^(<<<<<<<|>>>>>>>) ' -- < "$tmpdir/touched" 2>/dev/null || true)"
if [ -n "$markers" ]; then
    echo "$markers" | sed 's/^/     /' >&2
    gate_failed "Conflict markers left in the files above."
fi

uv run python -c "import ida_analyze_bin, ida_analyze_util" \
    || gate_failed "ida_analyze_bin / ida_analyze_util no longer import."

# A lost hunk that is not at module level (a name used inside a function)
# imports fine and fails at run time, so lint exactly the files where a hunk
# could have been lost: Python both sides changed.
comm -12 <(git diff --name-only "$BASE" "$PREV" -- '*.py' | sort) \
         <(git diff --name-only "$BASE" "$UP" -- '*.py' | sort) \
    | while IFS= read -r f; do [ -f "$f" ] && printf '%s\n' "$f"; done > "$tmpdir/both_py" || true
if [ -s "$tmpdir/both_py" ]; then
    rc=0
    xargs -d '\n' uv run --with ruff ruff check --no-cache --select F821,F823 --output-format concise \
        < "$tmpdir/both_py" || rc=$?
    case "$rc" in
        0) ;;
        1) gate_failed "Undefined names in files both sides changed (a hunk was lost in the merge)." ;;
        *) echo "   warning: ruff could not run (exit $rc) — undefined-name check skipped" >&2 ;;
    esac
fi
echo "   ok: no markers, modules import, no undefined names in $(wc -l < "$tmpdir/both_py" | tr -d ' ') both-sides Python file(s)"

git commit -q -m "Merge $REMOTE/$BRANCH (fork-owned paths kept, configs take upstream's hunks)"
echo "✅ Merge committed: $(git rev-parse --short HEAD)"

# --- replay the fork's tables onto upstream's configs -------------------------
echo "==> Re-injecting local gamedata symbols + agent-fallback skills into newest config..."
uv run ensure_local_gamedata_symbols.py || echo "  warning: seed-injection failed (run manually)"
uv run ensure_agent_fallback_skills.py || echo "  warning: fallback-skill generation failed (run manually)"

# --- gate 2: the test suite, with the tables replayed -------------------------
if [ "${SYNC_SKIP_TESTS:-0}" = 1 ]; then
    echo "==> Gate 2 skipped (SYNC_SKIP_TESTS=1)."
else
    echo "==> Gate 2: test suite..."
    if ! uv run --with pytest --with pyyaml --with capstone python -m pytest tests/ -q -p no:cacheprovider \
            > "$tmpdir/pytest.log" 2>&1; then
        mkdir -p .sync_backup
        cp "$tmpdir/pytest.log" .sync_backup/pytest-last.log
        tail -25 "$tmpdir/pytest.log" >&2
        echo >&2
        echo "❌ The test suite fails on the merged tree (full log: .sync_backup/pytest-last.log)." >&2
        echo "   The merge IS committed locally and is not pushed. Fix forward, or undo with:" >&2
        echo "     git reset --hard $PREV && git submodule update --init" >&2
        echo "   (the replay also wrote uncommitted config changes and untracked" >&2
        echo "    .claude/skills/ directories; git status --short lists them)" >&2
        exit 4
    fi
    echo "   $(tail -1 "$tmpdir/pytest.log")"
fi

echo "==> Done. Next: uv run abi_guard.py -gamever <VER> --fix on every gamever, then the"
echo "    verification battery. ./run_linux.sh regenerates gamedata for a new gamever."
