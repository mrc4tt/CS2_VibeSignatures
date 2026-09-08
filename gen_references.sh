#!/usr/bin/env bash
#
# gen_references.sh — generér manglende LLM_DECOMPILE-referencer med fuld log.
#
# Finder selv de manglende (placeholder-bevidst: {platform} udfoldes til linux+windows),
# springer eksisterende over (resume-sikkert), og skriver:
#   - konsol: statuslinjer pr. funktion (START/OK/FAIL/SKIP + tidspunkt)
#   - refs_gen_<tidsstempel>.log: ALLE output inkl. fejlmeddelelser
#
# Usage: ./gen_references.sh [GAMEVER]     (default: 14178b)

set -uo pipefail
cd "$(dirname "$0")"
GAMEVER="${1:-14178b}"
LOG="refs_gen_$(date +%Y%m%d_%H%M%S).log"

# byg mangler-listen (samme tjek som missing-check kommandoen)
MISSING=$(grep -h "references/" ida_preprocessor_scripts/find-*-decompiles.py | \
  grep -oP 'references/\S+?\.yaml' | sort -u | while read -r; do :; done
  grep -h "references/" ida_preprocessor_scripts/find-*-decompiles.py | \
  grep -oP 'references/\S+?\.yaml' | sort -u | while read r; do
    for p in linux windows; do
      f="ida_preprocessor_scripts/${r/\{platform\}/$p}"
      [ -f "$f" ] || echo "${r/\{platform\}/$p}"
    done
  done)

TOTAL=$(printf '%s\n' "$MISSING" | grep -c .)
echo "[$(date +%H:%M:%S)] Manglende referencer: $TOTAL — log: $LOG" | tee -a "$LOG"

ok=0; fail=0; skip=0
while read -r r; do
  [ -z "$r" ] && continue
  rel="${r#references/}"
  mod="${rel%%/*}"
  name="$(basename "$r" | sed 's/\.\(linux\|windows\)\.yaml//')"
  plat="$(basename "$r" | grep -oP 'linux|windows')"
  case "$mod" in
    engine)  bin="bin/$GAMEVER/engine/libengine2.so";;
    server)  bin="bin/$GAMEVER/server/libserver.so";;
    client)  bin="bin/$GAMEVER/client/libclient.so";;
    SDL3)         bin="bin/$GAMEVER/SDL3/libSDL3.so.0";;
    scenesystem)  bin="bin/$GAMEVER/scenesystem/libscenesystem.so";;
    networksystem) bin="bin/$GAMEVER/networksystem/libnetworksystem.so";;
    matchmaking)  bin="bin/$GAMEVER/matchmaking/libmatchmaking.so";;
    vphysics2)    bin="bin/$GAMEVER/vphysics2/libvphysics2.so";;
    *)       bin="";;
  esac
  if [ -z "$bin" ]; then
    echo "[$(date +%H:%M:%S)] SKIP (ukendt modul): $r" | tee -a "$LOG"; skip=$((skip+1)); continue
  fi
  echo "[$(date +%H:%M:%S)] START $r (bin: $bin)" | tee -a "$LOG"
  if uv run generate_reference_yaml.py -gamever "$GAMEVER" -module "$mod" -platform "$plat" \
       -func_name "$name" -auto_start_mcp -binary "$bin" >> "$LOG" 2>&1; then
    echo "[$(date +%H:%M:%S)] OK   $r" | tee -a "$LOG"; ok=$((ok+1))
  else
    echo "[$(date +%H:%M:%S)] FAIL $r  (detaljer i $LOG)" | tee -a "$LOG"; fail=$((fail+1))
  fi
done <<< "$MISSING"

echo "=== FÆRDIG $(date +%H:%M:%S): OK=$ok FAIL=$fail SKIP=$skip af $TOTAL — detaljer: $LOG" | tee -a "$LOG"
