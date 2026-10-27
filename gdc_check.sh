#!/usr/bin/env bash
#
# gdc_check.sh - second opinion on the shipped gamedata's signatures.
#
# Runs gdc (tools/gdc, a .NET scanner that parses the ELF/PE files and never loads
# them) over every shipped plugin file of a gamever, then gdc_compare.py, which
# scans the same values with verify_plugin_gamedata's own scanner. A disagreement
# means one of the two scanners is wrong. Warn-only: autopilot reports it and
# carries on, because the verify gate before it is the gate.
#
# gdc is published to tools/gdc/out/gdc, rebuilt when a source file is newer:
# with a local dotnet 10 SDK when there is one, else in the dotnet/sdk:10.0 image.
#
# Usage:
#   ./gdc_check.sh                 newest gamedata/<gamever>
#   ./gdc_check.sh 14192
#
# Exit: 0 gdc finds no problem and agrees with the reference, 1 problems or
# disagreements, 2 no usable setup.

set -uo pipefail
cd "$(dirname "$0")"

GAMEVER="${1:-$(ls gamedata | grep -E '^[0-9]+$' | sort -n | tail -1)}"
case "$GAMEVER" in
    -h|--help) sed -n '3,20p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
esac
[ -d "gamedata/$GAMEVER" ] || { echo "gdc_check: no gamedata/$GAMEVER"; exit 2; }
[ -d "bin/$GAMEVER" ] || { echo "gdc_check: no bin/$GAMEVER"; exit 2; }

GDC=tools/gdc/out/gdc
if [ ! -x "$GDC" ] || [ -n "$(find tools/gdc -maxdepth 1 \( -name '*.cs' -o -name '*.csproj' \) -newer "$GDC")" ]; then
    publish="dotnet publish tools/gdc -c Release -r linux-x64 --self-contained -p:PublishSingleFile=true -o tools/gdc/out"
    if command -v dotnet >/dev/null && dotnet --list-sdks 2>/dev/null | grep -q '^10\.'; then
        $publish > /dev/null || { echo "gdc_check: gdc does not build"; exit 2; }
    elif command -v docker >/dev/null; then
        docker run --rm --network=host -u "$(id -u):$(id -g)" -e HOME=/tmp -e DOTNET_CLI_TELEMETRY_OPTOUT=1 \
            -v "$PWD/tools/gdc:/src/tools/gdc" -w /src mcr.microsoft.com/dotnet/sdk:10.0 \
            $publish > /dev/null || { echo "gdc_check: gdc does not build (docker)"; exit 2; }
    else
        echo "gdc_check: no dotnet 10 SDK and no docker to build gdc"
        exit 2
    fi
fi

DISABLED=$(uv run python -c "import publish_site_data as P; print(' '.join(sorted(P.disabled_plugins())))" 2>/dev/null || echo "")
FILES=()
while IFS= read -r plugin_file; do
    [ -n "$plugin_file" ] || continue
    plugin_dir=${plugin_file#gamedata/$GAMEVER/}
    case " $DISABLED " in *" ${plugin_dir%%/*} "*) continue ;; esac
    FILES+=("$plugin_file")
done <<LIST
$(find "gamedata/$GAMEVER" -type f \( -name '*.json' -o -name '*.jsonc' -o -name '*.txt' \) ! -name '*.metadata.json' | sort)
LIST
[ "${#FILES[@]}" -gt 0 ] || { echo "gdc_check: no shipped files in gamedata/$GAMEVER"; exit 2; }

STATE="${AUTOPILOT_STATE:-.autopilot}"
mkdir -p "$STATE"
REPORT="$STATE/gdc-$GAMEVER.json"
GDC_OUT=$("$GDC" --bin "bin/$GAMEVER" --json "$REPORT" "${FILES[@]}")
gdc_rc=$?
[ "$gdc_rc" -le 1 ] || { echo "gdc_check: gdc could not run: $GDC_OUT"; exit 2; }
CMP_OUT=$(uv run gdc_compare.py -gamever "$GAMEVER" -gdc "$REPORT")
cmp_rc=$?
[ "$cmp_rc" -le 1 ] || { echo "gdc_check: $CMP_OUT"; exit 2; }

echo "$(head -1 <<<"$GDC_OUT"); $(head -1 <<<"$CMP_OUT" | sed 's/^gdc_compare: //')"
tail -n +2 <<<"$GDC_OUT"
tail -n +2 <<<"$CMP_OUT"
[ "$gdc_rc" = 0 ] && [ "$cmp_rc" = 0 ]
