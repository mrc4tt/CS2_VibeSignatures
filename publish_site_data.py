#!/usr/bin/env python3
"""
publish_site_data.py - compute the two datasets the site cannot derive itself.

The published snapshot describes one build. Three of the site's panels are about
change over time and about how a number was checked, which no single snapshot
can answer:

  gamedata/history.json      per-key value history across every published build,
                             plus which build each change landed in, and the map
                             from a plugin key to the symbol that feeds it
  diagnostics/<build>.json   what validate_artifacts found, and the plan the
                             analysis ran with what each task produced

Both are small, deterministic and derived from files already in the repository,
so they are committed and published rather than recomputed in the browser.

    uv run publish_site_data.py                 # newest build, both files
    uv run publish_site_data.py -gamever 14181
    uv run publish_site_data.py -skip-validator # keep the previous validator section
    uv run publish_site_data.py -history-only   # history.json alone, no binaries needed
    uv run publish_site_data.py -check          # is the committed history.json current?

`-check` writes nothing and exits 10 when the committed history.json disagrees
with what the gamedata in the tree implies. It needs no binaries, so CI can run
it: the site's history, fragility and "since my build" panels read that committed
file, and without the check a hand edit to gamedata/ publishes correct files
beside stale history.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import re
import subprocess
import sys

import yaml

GAMEDATA_ROOT = "gamedata"
SNAPSHOT_ROOT = "gamesymbols"
DIAGNOSTICS_ROOT = "diagnostics"
CONFIG_ROOT = "configs"
PREPROCESSOR_ROOT = "ida_preprocessor_scripts"
KIND_WORDS = {
    "signatures", "signature", "offsets", "offset", "patches", "patch",
    "addresses", "address", "games", "csgo", "library", "keys",
}
PLATFORM_KEYS = ("linux", "windows", "linuxsteamrt64", "win64")


def sort_key(tag: str) -> tuple[int, str]:
    match = re.fullmatch(r"(\d+)([a-z]?)", tag)
    return (int(match.group(1)), match.group(2)) if match else (0, tag)


def _committed_dates() -> dict[str, str]:
    """publishedAt as the last published history.json recorded it."""
    try:
        with open(os.path.join(GAMEDATA_ROOT, "history.json"), encoding="utf-8") as handle:
            previous = json.load(handle)
    except Exception:
        return {}
    return {
        entry["gameVersion"]: entry["publishedAt"]
        for entry in previous.get("builds", [])
        if isinstance(entry, dict) and entry.get("gameVersion") and entry.get("publishedAt")
    }


def _is_shallow() -> bool:
    """
    A shallow clone cannot answer when a path first appeared. Worse than being
    unable: with --depth 1 the single commit is the root, so `git log
    --diff-filter=A -- <path>` reports every path as added in HEAD and hands
    back HEAD's date. That looked like a working answer and turned all sixteen
    build dates into today, which is what made the CI check fail.
    """
    completed = subprocess.run(
        ["git", "rev-parse", "--is-shallow-repository"],
        capture_output=True, text=True,
    )
    return completed.stdout.strip() == "true"


def build_published_at(build: str, fallback: dict[str, str]) -> str | None:
    """
    When this build's gamedata first landed. The first commit that added
    gamedata/<build>/ is the honest answer: a snapshot's own last_publish_time
    only says when it was last re-packed, which moves every time the pipeline is
    re-run and would tell a server owner nothing about the age of the numbers.

    A shallow clone cannot answer that, and answers wrongly rather than not at
    all (see _is_shallow), so there the date already recorded in the committed
    history.json is reused. A build missing from that record gets no date, which
    is honest: the record is genuinely stale and -check should say so.
    """
    if _is_shallow():
        return fallback.get(build)
    completed = subprocess.run(
        ["git", "log", "--diff-filter=A", "--format=%aI", "--", os.path.join(GAMEDATA_ROOT, build)],
        capture_output=True, text=True,
    )
    lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    if lines:
        return lines[-1]
    return fallback.get(build)


def builds() -> list[str]:
    tags = [t for t in os.listdir(GAMEDATA_ROOT) if re.fullmatch(r"\d+[a-z]?", t)]
    return sorted(tags, key=sort_key)


def strip_jsonc(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"(^|\s)//[^\n]*", "", text)
    return re.sub(r",(\s*[}\]])", r"\1", text)


def key_name(path: tuple[str, ...]) -> str:
    for segment in reversed(path):
        if segment.lower() not in KIND_WORDS:
            return segment
    return path[-1]


def read_values(path: str) -> dict[str, list[object]] | None:
    """key -> [linux, windows]; None when the file is absent or unparsable."""
    if not os.path.exists(path):
        return None
    raw = open(path, encoding="utf-8").read()
    out: dict[str, list[object]] = {}
    if path.endswith(".txt"):
        for match in re.finditer(r'"([^"]+)"\s*\{(.*?)\n\t*\}', raw, re.S):
            body = match.group(2)
            linux = re.search(r'"(?:linux|linuxsteamrt64)"\s+"([^"]*)"', body)
            windows = re.search(r'"(?:windows|win64)"\s+"([^"]*)"', body)
            out[match.group(1)] = [linux.group(1) if linux else None, windows.group(1) if windows else None]
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
                out[key_name(prefix + (key,))] = [
                    value.get("linux", value.get("linuxsteamrt64")),
                    value.get("windows", value.get("win64")),
                ]
            else:
                walk(value, prefix + (key,))

    walk(document)
    return out


def generated_files(build: str) -> list[str]:
    root = os.path.join(GAMEDATA_ROOT, build)
    found = []
    for base, _dirs, names in os.walk(root):
        for name in names:
            if not name.endswith(".metadata.json"):
                found.append(os.path.relpath(os.path.join(base, name), root))
    return sorted(found)


def fold(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name).replace("::", "_").replace(".", "_").lower())


def symbol_index(build: str) -> dict[str, str]:
    """folded name -> "<module>/<symbol>", including every alias the config declares."""
    path = os.path.join(SNAPSHOT_ROOT, f"{build}.yaml")
    if not os.path.exists(path):
        return {}
    snapshot = yaml.safe_load(open(path, encoding="utf-8"))
    index: dict[str, str] = {}
    for file_path in snapshot.get("files", {}):
        module, rest = file_path.split("/", 1)
        symbol = rest.rsplit(".", 2)[0]
        index.setdefault(fold(symbol), f"{module}/{symbol}")

    config_path = os.path.join(CONFIG_ROOT, f"{build}.yaml")
    if os.path.exists(config_path):
        config = yaml.safe_load(open(config_path, encoding="utf-8"))
        for module in config.get("modules", []) or []:
            name = module.get("name")
            for symbol in module.get("symbols", []) or []:
                if not isinstance(symbol, dict):
                    continue
                target = symbol.get("name")
                if not target:
                    continue
                aliases = symbol.get("alias") or []
                if isinstance(aliases, str):
                    aliases = [aliases]
                for alias in aliases:
                    index.setdefault(fold(alias), f"{name}/{target}")
    return index


def build_history(newest: str) -> dict:
    order = builds()
    known_dates = _committed_dates()
    index = symbol_index(newest)
    per_build = collections.Counter()
    files: dict[str, dict] = {}
    key_to_symbol: dict[str, str] = {}

    for relative in generated_files(newest):
        series = [(build, read_values(os.path.join(GAMEDATA_ROOT, build, relative))) for build in order]
        keys: set[str] = set()
        for _build, values in series:
            if values:
                keys |= set(values)
        entries: dict[str, dict] = {}
        for key in sorted(keys):
            points: list[list[object]] = []
            changes: list[str] = []
            previous: list[str] | None = None
            for build, values in series:
                if not values or key not in values:
                    continue
                current = [str(part) for part in values[key]]
                if previous is None:
                    points.append([build, *values[key]])
                elif current != previous:
                    points.append([build, *values[key]])
                    changes.append(build)
                previous = current
            for build in changes:
                per_build[build] += 1
            entries[key] = {"points": points, "changes": changes}
            symbol = index.get(fold(key))
            if symbol:
                key_to_symbol[f"{relative}|{key}"] = symbol
        files[relative] = entries

    symbol_to_keys: dict[str, list[list[str]]] = collections.defaultdict(list)
    for composite, symbol in key_to_symbol.items():
        relative, key = composite.split("|", 1)
        symbol_to_keys[symbol].append([relative, key])

    return {
        "schemaVersion": 1,
        "gameVersion": newest,
        "builds": [
            {
                "gameVersion": build,
                "keyChanges": per_build.get(build, 0),
                "publishedAt": build_published_at(build, known_dates),
            }
            for build in order
        ],
        "files": files,
        "keyToSymbol": key_to_symbol,
        "symbolToKeys": {symbol: sorted(keys) for symbol, keys in symbol_to_keys.items()},
    }


def recovery_method(task: str) -> str:
    path = os.path.join(PREPROCESSOR_ROOT, f"{task}.py")
    if not os.path.exists(path):
        return "none"
    source = open(path, encoding="utf-8").read()
    if re.search(r"LLM_DECOMPILE\s*=\s*\[\s*[^\]\s]", source):
        return "llm"
    if re.search(r"INHERIT_VFUNCS\s*=\s*\[\s*\(", source):
        return "vtable"
    if re.search(r"FUNC_XREFS\s*=\s*\[\s*[^\]\s]", source):
        return "xref"
    if "TARGET_FUNCTION_NAMES" in source or "TARGET_" in source:
        return "reloc"
    return "other"


def build_run_report(build: str) -> list[dict]:
    config_path = os.path.join(CONFIG_ROOT, f"{build}.yaml")
    snapshot_path = os.path.join(SNAPSHOT_ROOT, f"{build}.yaml")
    if not (os.path.exists(config_path) and os.path.exists(snapshot_path)):
        return []
    config = yaml.safe_load(open(config_path, encoding="utf-8"))
    published = set(yaml.safe_load(open(snapshot_path, encoding="utf-8")).get("files", {}))
    rows = []
    for module in config.get("modules", []) or []:
        module_name = module.get("name")
        for task in module.get("skills", []) or []:
            name = task.get("name")
            if not name:
                continue
            pinned = task.get("platform")
            required = task.get("expected_output") or []
            optional = task.get("optional_output") or []
            if isinstance(required, str):
                required = [required]
            if isinstance(optional, str):
                optional = [optional]
            platforms = [pinned] if pinned else ["linux", "windows"]
            produced = missing = optional_missing = 0
            for spec in list(required) + list(optional):
                is_required = spec in required
                for platform in platforms:
                    if "{platform}" not in spec and platform != platforms[0]:
                        continue
                    artifact = f"{module_name}/{spec.replace('{platform}', platform)}"
                    if artifact in published:
                        produced += 1
                    elif is_required:
                        missing += 1
                    else:
                        optional_missing += 1
            rows.append({
                "module": module_name,
                "task": name,
                "platform": pinned or "both",
                "method": recovery_method(name),
                "produced": produced,
                "missing": missing,
                "optionalMissing": optional_missing,
                "status": "succeeded" if missing == 0 and produced > 0 else ("failed" if missing else "skipped"),
            })
    return rows


def build_diagnostics(build: str, *, skip_validator: bool) -> dict:
    validator: dict = {"ran": False}
    if not skip_validator:
        completed = subprocess.run(
            ["uv", "run", "validate_artifacts.py", "-gamever", build, "-json"],
            capture_output=True, text=True,
        )
        if completed.returncode == 0 and completed.stdout.strip():
            report = json.loads(completed.stdout)
            by_symbol: dict[str, list[dict]] = collections.defaultdict(list)
            for warning in report.get("warnings", []):
                by_symbol[f"{warning['module']}/{warning['symbol']}"].append({
                    "platform": warning.get("platform"),
                    "category": warning.get("category"),
                    "message": warning.get("message"),
                })
            validator = {
                "ran": True,
                "artifacts": report.get("artifacts", 0),
                "slotVerified": report.get("slot_verified", 0),
                "errors": len(report.get("errors", [])),
                "warnings": len(report.get("warnings", [])),
                "bySymbol": dict(by_symbol),
            }
        else:
            validator = {"ran": False, "reason": (completed.stderr or "validate_artifacts failed").strip()[:200]}
    return {
        "schemaVersion": 1,
        "gameVersion": build,
        "validator": validator,
        "run": build_run_report(build),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-gamever", help="build to publish for (default: the newest)")
    parser.add_argument("-skip-validator", action="store_true", dest="skip_validator",
                        help="do not re-read the binaries; keep the previous validator section")
    parser.add_argument("-history-only", action="store_true", dest="history_only",
                        help="write gamedata/history.json only (needs no binaries)")
    parser.add_argument("-check", action="store_true",
                        help="write nothing; exit 10 if the committed history.json is stale")
    args = parser.parse_args()

    available = builds()
    if not available:
        print("no generated gamedata to summarise", file=sys.stderr)
        return 1
    build = args.gamever or available[-1]
    if build not in available:
        print(f"no generated gamedata for {build}", file=sys.stderr)
        return 1

    history = build_history(build)
    os.makedirs(GAMEDATA_ROOT, exist_ok=True)
    history_path = os.path.join(GAMEDATA_ROOT, "history.json")

    if args.check:
        fresh = json.dumps(history, separators=(",", ":"), sort_keys=True)
        try:
            with open(history_path, encoding="utf-8") as handle:
                committed = json.dumps(json.load(handle), separators=(",", ":"), sort_keys=True)
        except Exception as error:
            print(f"{history_path}: cannot read ({error}); run publish_site_data.py", file=sys.stderr)
            return 10
        if committed == fresh:
            print(f"{history_path} is current for {build}")
            return 0
        old = json.loads(committed)
        drift = []
        if old.get("gameVersion") != history["gameVersion"]:
            drift.append(f"gameVersion {old.get('gameVersion')} -> {history['gameVersion']}")
        old_files, new_files = set(old.get("files", {})), set(history["files"])
        for missing in sorted(new_files - old_files):
            drift.append(f"file not recorded: {missing}")
        for extra in sorted(old_files - new_files):
            drift.append(f"file no longer generated: {extra}")
        old_builds = {entry.get("gameVersion"): entry for entry in old.get("builds", [])
                      if isinstance(entry, dict)}
        new_builds = {entry["gameVersion"]: entry for entry in history["builds"]}
        for gone in sorted(set(old_builds) - set(new_builds)):
            drift.append(f"build no longer present: {gone}")
        for added in sorted(set(new_builds) - set(old_builds)):
            drift.append(f"build not recorded: {added}")
        for version in sorted(set(old_builds) & set(new_builds)):
            was, now = old_builds[version], new_builds[version]
            for field in sorted(set(was) | set(now)):
                if was.get(field) != now.get(field):
                    drift.append(f"build {version}: {field} {was.get(field)!r} -> {now.get(field)!r}")
        for path in sorted(old_files & new_files):
            old_keys, new_keys = old["files"][path], history["files"][path]
            changed = [k for k in set(old_keys) | set(new_keys)
                       if old_keys.get(k) != new_keys.get(k)]
            if changed:
                drift.append(f"{path}: {len(changed)} key(s) differ, e.g. {sorted(changed)[0]}")
        print(f"{history_path} is stale for {build}:", file=sys.stderr)
        for line in drift[:10]:
            print(f"  {line}", file=sys.stderr)
        if len(drift) > 10:
            print(f"  ... and {len(drift) - 10} more", file=sys.stderr)
        print("  fix: uv run publish_site_data.py, then commit gamedata/history.json", file=sys.stderr)
        return 10
    with open(history_path, "w", encoding="utf-8") as handle:
        json.dump(history, handle, separators=(",", ":"), sort_keys=True)
        handle.write("\n")
    changed = sum(entry["keyChanges"] for entry in history["builds"])
    print(f"{history_path}: {len(history['files'])} files, "
          f"{sum(len(keys) for keys in history['files'].values())} keys, "
          f"{changed} recorded changes across {len(history['builds'])} builds, "
          f"{len(history['keyToSymbol'])} keys mapped to a symbol")

    if args.history_only:
        return 0

    diagnostics = build_diagnostics(build, skip_validator=args.skip_validator)
    os.makedirs(DIAGNOSTICS_ROOT, exist_ok=True)
    diagnostics_path = os.path.join(DIAGNOSTICS_ROOT, f"{build}.json")
    if args.skip_validator and os.path.exists(diagnostics_path):
        try:
            previous = json.load(open(diagnostics_path, encoding="utf-8"))
            if previous.get("validator", {}).get("ran"):
                diagnostics["validator"] = previous["validator"]
        except Exception:
            pass
    with open(diagnostics_path, "w", encoding="utf-8") as handle:
        json.dump(diagnostics, handle, separators=(",", ":"), sort_keys=True)
        handle.write("\n")
    validator = diagnostics["validator"]
    print(f"{diagnostics_path}: {len(diagnostics['run'])} tasks in the plan, "
          + (f"validator {validator['errors']} errors / {validator['warnings']} warnings / "
             f"{validator['slotVerified']} slots confirmed" if validator.get("ran") else "validator not run"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
