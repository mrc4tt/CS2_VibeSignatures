#!/usr/bin/env bash
#
# sdk_abi_fix.sh - have an agent fix the hl2sdk fork's headers after a game update moved
# a vtable slot or a layout, and open the pull request on mrc4tt/hl2sdk.
#
# sdk_abi_check.sh reports the NEW mismatches; this script hands them to a headless agent
# working in a throwaway worktree of the fork (~/hl2sdk itself is not touched), then
# checks the agent's commits itself before anything leaves the machine:
#
#   1. only headers and sources under public/ and game/ changed
#   2. sdk_abi_check.sh on the fixed commit: nothing new, or only accepted mismatches
#      that moved index (the same line once its numbers are ignored)
#   3. ./local-ci.sh linux and ./local-ci.sh windows build
#
# Only then is the branch fix/abi-<gamever> pushed and a pull request opened against the
# fork's cs2 branch. It is never merged here: a wrong slot crashes every plugin, so a
# person reads the PR. After merging, run update_hl2sdk_submodules.sh and
# sdk_abi_check.sh <gamever> (--accept when only indexes moved). Nothing is ever sent to
# alliedmodders/s2sdk; its open pull requests are only read, as a candidate fix.
#
# Usage:
#   ./sdk_abi_fix.sh                 newest configs/<gamever>.yaml
#   ./sdk_abi_fix.sh 14201
#   ./sdk_abi_fix.sh 14201 --dry-run   everything but the push and the pull request
#   SDK_BASE=<commit> ./sdk_abi_fix.sh  start from that fork commit instead of the cs2 head
#
# Environment: SDK_REPO (~/hl2sdk), SDK_FIX_AGENT (claude), SDK_FIX_MODEL, SDK_FIX_TIMEOUT
# (seconds, 3600), SDK_FIX_STATE (.autopilot), BINARIES (/srv/cs2-binaries).
#
# Exit: 0 pull request opened (or already open, or nothing to fix), 1 the fix was
# rejected by a check, 2 no usable setup.

set -uo pipefail
cd "$(dirname "$0")"
REPO=$PWD

GAMEVER=""
DRY_RUN=0
for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=1 ;;
        -h|--help) sed -n '3,31p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        -*) echo "unknown option $arg" >&2; exit 2 ;;
        *) GAMEVER="$arg" ;;
    esac
done
[ -n "$GAMEVER" ] || GAMEVER=$(ls configs/*.yaml | sed 's|configs/||; s|\.yaml$||' | sort -V | tail -1)

SDK_REPO="${SDK_REPO:-$HOME/hl2sdk}"
SDK_SLUG="mrc4tt/hl2sdk"
SDK_BRANCH="cs2"
AGENT="${SDK_FIX_AGENT:-claude}"
TIMEOUT="${SDK_FIX_TIMEOUT:-3600}"
STATE="${SDK_FIX_STATE:-$REPO/.autopilot}"
BINARIES="${BINARIES:-/srv/cs2-binaries}"
BRANCH="fix/abi-$GAMEVER"
WORKTREE="$STATE/hl2sdk-fix-$GAMEVER"
LOG="$STATE/sdk-abi-fix-$GAMEVER"

say() { printf '%s\n' "$*"; }
fail() { say "sdk abi fix $GAMEVER: $*" >&2; exit 2; }
notify() { [ -x ./autopilot_notify.sh ] && ./autopilot_notify.sh "$1" "$GAMEVER" "$2" || true; }
reject() {
    say "sdk abi fix $GAMEVER: REJECTED - $*"
    notify "sdk-abi-fix-rejected" "$*
worktree: $WORKTREE (branch $BRANCH, not pushed)
logs: $LOG-*.log"
    exit 1
}

command -v "$AGENT" > /dev/null || fail "no $AGENT on PATH"
command -v gh > /dev/null || fail "no gh on PATH"
[ -d "$SDK_REPO/.git" ] || fail "no hl2sdk fork checkout at $SDK_REPO"
[ -d "$BINARIES/$GAMEVER" ] || fail "no binaries in $BINARIES/$GAMEVER"
mkdir -p "$STATE"

# One fix per gamever: an open pull request means a person has it now
existing=$(gh pr list --repo "$SDK_SLUG" --head "$BRANCH" --state open --json url --jq '.[0].url' 2> /dev/null)
if [ -n "$existing" ]; then
    say "sdk abi fix $GAMEVER: already open, $existing"
    exit 0
fi

git -C "$SDK_REPO" fetch -q origin "$SDK_BRANCH" || fail "could not fetch $SDK_SLUG $SDK_BRANCH"
BASE=$(git -C "$SDK_REPO" rev-parse --verify -q "${SDK_BASE:-origin/$SDK_BRANCH}^{commit}") \
    || fail "no commit ${SDK_BASE:-origin/$SDK_BRANCH} in $SDK_REPO"

# The submodule is what sdk_abi_check.sh compiles; it is moved to the commit under test
# and put back where it was on the way out
SUBMODULE_WAS=$(git -C hl2sdk_cs2 rev-parse HEAD) || fail "no hl2sdk_cs2 submodule"
restore_submodule() { git -C hl2sdk_cs2 checkout -q "$SUBMODULE_WAS" 2> /dev/null || true; }
trap restore_submodule EXIT

abi_check() {  # abi_check <commit> <output file>; the commit is fetched from the fork checkout
    git -C hl2sdk_cs2 fetch -q "$SDK_REPO" "$1" || return 2
    SDK_REF="$1" ./sdk_abi_check.sh "$GAMEVER" > "$2" 2>&1
}
section() {  # section <file> new|gone - the mismatch lines under that heading
    awk -v want="$2" '
        /^no longer mismatching/ { cur = "gone"; next }
        /^NEW mismatches/ { cur = "new"; next }
        cur == want && /^  / { sub(/^  /, ""); print }' "$1"
}
# A mismatch that only moved: the same line once every number in it is ignored
shape() { sed -E 's/0x[0-9a-fA-F]+|[0-9]+/N/g' | sort; }

say "sdk abi fix $GAMEVER: checking hl2sdk $(git -C "$SDK_REPO" log -1 --format='%h %s' "$BASE")"
abi_check "$BASE" "$LOG-before.log"
case $? in
    0) say "sdk abi fix $GAMEVER: nothing to fix, $(head -1 "$LOG-before.log")"; exit 0 ;;
    1) ;;
    *) fail "sdk_abi_check.sh could not run: $(head -1 "$LOG-before.log")" ;;
esac
section "$LOG-before.log" new > "$LOG-mismatches.txt"
# Accepted mismatches that moved index are not a header bug: nothing for an agent to do
if [ -z "$(comm -23 <(shape < "$LOG-mismatches.txt") <(section "$LOG-before.log" gone | shape))" ]; then
    say "sdk abi fix $GAMEVER: only accepted mismatches moved index; run ./sdk_abi_check.sh $GAMEVER --accept"
    exit 0
fi
CLASSES=$(sed -E 's/_(Linux|MSVC) \|.*//' "$LOG-mismatches.txt" | sort -u | paste -sd' ')

# A fresh worktree of the fork at the base commit
git -C "$SDK_REPO" worktree remove --force "$WORKTREE" 2> /dev/null
rm -rf "$WORKTREE"
git -C "$SDK_REPO" worktree prune
git -C "$SDK_REPO" worktree add -q -B "$BRANCH" "$WORKTREE" "$BASE" || fail "could not create the worktree $WORKTREE"

PROMPT="CS2 build $GAMEVER changed the game's ABI and the headers in this repository no longer match it.
This directory is a git worktree of the hl2sdk fork ($SDK_SLUG) on the new branch $BRANCH. Fix the
headers here so they match the game, following AGENTS.md (read it first; its Verifying and Naming
sections are binding).

The ABI check (clang's vtable and record layouts of these headers against the binaries) reports
these NEW mismatches, as '<test> | <difference>'. 'YAML expects' is the name our analysis gave the
function at that slot in the binary; 'compiler reports' is what the header puts there:

$(cat "$LOG-mismatches.txt")

Evidence, all read-only:
- binaries of this build and the previous ones: $BINARIES/<gamever>/<module>/ (.so and .dll;
  compare $GAMEVER with the build before it to see what was inserted, removed or reordered)
- per-function and per-vtable facts our analysis recorded: $REPO/bin_artifacts/<gamever>/<module>/*.yaml
  (<Class>_vtable.<platform>.yaml lists every slot's address)
- open pull requests on alliedmodders/s2sdk may already fix this: read them with
  'gh pr list --repo alliedmodders/s2sdk --state open' and 'gh pr diff <n> --repo alliedmodders/s2sdk'.
  If one fixes these mismatches and you have confirmed every slot it changes in the binaries,
  cherry-pick its commit (git fetch https://github.com/alliedmodders/s2sdk pull/<n>/head) rather
  than writing your own. Never comment on, review or open anything there.

What to do:
1. For every class above, find what changed in the Linux AND the Windows binary by disassembling
   (llvm-objdump -d -M intel --start-address/--stop-address) the slots around the first mismatch.
   Find things through strings, RTTI and the recorded artifacts, and match slots by body.
2. Edit the headers: declare what the game has. A virtual whose purpose is not certain is an
   unknown named by AGENTS.md's unkXYZ rule, with the unknowns after it renumbered.
3. Commit on this branch, one commit per header or interface, subject as AGENTS.md says. Do not
   push, do not open a pull request, do not touch any other repository or directory, and do not
   change lib/, protobufs, scripts or CI files.
4. Finish with a short report: per class, what the game changed, the evidence on each platform
   (function addresses and what their bodies do) and anything you could not confirm.

If you cannot confirm a change in the binaries, do not guess: commit nothing for that class and
say so in the report."

say "sdk abi fix $GAMEVER: $AGENT is fixing $CLASSES in $WORKTREE (up to $((TIMEOUT / 60)) min)"
AGENT_ARGS=(-p "$PROMPT" --permission-mode "${SDK_FIX_PERMISSION_MODE:-auto}" --add-dir "$BINARIES" --add-dir "$REPO/bin_artifacts")
[ -n "${SDK_FIX_MODEL:-}" ] && AGENT_ARGS+=(--model "$SDK_FIX_MODEL")
(cd "$WORKTREE" && timeout "$TIMEOUT" "$AGENT" "${AGENT_ARGS[@]}") > "$LOG-agent.log" 2>&1 < /dev/null
AGENT_RC=$?
[ "$AGENT_RC" = 0 ] || say "sdk abi fix $GAMEVER: $AGENT exited $AGENT_RC, checking what it left"

# ---- the checks: nothing below trusts the agent's report
HEAD_FIX=$(git -C "$WORKTREE" rev-parse HEAD)
[ "$HEAD_FIX" != "$BASE" ] || reject "the agent committed nothing ($AGENT exit $AGENT_RC)
$(tail -12 "$LOG-agent.log" | cut -c1-300)"
[ -z "$(git -C "$WORKTREE" status --porcelain)" ] || reject "the agent left uncommitted changes:
$(git -C "$WORKTREE" status --porcelain | head -10)"
outside=$(git -C "$WORKTREE" diff --name-only "$BASE" HEAD | grep -vE '^(public|game)/.+\.(h|cpp)$')
[ -z "$outside" ] || reject "the fix touches files that are not SDK headers or sources:
$outside"

abi_check "$HEAD_FIX" "$LOG-after.log"
ABI_RC=$?
section "$LOG-after.log" new > "$LOG-new.txt"
section "$LOG-after.log" gone > "$LOG-gone.txt"
MOVED=0
case $ABI_RC in
    0) ;;
    1) left=$(comm -23 <(shape < "$LOG-new.txt") <(shape < "$LOG-gone.txt"))
       [ -z "$left" ] || reject "the fixed headers still mismatch the binaries:
$(head -12 "$LOG-new.txt")"
       MOVED=$(wc -l < "$LOG-new.txt") ;;
    *) reject "the fixed headers do not compile in the ABI tests:
$(head -12 "$LOG-after.log")" ;;
esac
say "sdk abi fix $GAMEVER: abi ok ($(head -1 "$LOG-after.log"))"

for platform in linux windows; do
    (cd "$WORKTREE" && ./local-ci.sh "$platform") > "$LOG-ci-$platform.log" 2>&1 \
        || reject "./local-ci.sh $platform fails on the fix, see $LOG-ci-$platform.log
$(grep -E 'error' "$LOG-ci-$platform.log" | head -8 | cut -c1-240)"
    say "sdk abi fix $GAMEVER: local-ci $platform ok"
done

COMMITS=$(git -C "$WORKTREE" log --format='- %h %s' "$BASE..HEAD")
REPORT=$(awk 'NF' "$LOG-agent.log" | tail -60)
BODY="CS2 build $GAMEVER moved the ABI of: $CLASSES. Fixed by \`sdk_abi_fix.sh\` ($AGENT), not reviewed by a person yet.

Checked by the script on this branch:
- \`sdk_abi_check.sh $GAMEVER\`: no new mismatch$([ "$MOVED" -gt 0 ] && echo " ($MOVED accepted mismatch line(s) only moved index: run it with \`--accept\` after merging)")
- \`./local-ci.sh linux\` and \`./local-ci.sh windows\` build
- only files under \`public/\` and \`game/\` changed

Commits:
$COMMITS

<details><summary>Mismatches before the fix</summary>

\`\`\`
$(cat "$LOG-mismatches.txt")
\`\`\`
</details>

<details><summary>The agent's report (verify the evidence before merging)</summary>

$REPORT
</details>"

if [ "$DRY_RUN" = 1 ]; then
    say "sdk abi fix $GAMEVER: dry run - not pushed. Branch $BRANCH in $WORKTREE:"
    say "$COMMITS"
    exit 0
fi

git -C "$WORKTREE" push -q --force-with-lease origin "$BRANCH" || reject "could not push $BRANCH to $SDK_SLUG"
URL=$(gh pr create --repo "$SDK_SLUG" --base "$SDK_BRANCH" --head "$BRANCH" \
    --title "cs2: Fix $CLASSES for $GAMEVER" --body "$BODY") \
    || reject "pushed $BRANCH but could not open the pull request on $SDK_SLUG"
git -C "$SDK_REPO" worktree remove --force "$WORKTREE" 2> /dev/null
say "sdk abi fix $GAMEVER: $URL"
notify "sdk-abi-fix" "pull request for $CLASSES: $URL
$COMMITS
after merging: ./update_hl2sdk_submodules.sh && ./sdk_abi_check.sh $GAMEVER"
