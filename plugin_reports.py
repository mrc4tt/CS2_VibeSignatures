#!/usr/bin/env python3
"""What CounterStrikeSharp servers run, as they report it: which gamedata files we already
generate, and which ones nobody here knows yet.

A server that opts in (CounterStrikeSharp's GamedataReportEnabled) posts one report per
start to POST /api/report (verify_service.py):

  {"build": "14196", "platform": "linux", "install": "<random hex, stable per server>",
   "files": [{"name": "matchzy.json", "sha256": "...", "keys": ["A", "B"], "broken": ["B"]}]}

No file text is sent: names, key names and a hash. Each file is answered

  known   the sha256 is one we published (any build): the plugin and its latest/ URL
  plugin  not a published copy, but it shares most of its keys with a plugin we generate
          (another release of it): the plugin and its latest/ URL
  unknown neither: recorded here as demand, so a generator gets written for what servers
          actually run

Only `unknown` files are stored, one record per sha256 under <user-file store>/reports/:
the file name, its key names, which keys were broken on which build, how many distinct
servers run it (the install id is kept only as a truncated sha256) and when it was seen.
`uv run plugin_reports.py list` ranks them by servers; nothing here is ever published.
"""

import argparse
import hashlib
import json
import os
import re
import sys
import threading
import time

import user_files as UF

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
INSTALL_RE = re.compile(r"^[0-9a-f]{16,64}$")
BUILD_RE = re.compile(r"^\d{4,6}[a-z]?$")
MAX_FILES_PER_REPORT = 200
MAX_KEYS_PER_FILE = 2000
MAX_KEY_LENGTH = 200
MAX_RECORDS = 5000
MAX_INSTALLS = 500
MAX_BUILDS = 20
# A non-identical file is another release of a plugin we generate when it shares at least
# this share of its keys with that plugin's newest file, and at least this many.
PLUGIN_SHARE = 0.5
PLUGIN_MIN_KEYS = 2
GAMEDATA_SUFFIXES = (".json", ".jsonc", ".txt", ".cfg")


class BadReport(Exception):
    """A report this service refuses; the message is safe to show the caller."""


# -- what we publish -----------------------------------------------------------

def _build_key(build):
    digits = re.match(r"\d+", build).group()
    return int(digits), build[len(digits):]


class Published:
    """sha256 of every gamedata file under gamedata/<build>/<plugin>/, and the key names of
    each plugin's newest files. Rebuilt when a build directory appears or changes."""

    def __init__(self, root=REPO_ROOT, refresh_seconds=300):
        self.root, self.refresh_seconds = root, refresh_seconds
        self.lock = threading.Lock()
        self.loaded_at, self.signature = 0.0, None
        self.hashes = {}  # sha256 -> (plugin, fileName)
        self.newest = []  # [(plugin, fileName, set of key names)], newest build of each plugin

    def _signature(self, base):
        try:
            return tuple(sorted((name, os.stat(os.path.join(base, name)).st_mtime_ns) for name in os.listdir(base)))
        except OSError:
            return None

    def get(self):
        with self.lock:
            now = time.monotonic()
            if self.signature is not None and now - self.loaded_at < self.refresh_seconds:
                return self
            base = os.path.join(self.root, "gamedata")
            signature = self._signature(base)
            if signature != self.signature:
                self._load(base)
                self.signature = signature
            self.loaded_at = now
            return self

    def _load(self, base):
        hashes, newest, seen = {}, [], set()
        builds = sorted((name for name in os.listdir(base) if BUILD_RE.match(name) and os.path.isdir(os.path.join(base, name))),
                        key=_build_key, reverse=True) if os.path.isdir(base) else []
        for build in builds:
            build_dir = os.path.join(base, build)
            for plugin in sorted(os.listdir(build_dir)):
                for folder, _dirs, names in os.walk(os.path.join(build_dir, plugin)):
                    for name in sorted(names):
                        if name.endswith(".metadata.json") or not name.endswith(GAMEDATA_SUFFIXES):
                            continue
                        path = os.path.join(folder, name)
                        try:
                            with open(path, "rb") as handle:
                                data = handle.read()
                        except OSError:
                            continue
                        hashes.setdefault(hashlib.sha256(data).hexdigest(), (plugin, name))
                        if (plugin, name) not in seen:
                            seen.add((plugin, name))
                            newest.append((plugin, name, _key_names(data)))
        self.hashes, self.newest = hashes, newest


def _key_names(data):
    """Top-level gamedata keys of a JSON file; empty for other formats (they are matched by hash only)."""
    try:
        parsed = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError):
        return set()
    if not isinstance(parsed, dict):
        return set()
    return {key for key in parsed if isinstance(key, str) and not key.startswith("_")}


def classify(entry, published):
    """-> the answer for one reported file (see the module docstring)."""
    out = {"name": entry["name"], "sha256": entry["sha256"]}
    hit = published.hashes.get(entry["sha256"])
    if hit:
        plugin, name = hit
        return {**out, "status": "known", "plugin": plugin, "feed": f"{plugin}/{name}"}

    keys = set(entry["keys"])
    best, best_count, tie = None, 0, False
    if keys:
        for plugin, name, shipped in published.newest:
            if not shipped:
                continue
            shared = len(keys & shipped)
            if shared < PLUGIN_MIN_KEYS or shared < PLUGIN_SHARE * len(keys):
                continue
            if shared > best_count:
                best, best_count, tie = (plugin, name), shared, False
            elif shared == best_count:
                tie = True
    if best and not tie:
        plugin, name = best
        return {**out, "status": "plugin", "plugin": plugin, "feed": f"{plugin}/{name}"}
    return {**out, "status": "unknown"}


# -- validation ----------------------------------------------------------------

def _text(value, field, limit):
    if not isinstance(value, str) or not value or len(value) > limit:
        raise BadReport(f"{field} must be a non-empty string of at most {limit} characters")
    return value


def parse_report(body):
    if not isinstance(body, dict):
        raise BadReport("body must be a JSON object")
    build = body.get("build")
    if not isinstance(build, str) or not BUILD_RE.match(build):
        raise BadReport("build must be a game build such as 14196")
    platform = body.get("platform")
    if platform not in ("linux", "windows"):
        raise BadReport("platform must be linux or windows")
    install = body.get("install")
    if not isinstance(install, str) or not INSTALL_RE.match(install):
        raise BadReport("install must be 16-64 lower-case hex characters")
    files = body.get("files")
    if not isinstance(files, list) or len(files) > MAX_FILES_PER_REPORT:
        raise BadReport(f"files must be a list of at most {MAX_FILES_PER_REPORT}")

    out = []
    for item in files:
        if not isinstance(item, dict):
            raise BadReport("each file must be an object")
        name = UF.clean_filename(_text(item.get("name"), "name", 200))
        sha = item.get("sha256")
        if not isinstance(sha, str) or not SHA_RE.match(sha):
            raise BadReport("sha256 must be 64 lower-case hex characters")
        lists = {}
        for field in ("keys", "broken"):
            values = item.get(field, [])
            if not isinstance(values, list) or len(values) > MAX_KEYS_PER_FILE:
                raise BadReport(f"{field} must be a list of at most {MAX_KEYS_PER_FILE}")
            lists[field] = sorted({_text(value, f"each of {field}", MAX_KEY_LENGTH) for value in values})
        out.append({"name": name, "sha256": sha, "keys": lists["keys"], "broken": lists["broken"]})
    return {"build": build, "platform": platform, "install": install, "files": out}


# -- the demand store ----------------------------------------------------------

def _reports_dir(root):
    path = os.path.join(root, "reports")
    os.makedirs(path, exist_ok=True)
    return path


def install_hash(install):
    return hashlib.sha256(install.encode()).hexdigest()[:16]


def record_unknown(report, entries, root=None, now=None):
    """Stores the `unknown` entries of one report. Returns how many records were written."""
    root = UF._root(root)
    now = int(now if now is not None else time.time())
    who = install_hash(report["install"])
    written = 0
    with UF.locked(root):
        base = _reports_dir(root)
        for entry in entries:
            path = os.path.join(base, f"{entry['sha256']}.json")
            try:
                record = json.loads(UF._read(path))
            except (OSError, ValueError):
                if len(os.listdir(base)) >= MAX_RECORDS:
                    continue
                record = {"sha256": entry["sha256"], "first_seen": now, "installs": [], "broken": {}, "platforms": []}
            record["name"] = entry["name"]
            record["keys"] = entry["keys"]
            record["last_seen"] = now
            if who not in record["installs"] and len(record["installs"]) < MAX_INSTALLS:
                record["installs"].append(who)
            if report["platform"] not in record["platforms"]:
                record["platforms"].append(report["platform"])
            broken = record["broken"]
            broken[report["build"]] = sorted(set(broken.get(report["build"], [])) | set(entry["broken"]))
            for build in sorted(broken, key=_build_key)[:-MAX_BUILDS]:
                del broken[build]
            UF._write(path, json.dumps(record, indent=2, sort_keys=True) + "\n", root)
            written += 1
    return written


def handle_report(body, published, root=None, now=None):
    """-> the JSON answer to POST /api/report. Raises BadReport."""
    report = parse_report(body)
    answers = [classify(entry, published) for entry in report["files"]]
    unknown = [entry for entry, answer in zip(report["files"], answers) if answer["status"] == "unknown"]
    if unknown:
        record_unknown(report, unknown, root=root, now=now)
    return {"build": report["build"], "files": answers}


def load_records(root=None):
    base = os.path.join(UF._root(root), "reports")
    out = []
    if not os.path.isdir(base):
        return out
    for name in sorted(os.listdir(base)):
        if not name.endswith(".json"):
            continue
        try:
            out.append(json.loads(UF._read(os.path.join(base, name))))
        except (OSError, ValueError):
            continue
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    listing = sub.add_parser("list", help="unknown gamedata files servers reported, most servers first")
    listing.add_argument("-root", default=UF.ROOT)
    listing.add_argument("-json", action="store_true")
    args = parser.parse_args()

    records = sorted(load_records(args.root), key=lambda r: (-len(r.get("installs", [])), -r.get("last_seen", 0)))
    if args.json:
        print(json.dumps(records, indent=2))
        return 0
    if not records:
        print("no unknown gamedata files reported")
        return 0
    for record in records:
        newest = max(record.get("broken", {}) or {"-": []}, key=lambda b: _build_key(b) if b != "-" else (0, ""))
        broken = record.get("broken", {}).get(newest, [])
        seen = time.strftime("%Y-%m-%d", time.gmtime(record.get("last_seen", 0)))
        print(f"{len(record.get('installs', [])):4d} server(s)  {record.get('name', '?'):40s} {record['sha256'][:12]}  "
              f"{len(record.get('keys', []))} keys, {len(broken)} broken on {newest}, last {seen}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
