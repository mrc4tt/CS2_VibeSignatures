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
    started)  TITLE="CS2 $GAMEVER detected, analysis starting" ;;
    deployed) TITLE="CS2 $GAMEVER analysed and deployed" ;;
    held)     TITLE="CS2 $GAMEVER analysed, deploy held for review" ;;
    analysed) TITLE="CS2 $GAMEVER analysed" ;;
    failed)   TITLE="CS2 $GAMEVER failed" ;;
    linux-deployed) TITLE="CS2 $GAMEVER linux analysed and deployed, windows next" ;;
    linux-held)     TITLE="CS2 $GAMEVER linux analysed, deploy held for review, windows next" ;;
    linux-analysed) TITLE="CS2 $GAMEVER linux analysed, windows next" ;;
    linux-failed)   TITLE="CS2 $GAMEVER linux early release stopped, windows goes ahead" ;;
    *)        TITLE="CS2 $GAMEVER: $OUTCOME" ;;
esac

# Which machine sent it: a notice with no trace in this server's journal cost a
# session hunting for its run (14194's "failed / push"), since every clone with
# the same webhook sends the same text.
TITLE="$TITLE [$(hostname -s 2>/dev/null || echo unknown-host)]"
BODY="$TITLE"$'\n\n'"$DETAIL"
printf '%s\n' "$BODY"

# The Discord bot (bot/) on this machine: it keeps one message per build in the
# updates channel and edits it as each outcome arrives. Independent of URL, so
# the plain webhook/ntfy message can stay on as a fallback.
if [ -n "${AUTOPILOT_BOT_URL:-}" ]; then
    python3 - "$AUTOPILOT_BOT_URL" "${AUTOPILOT_BOT_SECRET:-}" "$OUTCOME" "$GAMEVER" "$DETAIL" <<'PY'
import json, sys, urllib.request
url, secret, outcome, gamever, detail = sys.argv[1:6]
request = urllib.request.Request(
    url,
    data=json.dumps({"outcome": outcome, "gamever": gamever, "detail": detail}).encode(),
    headers={"Content-Type": "application/json", "Authorization": f"Bearer {secret}"},
)
try:
    urllib.request.urlopen(request, timeout=10).read()
except Exception as error:                     # a stopped bot must not fail a green run
    print(f"bot notification not delivered: {error}", file=sys.stderr)
PY
fi
[ -n "$URL" ] || exit 0

if [[ "$URL" == *"discord.com/api/webhooks"* ]]; then
    python3 - "$URL" "$BODY" <<'PY'
import json, sys, urllib.request
url, body = sys.argv[1], sys.argv[2][:1900]
# Discord refuses urllib's default User-Agent with 403 - measured: the same
# payload through curl returns 204, through urllib without this header it does
# not arrive at all. A notification that fails silently is worse than none.
request = urllib.request.Request(
    url,
    data=json.dumps({"content": f"```\n{body}\n```"}).encode(),
    headers={
        "Content-Type": "application/json",
        "User-Agent": "cs2vibe-autopilot (+https://sig.miksen.me)",
    },
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
