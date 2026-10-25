#!/usr/bin/env python3
"""What the agents cost: opencode's own session ledger, summed over a time window.

opencode records tokens and cost per session in its SQLite database; this reads it
back per model and per skill, so a build's agent bill is known without opening the
provider's dashboard. Not counted: LLM_DECOMPILE (a direct API call, not opencode)
and the claude/codex agents, which keep no such ledger.

    uv run agent_cost.py -since "2026-10-25 12:00"
    uv run agent_cost.py -since 1761393600 -json > .autopilot/agent-cost-14193.json
"""

import argparse
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone

DEFAULT_DB = os.path.expanduser("~/.local/share/opencode/opencode.db")
SKILL_PROMPT = re.compile(r"Run SKILL: \.claude/skills/([^/\s]+)/SKILL\.md")
# USD per 1M tokens (input, cached input, output), z.ai's price list of 2026-10-25.
# opencode bills the coding plan at $0, so this is what the same hunt costs on the API.
LIST_PRICES = {
    "glm-5.3": (1.40, 0.26, 4.40),
    "glm-5.3-flash": (0.15, 0.03, 0.50),
    "glm-5.3-flashx": (0.37, 0.075, 1.25),
}


def parse_time(value):
    """Epoch seconds, or an ISO-ish local time such as '2026-10-25 12:00'."""
    if value is None:
        return None
    if re.fullmatch(r"\d+(\.\d+)?", value):
        return float(value)
    return datetime.fromisoformat(value).timestamp()


def collect(db_path, since=None, until=None):
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    query = "select id from session where parent_id is null"
    params = []
    if since is not None:
        query += " and time_created >= ?"
        params.append(int(since * 1000))
    if until is not None:
        query += " and time_created < ?"
        params.append(int(until * 1000))
    sessions = connection.execute(query, params).fetchall()

    total = {"hunts": 0, "cost": 0.0, "list_cost": 0.0, "input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
    by_model, by_skill = {}, {}
    for (sid,) in sessions:
        prompt = connection.execute(
            "select json_extract(data,'$.text') from part where session_id=? "
            "and json_extract(data,'$.type')='text' order by time_created limit 1",
            (sid,),
        ).fetchone()
        match = SKILL_PROMPT.search((prompt or [""])[0] or "")
        if not match:
            continue  # an interactive session, not a hunt
        # the session row's own totals stay 0 on this opencode; the messages carry them
        provider, model_id, cost, t_in, t_out, t_reason, t_cread, t_cwrite = connection.execute(
            "select max(json_extract(data,'$.providerID')), max(json_extract(data,'$.modelID')), "
            "total(json_extract(data,'$.cost')), total(json_extract(data,'$.tokens.input')), "
            "total(json_extract(data,'$.tokens.output')), total(json_extract(data,'$.tokens.reasoning')), "
            "total(json_extract(data,'$.tokens.cache.read')), total(json_extract(data,'$.tokens.cache.write')) "
            "from message where session_id=? and json_extract(data,'$.role')='assistant'",
            (sid,),
        ).fetchone()
        model = f"{provider or '?'}/{model_id or '?'}"
        price_in, price_cached, price_out = LIST_PRICES.get(model_id, (0.0, 0.0, 0.0))
        row = {
            "hunts": 1,
            "cost": cost,
            "list_cost": ((t_in + t_cwrite) * price_in + t_cread * price_cached + (t_out + t_reason) * price_out) / 1e6,
            "input": int(t_in),
            "output": int(t_out + t_reason),
            "cache_read": int(t_cread),
            "cache_write": int(t_cwrite),
        }
        for bucket in (total, by_model.setdefault(model, dict.fromkeys(total, 0)),
                       by_skill.setdefault(match.group(1), dict.fromkeys(total, 0))):
            for key, value in row.items():
                bucket[key] += value
    connection.close()
    return {
        "since": datetime.fromtimestamp(since, timezone.utc).isoformat() if since else None,
        "until": datetime.fromtimestamp(until, timezone.utc).isoformat() if until else None,
        "total": total,
        "by_model": by_model,
        "by_skill": dict(sorted(by_skill.items(), key=lambda item: -item[1]["list_cost"])),
    }


def render(report, top):
    total = report["total"]
    lines = [
        f"agents: {total['hunts']} hunts, billed ${total['cost']:.2f}, at API list price ${total['list_cost']:.2f} "
        f"(input {total['input'] / 1e6:.1f}M, cache-read {total['cache_read'] / 1e6:.1f}M, "
        f"output {total['output'] / 1e6:.2f}M)"
    ]
    for model, row in sorted(report["by_model"].items(), key=lambda item: -item[1]["list_cost"]):
        lines.append(f"  {model}: {row['hunts']} hunts, billed ${row['cost']:.2f}, list ${row['list_cost']:.2f}")
    if report["by_skill"]:
        lines.append("  most expensive skills (list price):")
        for skill, row in list(report["by_skill"].items())[:top]:
            lines.append(f"    ${row['list_cost']:.2f}  {row['hunts']}x  {skill}")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("-since", help="epoch seconds or ISO time (default: all)")
    parser.add_argument("-until", help="epoch seconds or ISO time (default: now)")
    parser.add_argument("-db", default=os.environ.get("CS2VIBE_OPENCODE_DB", DEFAULT_DB))
    parser.add_argument("-top", type=int, default=10, help="skills listed in the text report")
    parser.add_argument("-json", action="store_true", help="print the full report as JSON")
    args = parser.parse_args(argv)
    if not os.path.isfile(args.db):
        print(f"no opencode database at {args.db}", file=sys.stderr)
        return 0  # no ledger is not a failure: the agents may simply not be opencode
    report = collect(args.db, parse_time(args.since), parse_time(args.until))
    print(json.dumps(report, indent=2) if args.json else render(report, args.top))
    return 0


if __name__ == "__main__":
    sys.exit(main())
