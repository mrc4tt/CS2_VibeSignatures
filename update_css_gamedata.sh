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

REPO="$HOME/CS2_VibeSignatures"
CSS_INSTALL="${CSS_INSTALL:-$HOME/CounterStrikeSharp}"
# update_gamedata.py writes per-version output under gamedata/<GAMEVER>/ (it used
# to write a single unversioned dist/ tree), so DIST_GD is resolved after GAMEVER.
DIST_SUBPATH="CounterStrikeSharp/config/addons/counterstrikesharp/gamedata/gamedata.json"
INSTALL_REL="configs/addons/counterstrikesharp/gamedata/gamedata.json"

INSTALL_GD="$CSS_INSTALL/$INSTALL_REL"
BIN_ROOT="$REPO/bin"

log() { echo "[update_css] $*"; }
die() { echo "[update_css][ERROR] $*" >&2; exit 1; }

# Kill stale idalib-mcp supervisors/workers and purge orphaned IDA database
# locks. idalib-mcp 2.0.0 detaches its supervisor into its own session, so an
# interrupted/aborted prior run can leave it holding the port plus an
# uncompacted DB (.id0/.id1/.id2/.nam/.til) that trips "IDB lock file detected".
# Matching by cmdline avoids self-killing this script (it does not run idalib).
reap_idalib() {
  pkill -9 -f 'ida_pro_mcp\.idalib_server' 2>/dev/null || true
  pkill -9 -f 'idalib-mcp --unsafe'        2>/dev/null || true
  if [ -n "${GAMEVER:-}" ] && [ -d "$BIN_ROOT/$GAMEVER" ]; then
    find "$BIN_ROOT/$GAMEVER" \
      \( -name '*.id0' -o -name '*.id1' -o -name '*.id2' -o -name '*.nam' -o -name '*.til' \) \
      -delete 2>/dev/null || true
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
log "preflight: reaping stale idalib-mcp servers + IDB locks under bin/$GAMEVER"
reap_idalib
sleep 1
trap reap_idalib EXIT INT TERM

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
