#!/usr/bin/env python3
"""
Read the gamedata changes other people propose upstream, and test them against our build.

Upstream CounterStrikeSharp (roflmuffin) gets pull requests that change signatures in
its gamedata.json - usually right after a CS2 update, from people who scanned the new
binary by hand. Each is either a fix we already have, a mistake, or something we lack.
This fetches the file at the head of every open pull request that touches a watched
path (and at the default branch), takes the keys whose value differs from the base, and
scans each value in the newest analysed build:

  agrees     the value finds the function our record names (same bytes or not)
  WRONG      the value finds a function other than ours - with the name of our record
             at that address, if there is one. PR #1492's ClientPrint on 14197 landed on
             a constructor with one caller, where ours is the controller wrapper that
             calls UTIL_ClientPrintFilter
  broken     the value does not resolve uniquely in this build (status from
             verify_plugin_gamedata.check_signature)
  new        a key we have no record for; with an alias suggestion when the value lands
             on one of our functions, otherwise a candidate for a fork-owned symbol
  offset     an offset that differs from ours (ours is verified on generation)

Read only. It never comments, reviews or reacts on an upstream repository: findings go
to stdout and, from autopilot's idle tick, to the admin channel - only when a pull
request's findings changed since the last report (.autopilot/upstream-watch.json).

  uv run upstream_watch.py -gamever 14197            # report every watched source
  uv run upstream_watch.py -gamever 14197 -notify    # and notify what is new
  uv run upstream_watch.py -gamever 14197 -notify -every 1   # autopilot: at most hourly

Exit 0 nothing to report, 1 a finding (WRONG, broken or new), 2 a fetch failed.
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time

import validate_artifacts as V
import verify_plugin_gamedata as P

STATE = os.path.join(".autopilot", "upstream-watch.json")

# (upstream repo, path in it, our generator, the generator's output relative to gamedata/<VER>/<plugin>/)
WATCHES = [
    ("roflmuffin/CounterStrikeSharp", "configs/addons/counterstrikesharp/gamedata/gamedata.json",
     "CounterStrikeSharp", "config/addons/counterstrikesharp/gamedata/gamedata.json"),
]


def gh_json(endpoint):
    done = subprocess.run(["gh", "api", "--paginate", endpoint], capture_output=True, text=True, timeout=120)
    if done.returncode != 0:
        raise RuntimeError(done.stderr.strip().splitlines()[-1] if done.stderr.strip() else f"gh api {endpoint} failed")
    # --paginate concatenates JSON arrays as "][": merge them
    text = done.stdout.strip()
    return json.loads("[" + text[1:-1].replace("]\n[", ",").replace("][", ",") + "]") if text.startswith("[") \
        else json.loads(text)


def gh_raw(repo, path, ref):
    done = subprocess.run(["gh", "api", f"repos/{repo}/contents/{path}?ref={ref}",
                           "-H", "Accept: application/vnd.github.raw"], capture_output=True, text=True, timeout=120)
    if done.returncode != 0:
        raise RuntimeError(f"cannot fetch {repo}:{path}@{ref}")
    return json.loads(P._strip_jsonc(done.stdout))


def sources(repo, path, days):
    """[(id, label, ref, base ref)] - the default branch, then each open PR touching path
    and updated in the last `days` days (an abandoned PR against an old build only adds noise)."""
    info = gh_json(f"repos/{repo}")
    branch = info["default_branch"]
    out = [(f"{repo}@{branch}", f"{repo} {branch}", branch, None)]
    cutoff = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - days * 86400))
    for pr in gh_json(f"repos/{repo}/pulls?state=open&per_page=100"):
        if pr.get("updated_at", "") < cutoff:
            continue
        files = gh_json(f"repos/{repo}/pulls/{pr['number']}/files?per_page=100")
        if any(f.get("filename") == path for f in files):
            out.append((f"{repo}#{pr['number']}@{pr['head']['sha'][:12]}",
                        f"{repo}#{pr['number']} \"{pr['title']}\" ({pr['user']['login']}) "
                        f"https://github.com/{repo}/pull/{pr['number']}",
                        f"refs/pull/{pr['number']}/head", pr["base"]["sha"]))
    return out


def _values(entry):
    for kind in ("signatures", "offsets"):
        if isinstance(entry, dict) and isinstance(entry.get(kind), dict):
            return kind, {p: entry[kind].get(p) for p in ("linux", "windows")}, entry[kind].get("library")
    return None, {}, None


def changed_keys(theirs, base):
    """{key: [platform]} whose value in theirs differs from base (every key when base is None)."""
    out = {}
    for key, entry in theirs.items():
        kind, values, _lib = _values(entry)
        if kind is None:
            continue
        _k, before, _l = _values((base or {}).get(key))
        platforms = [p for p in ("linux", "windows") if values.get(p) not in (None, "")
                     and (base is None or values.get(p) != before.get(p))]
        if platforms:
            out[key] = platforms
    return out


def symbol_at(index, platform, va):
    for name, per_platform in index.items():
        record = per_platform.get(platform) or {}
        if record.get("func_va") and V._hexint(record["func_va"]) == va:
            return record.get("func_name") or name
    return None


def judge(index, binaries, aliases, key, platform, entry, ours_entry):
    """(verdict, text) for one value."""
    kind, values, library = _values(entry)
    value = values[platform]
    _k, mine, _l = _values(ours_entry)
    record = P.resolve_record(index, key, platform, aliases)
    module = P.LIBRARY_TO_MODULE.get(str(library or "server"), "server")
    if kind == "offsets":
        if mine.get(platform) is None:
            return "new", f"offset {value}, no record here"
        if str(value) == str(mine.get(platform)):
            return "agrees", f"offset {value}"
        return "offset", f"offset {value}, ours {mine.get(platform)} (verified)"
    info = P.check_signature(binaries, module, platform, value)
    status = info.get("status")
    if status not in ("ok", "ok-midfunction", "ok-globalref"):
        return "broken", f"{status} in this build" + (f" ({info.get('detail')})" if info.get("detail") else "")
    at = V._hexint(info["at"])
    if record is None:
        hit = symbol_at(index, platform, at)
        return "new", (f"lands on our {hit} - alias it" if hit else f"lands at {hex(at)}, no record here")
    ours_va = V._hexint(record["func_va"]) if record.get("func_va") else None
    if ours_va is None or at == ours_va:
        return "agrees", "same function as ours" + ("" if value != mine.get(platform) else ", same bytes")
    hit = symbol_at(index, platform, at)
    return "WRONG", (f"lands at {hex(at)}" + (f" ({hit})" if hit else " (no record there)")
                     + f", ours at {hex(ours_va)}: {mine.get(platform)!r}")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("-gamever", required=True)
    parser.add_argument("-notify", action="store_true", help="send what changed since the last report")
    parser.add_argument("-days", type=int, default=45, help="skip pull requests not updated for this long")
    parser.add_argument("-every", type=float, default=0,
                        help="hours: do nothing when the last -notify run is more recent (autopilot's idle tick)")
    args = parser.parse_args()

    index = P.load_snapshot_index(os.path.join("gamesymbols", f"{args.gamever}.yaml"))
    P._SNAPSHOT_INDEX.update(index)
    config = os.path.join("configs", f"{args.gamever}.yaml")
    aliases = P.load_alias_map(config) if os.path.isfile(config) else {}
    if os.path.isfile(config):
        P.GENERATOR_ALIASES.update(P.load_generator_aliases(config))
    binaries = P.Binaries("bin", args.gamever)

    try:
        state = json.load(open(STATE, encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    if args.every and time.time() - state.get("_last_run", 0) < args.every * 3600:
        return 0
    report, findings, failed, seen = [], 0, 0, {}
    for repo, path, plugin, relative in WATCHES:
        generated_path = os.path.join("gamedata", args.gamever, plugin, relative)
        generated = json.load(open(generated_path, encoding="utf-8")) if os.path.isfile(generated_path) else {}
        P.GENERATOR_ALIASES.update(P.generator_key_overrides(plugin, output=relative))
        try:
            watched = sources(repo, path, args.days)
        except Exception as error:  # noqa: BLE001 - an API outage must not stop autopilot
            print(f"[{repo}] {error}")
            failed += 1
            continue
        for source_id, label, ref, base_ref in watched:
            try:
                theirs = gh_raw(repo, path, ref)
                base = gh_raw(repo, path, base_ref) if base_ref else None
            except Exception as error:  # noqa: BLE001
                print(f"[{label}] {error}")
                failed += 1
                continue
            lines = []
            # The default branch is compared with our file, a pull request with its base.
            compare = generated if base is None else base
            for key, platforms in sorted(changed_keys(theirs, compare).items()):
                for platform in platforms:
                    verdict, text = judge(index, binaries, aliases, key, platform, theirs[key], generated.get(key))
                    if verdict == "agrees" and base is None:
                        continue  # the default branch differs from ours in bytes only
                    lines.append(f"  {verdict:7} {key}.{platform}: {text}")
            if not lines:
                continue
            bad = [l for l in lines if l.split()[0] in ("WRONG", "broken", "new")]
            findings += bool(bad)
            block = [f"[{label}]"] + lines
            print("\n".join(block))
            digest = hashlib.sha256("\n".join(lines).encode()).hexdigest()[:16]
            seen[source_id] = digest
            if bad and state.get(source_id) != digest:
                report.append("\n".join(block))
    summary = f"upstream_watch {args.gamever}: {findings} source(s) with findings" \
        + (f", {failed} could not be fetched" if failed else "")
    print(summary)

    if args.notify and report and os.access("./autopilot_notify.sh", os.X_OK):
        subprocess.run(["./autopilot_notify.sh", "upstream-gamedata", args.gamever,
                        "\n\n".join(report)[:1700] + "\n\nread only - nothing was posted upstream"])
    if args.notify:
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        seen["_last_run"] = int(time.time())
        with open(STATE, "w", encoding="utf-8") as handle:
            json.dump(seen, handle, indent=1, sort_keys=True)
    return 2 if failed else (1 if findings else 0)


if __name__ == "__main__":
    sys.exit(main())
