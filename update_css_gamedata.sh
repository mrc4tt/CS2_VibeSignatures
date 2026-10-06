#!/bin/bash
# update_css_gamedata.sh
# ---------------------------------------------------------------------------
# One-shot orchestrator: regenerate CounterStrikeSharp gamedata.json
# (signatures + vtable offsets) from CS2 server binaries and deploy it into a
# live CounterStrikeSharp install.
#
# Engine:  headless idalib  (ida_analyze_bin.py spawns its own idalib-mcp;
#          no IDA GUI / lin.sh / win.sh required).
# Scope:   only the symbols present in the CSS install gamedata.json are
#          deployed (update_gamedata.py's CSS module only writes those).
#          Analysis runs the whole `server` module, but -oldgamever reuse
#          makes unchanged symbols ~free (direct MCP match, no agent/LLM).
# Deploy:  MERGE into the install file (regenerated values win per key,
#          install-only symbols are preserved). No backup file is written: the
#          install gamedata is tracked in git, so `git show HEAD:<path>` is the backup.
#
# Usage:
#   ./update_css_gamedata.sh [GAMEVER] [OLDGAMEVER]
#
#   GAMEVER      build under bin/ to analyze        (default: newest numeric)
#   OLDGAMEVER   prior build for sig reuse          (default: ida_analyze_bin
#                                                     auto = GAMEVER-1; "none"
#                                                     to disable)
#
# Env knobs (optional, passed through to ida_analyze_bin.py):
#   CSS_INSTALL   path to CSS install root
#                 (default: $HOME/CounterStrikeSharp)
#   AGENT         -agent value      (e.g. claude / codex)
#   LLM_APIKEY    -llm_apikey value
#   LLM_BASEURL   -llm_baseurl value
#   LLM_MODEL     -llm_model value
#   SNAPSHOT      game-symbol snapshot fed to update_gamedata.py
#                 (default: gamesymbols/<GAMEVER>.yaml)
#   DRYRUN=1      do everything except writing the install file
# ---------------------------------------------------------------------------
set -euo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"
CSS_INSTALL="${CSS_INSTALL:-$HOME/CounterStrikeSharp}"
# update_gamedata.py writes per-version output under gamedata/<GAMEVER>/ (it used
# to write a single unversioned dist/ tree), so DIST_GD is resolved after GAMEVER.
DIST_SUBPATH="CounterStrikeSharp/config/addons/counterstrikesharp/gamedata/gamedata.json"
INSTALL_REL="configs/addons/counterstrikesharp/gamedata/gamedata.json"

INSTALL_GD="$CSS_INSTALL/$INSTALL_REL"
BIN_ROOT="$REPO/bin"

log() { echo "[update_css] $*"; }
die() { echo "[update_css][ERROR] $*" >&2; exit 1; }

# Clean up after an interrupted earlier run WITHOUT touching anything live.
# This used to `pkill -9` every idalib-mcp and delete every .id0/.id1/.id2/.nam/
# .til under bin/<VER>/ - before and after the run - which killed the editor's
# IDA session and deleted the working files of its open database. Now, as in
# run_linux.sh:
#   * the editor session unit is paused for the run and started on exit
#   * only ORPHANED supervisors/workers (parent is init) are killed, and never
#     the session port
#   * only aux files no live idalib process owns are removed (an unowned set is
#     the wreckage of an interrupted run; an owned set is a working database)
SESSION_UNIT=cs2vibe-ida-session.service
SESSION_PORT="${CS2VIBE_SESSION_MCP_PORT:-13337}"

reap_orphans() {
  local pid ppid
  for pid in $(pgrep -f 'idalib-mcp --unsafe' 2>/dev/null); do
    ppid=$(ps -o ppid= -p "$pid" 2>/dev/null | tr -d ' ')
    [ "$ppid" = "1" ] || continue
    tr '\0' ' ' < /proc/"$pid"/cmdline 2>/dev/null | grep -qE -- "--port ${SESSION_PORT}( |$)" && continue
    pkill -9 -P "$pid" 2>/dev/null || true
    kill -9 "$pid" 2>/dev/null || true
  done
  for pid in $(pgrep -f 'ida_pro_mcp\.idalib_server' 2>/dev/null); do
    ppid=$(ps -o ppid= -p "$pid" 2>/dev/null | tr -d ' ')
    [ "$ppid" = "1" ] && kill -9 "$pid" 2>/dev/null || true
  done
}

held_idb_bases() {
  local pid link base arg
  for pid in $(pgrep -f 'idalib-mcp --unsafe' 2>/dev/null) \
             $(pgrep -f 'ida_pro_mcp\.idalib_server' 2>/dev/null); do
    for link in /proc/"$pid"/fd/*; do
      base=$(readlink "$link" 2>/dev/null) || continue
      case "$base" in *.id0|*.id1|*.id2|*.nam|*.til|*.i64) printf '%s\n' "${base%.*}" ;; esac
    done
    arg=$(tr '\0' '\n' < /proc/"$pid"/cmdline 2>/dev/null | tail -1)
    case "$arg" in /*) printf '%s\n' "$arg" ;; bin/*) readlink -f "$REPO/$arg" ;; esac
  done | sort -u
}

clear_free_idb_aux() {
  local file held
  [ -n "${GAMEVER:-}" ] && [ -d "$BIN_ROOT/$GAMEVER" ] || return 0
  held="$(held_idb_bases)"
  find "$BIN_ROOT/$GAMEVER" \( -name '*.id0' -o -name '*.id1' -o -name '*.id2' -o -name '*.nam' -o -name '*.til' \) 2>/dev/null |
  while IFS= read -r file; do
    printf '%s\n' "$held" | grep -qxF "$(readlink -f "${file%.*}")" && continue
    rm -f -- "$file"
  done
}

reap_idalib() {
  reap_orphans
  clear_free_idb_aux
}

resume_session() {
  if command -v systemctl >/dev/null 2>&1 && systemctl is-enabled --quiet "$SESSION_UNIT" 2>/dev/null; then
    systemctl start --no-block "$SESSION_UNIT" 2>/dev/null || true
  fi
}

cd "$REPO"

# --- 1. resolve gamever ----------------------------------------------------
GAMEVER="${1:-}"
if [ -z "$GAMEVER" ]; then
  GAMEVER="$(ls -1 "$BIN_ROOT" | grep -E '^[0-9]+$' | sort -n | tail -1)"
  [ -n "$GAMEVER" ] || die "no numeric build under $BIN_ROOT"
fi
OLDGAMEVER="${2:-}"

DIST_GD="$REPO/gamedata/$GAMEVER/$DIST_SUBPATH"
# update_gamedata.py reads symbols from a game-symbol snapshot, not from bin/ YAML.
SNAPSHOT="${SNAPSHOT:-$REPO/gamesymbols/$GAMEVER.yaml}"

LIN="$BIN_ROOT/$GAMEVER/server/libserver.so"
WIN="$BIN_ROOT/$GAMEVER/server/server.dll"
[ -f "$LIN" ] || die "missing linux binary: $LIN"
[ -f "$WIN" ] || die "missing windows binary: $WIN"
[ -f "$INSTALL_GD" ] || die "CSS install gamedata not found: $INSTALL_GD"

log "build       : $GAMEVER"
log "linux bin   : $LIN"
log "windows bin : $WIN"
log "install gd  : $INSTALL_GD"

# --- 1b. preflight: clear stale idalib-mcp servers + IDB locks --------------
# Fixes "IDB lock file detected ... another IDA instance has this database open"
# left by an interrupted prior run. Also reap on exit/interrupt so THIS run
# never leaves a lock behind for the next one.
if command -v systemctl >/dev/null 2>&1 && systemctl is-active --quiet "$SESSION_UNIT" 2>/dev/null; then
  log "pausing the editor IDA session for this run ($SESSION_UNIT)"
  systemctl stop "$SESSION_UNIT" || true
fi
log "preflight: reaping orphaned idalib-mcp servers + unowned IDB aux files under bin/$GAMEVER"
reap_idalib
sleep 1
trap 'reap_idalib; resume_session' EXIT
trap 'exit 130' INT TERM

# --- 2. analyze both binaries (linux+windows) -> per-symbol YAML -----------
ANALYZE=(uv run ida_analyze_bin.py -gamever="$GAMEVER" -platform=linux,windows -modules=server)
[ -n "$OLDGAMEVER" ]        && ANALYZE+=(-oldgamever="$OLDGAMEVER")
[ -n "${AGENT:-}" ]         && ANALYZE+=(-agent="$AGENT")
[ -n "${LLM_APIKEY:-}" ]    && ANALYZE+=(-llm_apikey="$LLM_APIKEY")
[ -n "${LLM_BASEURL:-}" ]   && ANALYZE+=(-llm_baseurl="$LLM_BASEURL")
[ -n "${LLM_MODEL:-}" ]     && ANALYZE+=(-llm_model="$LLM_MODEL")

log "running: ${ANALYZE[*]}"
"${ANALYZE[@]}"

# --- 3. YAML -> dist gamedata.json -----------------------------------------
[ -f "$SNAPSHOT" ] || die "game-symbol snapshot not found: $SNAPSHOT (pack it first, or set SNAPSHOT=<path>)"

log "running: uv run update_gamedata.py -gamever=$GAMEVER -snapshot=$SNAPSHOT"
uv run update_gamedata.py -gamever="$GAMEVER" -snapshot="$SNAPSHOT" -outputdir="$REPO/gamedata/$GAMEVER"

[ -f "$DIST_GD" ] || die "dist gamedata not produced: $DIST_GD"

# --- 4. merge dist -> install (preserve install-only symbols) + diff -------
# Bring the install repo up to date first. The merge reads the install file, and
# the repo gets commits from elsewhere (15 behind on 14189): merging into a stale
# copy keeps install-only keys someone already changed upstream, and
# check_deploy_drift then compares against that stale copy too. Not fatal - the
# push in deploy_local_plugins.sh rebases anyway - but say so.
if [ "${DRYRUN:-0}" != "1" ] && git -C "$CSS_INSTALL" rev-parse --git-dir >/dev/null 2>&1; then
    if git -C "$CSS_INSTALL" pull -q --rebase --autostash 2>/dev/null; then
        log "pulled $CSS_INSTALL ($(git -C "$CSS_INSTALL" log -1 --format=%h))"
    else
        git -C "$CSS_INSTALL" rebase --abort 2>/dev/null || true
        log "WARNING: could not pull $CSS_INSTALL - merging into the local copy"
    fi
fi

# No .bak: $INSTALL_GD is tracked in the CounterStrikeSharp repo, so the pre-merge
# version is `git show HEAD:$INSTALL_REL`. Uncommitted edits are the exception, so
# say so before the merge rewrites them in place.
if git -C "$CSS_INSTALL" rev-parse --git-dir >/dev/null 2>&1 \
   && ! git -C "$CSS_INSTALL" diff --quiet -- "$INSTALL_REL" 2>/dev/null; then
    log "WARNING: $INSTALL_REL has uncommitted changes - the merge rewrites them in place"
fi

DRYRUN="${DRYRUN:-0}" python3 - "$DIST_GD" "$INSTALL_GD" <<'PY'
import json, os, sys
dist_p, inst_p = sys.argv[1], sys.argv[2]
dist = json.load(open(dist_p, encoding="utf-8"))
inst = json.load(open(inst_p, encoding="utf-8"))

changed, added, kept = [], [], []
merged = dict(inst)
for k, v in dist.items():
    if k not in inst:
        added.append(k)
    elif inst[k] != v:
        changed.append(k)
    merged[k] = v
inst_only = sorted(set(inst) - set(dist))

print("[update_css] regenerated symbols : %d (dist)" % len(dist))
print("[update_css] install symbols      : %d" % len(inst))
print("[update_css] changed              : %s" % (", ".join(sorted(changed)) or "(none)"))
print("[update_css] added                : %s" % (", ".join(sorted(added)) or "(none)"))
print("[update_css] preserved install-only: %s" % (", ".join(inst_only) or "(none)"))

if os.environ.get("DRYRUN") == "1":
    print("[update_css] DRYRUN=1 -> install file NOT written")
    sys.exit(0)
if not changed and not added:
    print("[update_css] no changes -> install file left as-is")
    sys.exit(0)
with open(inst_p, "w", encoding="utf-8") as f:
    json.dump(merged, f, indent=2)
    f.write("\n")
print("[update_css] wrote %s" % inst_p)
PY

log "done."
