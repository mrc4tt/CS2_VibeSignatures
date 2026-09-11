#!/usr/bin/env python3
"""
autopilot_safe_gate.py - decide whether a freshly generated build may deploy
itself, or has to wait for a person.

The verification battery proves a pattern matches, matches once, lands on a
function head and that vtable slots agree with the class table read through
RTTI. It cannot prove the pattern names the function you think it does (see
CLAUDE.md rule 12: ParseNetadrList was a clean, unique, boundary-correct match
on the wrong function). So the gate does not try to judge correctness. It asks a
narrower question that IS answerable from the generated output:

    is this build nothing but a rebuild relocation?

A build where Valve moved code and every plugin key kept its shape is the boring
case, and by far the most common. A build where keys appeared or disappeared, an
offset or a vtable slot moved, coverage dropped, or a symbol lost a platform is a
build where something structural changed, and those are the ones worth a look
before they reach a live server.

Exit codes: 0 = safe to deploy, 10 = hold for review, 1 = could not decide.

    uv run autopilot_safe_gate.py -gamever 14181
    uv run autopilot_safe_gate.py -gamever 14181 -prev 14180 -json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

GAMEDATA_ROOT = "gamedata"
SNAPSHOT_ROOT = "gamesymbols"
KIND_WORDS = {
    "signatures", "signature", "offsets", "offset", "patches", "patch",
    "addresses", "address", "games", "csgo", "library", "keys",
}
PLATFORM_KEYS = ("linux", "windows", "linuxsteamrt64", "win64")


def game_version_sort_key(tag: str) -> tuple[int, str]:
    match = re.fullmatch(r"(\d+)([a-z]?)", tag)
    if not match:
        return (0, tag)
    return (int(match.group(1)), match.group(2))


def published_versions() -> list[str]:
    if not os.path.isdir(GAMEDATA_ROOT):
        return []
    tags = [t for t in os.listdir(GAMEDATA_ROOT) if re.fullmatch(r"\d+[a-z]?", t)]
    return sorted(tags, key=game_version_sort_key)


def strip_jsonc(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"(^|\s)//[^\n]*", "", text)
    return re.sub(r",(\s*[}\]])", r"\1", text)


def key_name(path: tuple[str, ...]) -> str:
    for segment in reversed(path):
        if segment.lower() not in KIND_WORDS:
            return segment
    return path[-1]


def read_keys(path: str) -> dict[str, dict[str, object]] | None:
    """key -> {linux, windows}. None when the file is absent or unreadable."""
    if not os.path.exists(path):
        return None
    raw = open(path, encoding="utf-8").read()
    out: dict[str, dict[str, object]] = {}
    if path.endswith(".txt"):
        for match in re.finditer(r'"([^"]+)"\s*\{(.*?)\n\t*\}', raw, re.S):
            body = match.group(2)
            linux = re.search(r'"(?:linux|linuxsteamrt64)"\s+"([^"]*)"', body)
            windows = re.search(r'"(?:windows|win64)"\s+"([^"]*)"', body)
            out[match.group(1)] = {
                "linux": linux.group(1) if linux else None,
                "windows": windows.group(1) if windows else None,
            }
        return out
    try:
        document = json.loads(strip_jsonc(raw) if path.endswith(".jsonc") else raw)
    except Exception:
        return None

    def walk(node: dict, prefix: tuple[str, ...] = ()) -> None:
        for key, value in node.items():
            if not isinstance(value, dict):
                continue
            if any(platform in value for platform in PLATFORM_KEYS):
                out[key_name(prefix + (key,))] = {
                    "linux": value.get("linux", value.get("linuxsteamrt64")),
                    "windows": value.get("windows", value.get("win64")),
                }
            else:
                walk(value, prefix + (key,))

    walk(document)
    return out


def generated_files(version: str) -> list[str]:
    """
    Every generated file, companion metadata or not. Older builds predate the
    metadata companions, and keying off them once made this gate compare an
    empty set and call the result safe.
    """
    root = os.path.join(GAMEDATA_ROOT, version)
    found = []
    for base, _dirs, names in os.walk(root):
        for name in names:
            if name.endswith(".metadata.json"):
                continue
            found.append(os.path.relpath(os.path.join(base, name), root))
    return sorted(found)


def coverage(version: str) -> tuple[int, int]:
    total = covered = 0
    root = os.path.join(GAMEDATA_ROOT, version)
    for base, _dirs, names in os.walk(root):
        for name in names:
            if not name.endswith(".metadata.json"):
                continue
            try:
                summary = json.load(open(os.path.join(base, name), encoding="utf-8")).get("summary", {})
            except Exception:
                continue
            total += int(summary.get("total", 0) or 0)
            covered += int(summary.get("covered", 0) or 0)
    return covered, total


def is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def snapshot_platforms(version: str) -> dict[str, set[str]]:
    """symbol -> the platforms it is published for, straight out of the snapshot."""
    path = os.path.join(SNAPSHOT_ROOT, f"{version}.yaml")
    if not os.path.exists(path):
        return {}
    platforms: dict[str, set[str]] = {}
    # The snapshot's `files:` keys are the only lines shaped like
    # "  <module>/<symbol>.<platform>.yaml:", so a scan beats parsing 2 MB of YAML.
    pattern = re.compile(r"^\s{2}([^/\s]+)/(.+)\.(linux|windows)\.yaml:\s*$")
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            match = pattern.match(line)
            if match:
                platforms.setdefault(f"{match.group(1)}/{match.group(2)}", set()).add(match.group(3))
    return platforms


def decide(version: str, previous: str) -> dict:
    holds: list[dict] = []
    notes: list[str] = []

    new_files = set(generated_files(version))
    old_files = set(generated_files(previous))
    for missing in sorted(old_files - new_files):
        holds.append({"reason": "file_missing", "file": missing})
    for added in sorted(new_files - old_files):
        holds.append({"reason": "file_new", "file": added})

    patterns_changed = 0
    for relative in sorted(new_files & old_files):
        new_keys = read_keys(os.path.join(GAMEDATA_ROOT, version, relative))
        old_keys = read_keys(os.path.join(GAMEDATA_ROOT, previous, relative))
        if new_keys is None or old_keys is None:
            holds.append({"reason": "unreadable", "file": relative})
            continue
        for lost in sorted(set(old_keys) - set(new_keys)):
            holds.append({"reason": "key_removed", "file": relative, "key": lost})
        for gained in sorted(set(new_keys) - set(old_keys)):
            holds.append({"reason": "key_added", "file": relative, "key": gained})
        for key in sorted(set(new_keys) & set(old_keys)):
            for platform in ("linux", "windows"):
                before, after = old_keys[key][platform], new_keys[key][platform]
                if before == after:
                    continue
                if is_number(before) or is_number(after):
                    holds.append({
                        "reason": "offset_or_slot_changed", "file": relative, "key": key,
                        "platform": platform, "before": before, "after": after,
                    })
                else:
                    patterns_changed += 1

    if not (new_files & old_files):
        holds.append({
            "reason": "nothing_to_compare",
            "detail": f"{len(new_files)} files in {version}, {len(old_files)} in {previous}",
        })

    new_covered, new_total = coverage(version)
    old_covered, old_total = coverage(previous)
    if new_total == 0 or old_total == 0:
        notes.append("one of the builds has no metadata companions; coverage check skipped")
    elif new_covered < old_covered:
        holds.append({
            "reason": "coverage_dropped",
            "before": f"{old_covered}/{old_total}", "after": f"{new_covered}/{new_total}",
        })

    new_platforms = snapshot_platforms(version)
    old_platforms = snapshot_platforms(previous)
    if new_platforms and old_platforms:
        for symbol, platforms in sorted(old_platforms.items()):
            current = new_platforms.get(symbol, set())
            if len(platforms) == 2 and len(current) < 2:
                holds.append({
                    "reason": "symbol_lost_platform", "symbol": symbol,
                    "before": sorted(platforms), "after": sorted(current),
                })
    else:
        notes.append("no snapshot for one of the two builds; platform check skipped")

    compared = len(new_files & old_files)
    return {
        "gamever": version,
        "previous": previous,
        "safe": not holds and compared > 0,
        "files_compared": compared,
        "patterns_changed": patterns_changed,
        "coverage": {"before": f"{old_covered}/{old_total}", "after": f"{new_covered}/{new_total}"},
        "holds": holds,
        "notes": notes,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-gamever", required=True, help="the freshly generated build")
    parser.add_argument("-prev", help="build to compare against (default: the previous published one)")
    parser.add_argument("-json", action="store_true", help="machine-readable verdict on stdout")
    args = parser.parse_args()

    versions = published_versions()
    if args.gamever not in versions:
        print(f"no generated gamedata for {args.gamever}", file=sys.stderr)
        return 1
    previous = args.prev
    if not previous:
        earlier = [v for v in versions if game_version_sort_key(v) < game_version_sort_key(args.gamever)]
        if not earlier:
            print(f"{args.gamever} is the first published build; nothing to compare", file=sys.stderr)
            return 1
        previous = earlier[-1]
    if previous not in versions:
        print(f"no generated gamedata for {previous}", file=sys.stderr)
        return 1

    verdict = decide(args.gamever, previous)
    if args.json:
        print(json.dumps(verdict, indent=1))
    else:
        print(f"{verdict['gamever']} against {previous}")
        print(f"  files compared        : {verdict['files_compared']}")
        print(f"  byte patterns changed : {verdict['patterns_changed']}")
        print(f"  plugin keys filled    : {verdict['coverage']['before']} -> {verdict['coverage']['after']}")
        for note in verdict["notes"]:
            print(f"  note                  : {note}")
        if verdict["safe"]:
            print("  verdict               : SAFE, a rebuild relocation and nothing more")
        else:
            grouped: dict[str, int] = {}
            for hold in verdict["holds"]:
                grouped[hold["reason"]] = grouped.get(hold["reason"], 0) + 1
            print("  verdict               : HOLD for review")
            for reason, count in sorted(grouped.items(), key=lambda item: -item[1]):
                print(f"    {reason}: {count}")
            for hold in verdict["holds"][:8]:
                detail = " ".join(f"{k}={v}" for k, v in hold.items() if k != "reason")
                print(f"    - {hold['reason']}: {detail}")
            if len(verdict["holds"]) > 8:
                print(f"    ... and {len(verdict['holds']) - 8} more")
    return 0 if verdict["safe"] else 10


if __name__ == "__main__":
    sys.exit(main())
