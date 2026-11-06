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

Every file (known ones too) also counts in a per-build tally of broken keys,
reports/broken/<build>.json: per feed file (`<plugin>/<file>`, or `sha256:<hash>` for an
unknown one) which servers run it and which of them report each key broken. Each server
counts with its latest report only, so a key it fixed (plugin gamedata update) drops out.
Newest TALLY_BUILDS builds only; a build more than TALLY_AHEAD past the newest we publish is
refused (a server is ahead of us right after an update - that is the early warning - but not
by more). When the newest build's tally changes in a way worth knowing (a key broken for the
first time, or its server count crossing one of DIGEST_LEVELS), `Digest` sends the whole
tally to the Discord bot (event `server-reports`, admin channel, one message per build),
from its own thread and at most once per DIGEST_DEBOUNCE seconds per build.
`uv run plugin_reports.py broken [build]` prints it.
"""

import argparse
import hashlib
import json
import os
import re
import sys
import threading
import time
import urllib.request

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
# The broken-key tally (reports/broken/<build>.json).
TALLY_BUILDS = 6
TALLY_AHEAD = 3
TALLY_MAX_FILES = 300
TALLY_MAX_KEYS = 200          # broken keys kept per file
TALLY_MAX_INSTALLS = 500      # servers kept per file
TALLY_MAX_ENTRIES = 50000     # install hashes in one build's tally, all lists together (~1 MB)
DIGEST_LEVELS = (1, 5, 20)
DIGEST_DEBOUNCE = 1800
DIGEST_SETTLE = 60            # a burst of reports right after an update goes out as one digest
DIGEST_FILES = 25
DIGEST_KEYS = 15


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
        self.builds = []  # build directories, newest first

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
        self.hashes, self.newest, self.builds = hashes, newest, builds


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


# -- the broken-key tally -------------------------------------------------------

def _tally_dir(root):
    path = os.path.join(_reports_dir(root), "broken")
    os.makedirs(path, exist_ok=True)
    return path


def tally_builds(root=None):
    """Builds with a tally, newest first."""
    base = os.path.join(UF._root(root), "reports", "broken")
    if not os.path.isdir(base):
        return []
    builds = [name[:-5] for name in os.listdir(base) if name.endswith(".json") and BUILD_RE.match(name[:-5])]
    return sorted(builds, key=_build_key, reverse=True)


def load_tally(build, root=None):
    if not isinstance(build, str) or not BUILD_RE.match(build):
        return None
    try:
        return json.loads(UF._read(os.path.join(UF._root(root), "reports", "broken", f"{build}.json")))
    except (OSError, ValueError):
        return None


def _feed_id(answer):
    if answer["status"] in ("known", "plugin"):
        return answer["feed"]
    return f"sha256:{answer['sha256']}"


def _entries(tally):
    return sum(len(f["installs"]) + sum(len(v) for v in f["broken"].values()) for f in tally["files"].values())


def level(servers):
    return sum(1 for threshold in DIGEST_LEVELS if servers >= threshold)


def _levels(tally):
    return {f"{fid}|{key}": level(len(who)) for fid, f in tally["files"].items() for key, who in f["broken"].items()}


def record_tally(report, answers, published, root=None, now=None):
    """Counts one report in its build's tally. -> True when the tally of the newest build
    changed in a way worth a digest (see the module docstring), else False."""
    build = report["build"]
    newest_published = published.builds[0] if published.builds else None
    if newest_published and _build_key(build)[0] > _build_key(newest_published)[0] + TALLY_AHEAD:
        return False
    root = UF._root(root)
    now = int(now if now is not None else time.time())
    who = install_hash(report["install"])
    with UF.locked(root):
        base = _tally_dir(root)
        builds = tally_builds(root)
        if build not in builds and len(builds) >= TALLY_BUILDS and _build_key(build) < _build_key(builds[TALLY_BUILDS - 1]):
            return False  # older than every build kept: it would be dropped at once
        path = os.path.join(base, f"{build}.json")
        tally = load_tally(build, root) or {"build": build, "first_seen": now, "files": {}, "notified": {}}
        entries = _entries(tally)
        for entry, answer in zip(report["files"], answers):
            fid = _feed_id(answer)
            item = tally["files"].get(fid)
            if item is None:
                if len(tally["files"]) >= TALLY_MAX_FILES:
                    continue
                item = tally["files"][fid] = {"status": answer["status"], "installs": {}, "broken": {}}
            if answer["status"] == "unknown":
                item["name"] = entry["name"]
            item["status"] = answer["status"]
            if who not in item["installs"]:
                if len(item["installs"]) >= TALLY_MAX_INSTALLS or entries >= TALLY_MAX_ENTRIES:
                    continue
                entries += 1
            item["installs"][who] = report["platform"]
            # This server's latest report replaces its earlier one: a key it fixed drops out.
            broken = set(entry["broken"])
            for key in list(item["broken"]):
                if key not in broken and who in item["broken"][key]:
                    item["broken"][key].remove(who)
                    entries -= 1
                    if not item["broken"][key]:
                        del item["broken"][key]
            for key in sorted(broken):
                servers = item["broken"].get(key)
                if servers is None:
                    if len(item["broken"]) >= TALLY_MAX_KEYS:
                        continue
                    servers = item["broken"][key] = []
                if who not in servers and entries < TALLY_MAX_ENTRIES:
                    servers.append(who)
                    entries += 1
        tally["last_seen"] = now
        UF._write(path, json.dumps(tally, indent=1, sort_keys=True) + "\n", root)
        for old in tally_builds(root)[TALLY_BUILDS:]:
            try:
                os.remove(os.path.join(base, f"{old}.json"))
            except OSError:
                pass
        newest = tally_builds(root)[0]
    if build != newest:
        return False
    notified = tally.get("notified", {})
    return any(value > notified.get(name, 0) for name, value in _levels(tally).items())


def summarize(tally, max_files=DIGEST_FILES, max_keys=DIGEST_KEYS):
    """-> the tally as counts only (no install hashes): what the bot and the CLI show.
    Files with a broken key first, most affected servers first."""
    files = []
    for fid, item in tally.get("files", {}).items():
        platforms = item.get("installs", {})
        keys = []
        for key, who in item.get("broken", {}).items():
            linux = sum(1 for w in who if platforms.get(w) == "linux")
            keys.append({"key": key, "servers": len(who), "linux": linux, "windows": len(who) - linux})
        keys.sort(key=lambda k: (-k["servers"], k["key"]))
        out = {"file": fid if not fid.startswith("sha256:") else f"{item.get('name', '?')} ({fid[7:19]})",
               "status": item.get("status", "unknown"), "servers": len(platforms),
               "broken_servers": len({w for who in item.get("broken", {}).values() for w in who}),
               "broken": keys[:max_keys], "more_keys": max(0, len(keys) - max_keys)}
        files.append(out)
    files.sort(key=lambda f: (-f["broken_servers"], -len(f["broken"]) - f["more_keys"], -f["servers"], f["file"]))
    shown = [f for f in files if f["broken"]][:max_files]
    servers = {w for item in tally.get("files", {}).values() for w in item.get("installs", {})}
    return {"build": tally.get("build"), "servers": len(servers), "files_seen": len(files),
            "files_broken": sum(1 for f in files if f["broken"]), "files": shown,
            "more_files": sum(1 for f in files if f["broken"]) - len(shown),
            "first_seen": tally.get("first_seen"), "last_seen": tally.get("last_seen")}


class Digest:
    """Sends the newest build's tally to the Discord bot, off the request thread.

    `poke(build)` is cheap and never blocks on the network. The first poke of a build waits
    `settle` seconds (one digest for the burst of server starts after an update); after a
    send, the next one for that build waits until `debounce` seconds have passed. What is sent
    is the tally as it stands when the send happens. `notified` in the tally is written only
    after the bot accepted it, so a lost send is retried by the next report that matters."""

    def __init__(self, url, secret, root=None, debounce=DIGEST_DEBOUNCE, settle=DIGEST_SETTLE,
                 send=None, clock=time.monotonic):
        self.url, self.secret, self.root = url, secret, root
        self.debounce, self.settle, self.clock = debounce, settle, clock
        self.send = send or self._post
        self.cond = threading.Condition()
        self.due = {}    # build -> monotonic time to send at
        self.sent = {}   # build -> monotonic time of the last send
        self.thread = None

    @classmethod
    def from_env(cls, root=None, environ=None):
        environ = os.environ if environ is None else environ
        url = environ.get("AUTOPILOT_BOT_URL", "").strip()
        secret = environ.get("AUTOPILOT_BOT_SECRET", "").strip()
        return cls(url, secret, root=root) if url and secret else None

    def poke(self, build):
        with self.cond:
            if build in self.due:
                return
            now = self.clock()
            last = self.sent.get(build)
            self.due[build] = max(now + self.settle, last + self.debounce if last is not None else 0)
            if self.thread is None:
                self.thread = threading.Thread(target=self._loop, name="report-digest", daemon=True)
                self.thread.start()
            self.cond.notify()

    def _loop(self):
        while True:
            with self.cond:
                while not self.due:
                    self.cond.wait()
                build, when = min(self.due.items(), key=lambda item: item[1])
                wait = when - self.clock()
                if wait > 0:
                    self.cond.wait(wait)
                    continue
                del self.due[build]
                self.sent[build] = self.clock()
            try:
                self.flush(build)
            except Exception as error:  # a stopped bot must never take the service down
                print(f"report digest for {build} not delivered: {error}", file=sys.stderr, flush=True)

    def flush(self, build):
        """Sends the build's digest now (the worker calls this; tests call it directly)."""
        root = UF._root(self.root)
        tally = load_tally(build, root)
        if not tally:
            return False
        summary = summarize(tally)
        self.send({"outcome": "server-reports", "gamever": build, "detail": "", "reports": summary})
        with UF.locked(root):
            current = load_tally(build, root)
            if current:
                current["notified"] = _levels(tally)
                UF._write(os.path.join(_tally_dir(root), f"{build}.json"),
                          json.dumps(current, indent=1, sort_keys=True) + "\n", root)
        return True

    def _post(self, payload):
        request = urllib.request.Request(
            self.url, data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.secret}"})
        with urllib.request.urlopen(request, timeout=10) as response:
            response.read()


def handle_report(body, published, root=None, now=None, digest=None):
    """-> the JSON answer to POST /api/report. Raises BadReport."""
    report = parse_report(body)
    answers = [classify(entry, published) for entry in report["files"]]
    unknown = [entry for entry, answer in zip(report["files"], answers) if answer["status"] == "unknown"]
    if unknown:
        record_unknown(report, unknown, root=root, now=now)
    if record_tally(report, answers, published, root=root, now=now) and digest is not None:
        digest.poke(report["build"])
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


def print_broken(summary):
    seen = time.strftime("%Y-%m-%d %H:%M", time.gmtime(summary.get("last_seen") or 0))
    print(f"CS2 {summary['build']}: {summary['servers']} server(s) reported, {summary['files_broken']} of "
          f"{summary['files_seen']} file(s) with broken keys, last report {seen} UTC")
    for item in summary["files"]:
        print(f"\n  {item['file']}  [{item['status']}]  {item['broken_servers']}/{item['servers']} server(s) affected")
        for key in item["broken"]:
            print(f"    {key['servers']:4d}  {key['key']}  (linux {key['linux']}, windows {key['windows']})")
        if item["more_keys"]:
            print(f"          ... {item['more_keys']} more key(s)")
    if summary["more_files"]:
        print(f"\n  ... {summary['more_files']} more file(s)")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    listing = sub.add_parser("list", help="unknown gamedata files servers reported, most servers first")
    listing.add_argument("-root", default=UF.ROOT)
    listing.add_argument("-json", action="store_true")
    broken = sub.add_parser("broken", help="keys servers report broken, per feed file (newest build by default)")
    broken.add_argument("build", nargs="?")
    broken.add_argument("-root", default=UF.ROOT)
    broken.add_argument("-json", action="store_true")
    broken.add_argument("-all", action="store_true", help="every file and key, not the digest's top ones")
    args = parser.parse_args()

    if args.command == "broken":
        builds = tally_builds(args.root)
        build = args.build or (builds[0] if builds else None)
        tally = load_tally(build, args.root) if build else None
        if not tally:
            print(f"no broken-key tally for {build or 'any build'}" + (f" (have: {', '.join(builds)})" if builds else ""))
            return 1 if args.build else 0
        summary = summarize(tally, *((10**6, 10**6) if args.all else ()))
        if args.json:
            print(json.dumps(summary, indent=2))
        else:
            print_broken(summary)
        return 0

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
