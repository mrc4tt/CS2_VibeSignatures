#!/usr/bin/env bash
#
# autopilot_notify.sh - one outgoing message per autopilot outcome.
#
# Outgoing only: no port is opened and nothing waits for a reply, which is why
# this works from a machine behind a home router. Set AUTOPILOT_NOTIFY_URL to an
# ntfy topic (https://ntfy.sh/<topic>) or a Discord webhook; the payload shape is
# picked from the URL. With nothing set it prints and exits 0, so the chain never
# fails because a notification could not be delivered.
#
# Usage: ./autopilot_notify.sh <outcome> <gamever> <detail>
set -uo pipefail

OUTCOME="${1:-unknown}"
GAMEVER="${2:-unknown}"
DETAIL="${3:-}"
URL="${AUTOPILOT_NOTIFY_URL:-}"

case "$OUTCOME" in
    deployed) TITLE="CS2 $GAMEVER analysed and deployed" ;;
    held)     TITLE="CS2 $GAMEVER analysed, deploy held for review" ;;
    analysed) TITLE="CS2 $GAMEVER analysed" ;;
    failed)   TITLE="CS2 $GAMEVER failed" ;;
    *)        TITLE="CS2 $GAMEVER: $OUTCOME" ;;
esac

BODY="$TITLE"$'\n\n'"$DETAIL"
printf '%s\n' "$BODY"
[ -n "$URL" ] || exit 0

if [[ "$URL" == *"discord.com/api/webhooks"* ]]; then
    python3 - "$URL" "$BODY" <<'PY'
import json, sys, urllib.request
url, body = sys.argv[1], sys.argv[2][:1900]
request = urllib.request.Request(
    url,
    data=json.dumps({"content": f"```\n{body}\n```"}).encode(),
    headers={"Content-Type": "application/json"},
)
try:
    urllib.request.urlopen(request, timeout=15).read()
except Exception as error:                     # a dead webhook must not fail a green run
    print(f"notification not delivered: {error}", file=sys.stderr)
PY
else
    curl -fsS --max-time 15 -H "Title: $TITLE" -d "$DETAIL" "$URL" >/dev/null \
        || echo "notification not delivered" >&2
fi
exit 0
