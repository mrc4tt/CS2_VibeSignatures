#!/usr/bin/env bash
#
# add_gamever.sh — register a NEW gamever tag in download.yaml WITHOUT upstream.
#
# Valve ships new depots before any repo curates them. This tool resolves the
# current public manifest IDs for CS2's two server depots by probing
# DepotDownloader (which prints "manifest <id>" before transferring files, using
# a one-file filelist so the probe costs a few MB), then appends the tag entry.
# After this, run_linux.sh / run_windows.sh work for the tag as usual.
#
# Usage:
#   ./add_gamever.sh 14180            # eksplicit tag
#   ./add_gamever.sh                  # auto: Steam API's required_version
#
# Kræver: DepotDownloader i PATH + DEPOTDOWNLOADER_STEAM_USERNAME/PASSWORD (eller
# allerede cachet login-session).

set -euo pipefail
cd "$(dirname "$0")"

TAG="${1:-}"
if [ -z "$TAG" ]; then
    TAG=$(curl -sL --max-time 5 -A "Mozilla/5.0" \
        "https://api.steampowered.com/ISteamApps/UpToDateCheck/v1/?appid=730&version=0" | \
        python3 -c "import sys,json;print(json.load(sys.stdin)['response']['required_version'])" 2>/dev/null || true)
fi
[[ "$TAG" =~ ^[0-9]+[a-z]?$ ]] || { echo "❌ Ugyldigt/missing tag: '$TAG'"; exit 1; }

if grep -q "tag: \"$TAG\"" download.yaml; then
    echo "✔ $TAG er allerede registreret i download.yaml"
    exit 0
fi

USERNAME="${DEPOTDOWNLOADER_STEAM_USERNAME:-}"
PASSWORD="${DEPOTDOWNLOADER_STEAM_PASSWORD:-}"
AUTH=()
if [ -n "$USERNAME" ]; then
    AUTH+=(-username "$USERNAME" -password "$PASSWORD" -remember-password)
fi

probe_manifest() {  # $1=depot  $2=probe-filepath (findes i depotet)
    local depot="$1" probe="$2" tmp out
    tmp=$(mktemp)
    echo "$probe" > "$tmp"
    out=$(DepotDownloader -app 730 -depot "$depot" -dir "/tmp/depot_probe_${depot}" \
        "${AUTH[@]}" -filelist "$tmp" 2>&1) || true
    rm -f "$tmp"
    printf '%s' "$out" | grep -oP 'manifest \K[0-9]+' | head -1
}

echo "==> Resolver aktuelle manifest-ID'er (probe-download, faa MB)..."
WIN=$(probe_manifest 2347771 "game/bin/win64/SDL3.dll")
LIN=$(probe_manifest 2347773 "game/bin/linuxsteamrt64/libSDL3.so.0")

[ -n "$WIN" ] && [ -n "$LIN" ] || {
    echo "❌ Kunne ikke resolve manifest-ID'er (login? DepotDownloader-output ovenfor)."
    exit 1
}

# Sikkerheds-tjek: filen skal stadig slutte som en manifest-mapping (append-sikker)
tail -1 download.yaml | grep -qE '^\s+"2347773": "[0-9]+"$' || {
    echo "❌ download.yaml har uventet slut-format - append ikke sikker. Tjek filen manuelt."
    exit 1
}

cat >> download.yaml <<EOF
  - tag: "$TAG"
    name: $TAG
    manifests:
      "2347771": "$WIN"
      "2347773": "$LIN"
EOF

python3 -c "import yaml; yaml.safe_load(open('download.yaml')); print('yaml OK')" >/dev/null \
    || { echo "❌ append brød YAML'en - rul tilbage manuelt"; exit 1; }

echo "✔ $TAG registreret:  2347771=$WIN  2347773=$LIN"
echo "Næste skridt:"
echo "  git add download.yaml && git commit -m \"chore: pin gamever $TAG manifests\" && git push"
echo "  ./run_linux.sh $TAG && ./run_windows.sh $TAG"
