#!/usr/bin/env python3
"""Answer "is my gamedata file still right?" over HTTP, for sig.miksen.me and the bot.

A thin front for verify_plugin_gamedata: the same judgement the pipeline gates a
deploy on, run against an uploaded file instead of a shipped one. Nothing here
decides a verdict of its own.

  POST /api/verify  {"gamedata": "<file text>", "filename"?, "build"?, "platform"?}
      every entry judged per platform, plus a fix for each bad one this build knows
      the right value of (from the matching shipped file, or the offset's record)
  POST /api/check   {"signature", "platform", "module"?, "build"?}
      one pattern scanned against one binary, by CounterStrikeSharp's rules
  GET  /api/builds  the builds whose binaries are on disk (only those can be scanned)
  GET  /api/health

Uploads are parsed as data (JSON, JSONC, KeyValues, key=value) and never executed,
never written to disk and never used as a path. The service binds loopback only;
nginx in front of it owns TLS, the per-IP rate limit and the body cap.

Loading a build's snapshot takes seconds, so workers are long-lived processes that
keep the last build they judged and only reload when a request names another one.

  uv run verify_service.py -port 8787 -workers 4
"""

import argparse
import concurrent.futures as cf
import hashlib
import json
import multiprocessing
import os
import re
import sys
import threading
import traceback
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import verify_plugin_gamedata as VPG

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
BUILD_RE = re.compile(r"^\d{4,6}[a-z]?$")
MAX_BODY = 256 * 1024
MAX_PATTERN = 600
MAX_ENTRIES = 2000
# A shipped file is the upload's counterpart when it holds at least this share of its keys.
MATCH_SHARE = 0.5
BAD_STATUSES = ("broken", "ambiguous", "mismatch", "unparsable", "too-few-literals")


class BadRequest(Exception):
    pass


# -- build discovery ----------------------------------------------------------

def _build_key(build):
    digits = re.match(r"\d+", build).group()
    return int(digits), build[len(digits):]


def scannable_builds(root=REPO_ROOT, bindir="bin"):
    """Builds with both binaries and a snapshot on disk, newest first."""
    base = os.path.join(root, bindir)
    if not os.path.isdir(base):
        return []
    out = [name for name in os.listdir(base)
           if BUILD_RE.match(name) and os.path.isdir(os.path.join(base, name))
           and os.path.isfile(os.path.join(root, "gamesymbols", f"{name}.yaml"))]
    return sorted(out, key=_build_key, reverse=True)


# -- matching an upload to the file this repo ships ---------------------------

def shipped_files(gamever, root=REPO_ROOT):
    """[(plugin, path)] of every gamedata file shipped for a build."""
    base = os.path.join(root, "gamedata", gamever)
    out = []
    if not os.path.isdir(base):
        return out
    for plugin in sorted(os.listdir(base)):
        for folder, _, names in os.walk(os.path.join(base, plugin)):
            for name in sorted(names):
                if name.endswith(".metadata.json"):
                    continue
                if name.endswith((".json", ".jsonc", ".txt", ".cfg")):
                    out.append((plugin, os.path.join(folder, name)))
    return out


def match_shipped(entries, filename, candidates):
    """-> (plugin, path, shipped entries) of the shipped file the upload is a copy of, or None.

    By key overlap: plugins rename files, but a stale copy of a plugin's file still
    carries that plugin's keys. A same-named file wins a tie, so the two matchzy
    variants are told apart by name when their keys agree. Past that, the shipped
    file with fewer keys the upload lacks wins: a fork ships its upstream's keys
    plus its own, so stock CounterStrikeSharp and the mrc4tt fork both hold every
    key of a stock file, and only this tells the stock one is the copy.
    """
    keys = set(entries)
    if not keys:
        return None
    best, best_score = None, (0.0, False, 0.0)
    for plugin, path, shipped in candidates:
        shared = len(keys & set(shipped))
        share = shared / len(keys)
        score = (share, os.path.basename(path) == os.path.basename(filename or ""),
                 shared / len(shipped) if shipped else 0.0)
        if score > best_score:
            best, best_score = (plugin, path, shipped), score
    return best if best_score[0] >= MATCH_SHARE else None


def suggest_fixes(results, entries, shipped=None, vtables=None, shipped_vtables=None):
    """[{key, platform, from, to, source}] for every bad value this build knows the right one of.

    Only a contradicted value is replaced, and only with a value this repo shipped for
    the same key (the pipeline verified it) or, for an offset, the record it was judged
    against. A value with no known replacement is left for a human: guessing one would
    be worse than leaving the file alone.
    """
    fixes = []
    shipped = shipped or {}
    for row in results:
        name = row["name"]
        entry = entries.get(name) or {}
        for platform, info in row["platforms"].items():
            current = (entry.get("values") or {}).get(platform)
            bad = info.get("status") in BAD_STATUSES or info.get("verification") == "contradicted"
            if bad and current not in (None, ""):
                target, source = None, None
                known = ((shipped.get(name) or {}).get("values") or {}).get(platform)
                if known not in (None, "") and str(known) != str(current):
                    target, source = known, "shipped"
                elif (row.get("kind") == "offset" and info.get("status") == "mismatch"
                      and info.get("reference") is not None and not (VPG.OFFSET_DIVISORS or {}).get(name)):
                    target, source = info["reference"], "record"
                if target is not None:
                    fixes.append({"key": name, "platform": platform, "from": current, "to": target,
                                  "source": source})
            if info.get("vtable") in VPG.VTABLE_BAD:
                field = f"{platform}_index"
                have = ((vtables or {}).get(name) or {}).get(field)
                want = ((shipped_vtables or {}).get(name) or {}).get(field)
                if have is not None and want is not None and want != have:
                    fixes.append({"key": f"{name}.vtable", "platform": platform, "from": have, "to": want,
                                  "source": "shipped"})
    return fixes


def record_signature_fixes(results, entries, fixes, lookup, scan):
    """[{key, platform, from, to, source: 'record'}] for bad signatures no shipped value fixes.

    A plugin key this repo has a function record for gets that record's own signature,
    but only where the signature, scanned now and the way CounterStrikeSharp scans it,
    lands once and exactly on the function the record identified. That is the same
    evidence a verified value carries, so it is not a guess; a record without a
    signature, with one that no longer resolves, or for another module offers nothing.

    lookup(name, platform) -> record or None; scan(module, platform, pattern) -> check_signature.
    """
    taken = {(fix["key"], fix["platform"]) for fix in fixes}
    out = []
    for row in results:
        if row.get("kind") != "signature":
            continue
        name = row["name"]
        for platform, info in row["platforms"].items():
            current = ((entries.get(name) or {}).get("values") or {}).get(platform)
            bad = (info.get("status") in ("broken", "ambiguous") or info.get("func") == "mismatch"
                   or info.get("verification") == "contradicted")
            if not bad or current in (None, "") or (name, platform) in taken:
                continue
            record = lookup(name, platform)
            if not record or not record.get("func_sig") or VPG._int(record.get("func_va")) is None:
                continue
            if (record.get("_module") or "server") != row.get("module", "server"):
                continue
            pattern = str(record["func_sig"]).strip()
            if pattern == str(current).strip():
                continue
            hit = scan(row.get("module", "server"), platform, pattern)
            if hit.get("status") == "ok" and VPG._int(hit.get("at")) == VPG._int(record["func_va"]):
                out.append({"key": name, "platform": platform, "from": current, "to": pattern,
                            "source": "record"})
    return out


# -- worker side: one long-lived process holds one build ----------------------

_STATE = {"build": None}


def _use_build(gamever, bindir):
    """Load a build's snapshot and binaries, dropping every cache the last one filled."""
    if _STATE["build"] == gamever:
        return _STATE
    for cache in (VPG._SNAPSHOT_INDEX, VPG._STUB_RANGES, VPG._PRIMARY_CACHE, VPG._MEMBERS,
                  VPG._FUNC_RANGES, VPG.GENERATOR_ALIASES):
        cache.clear()
    _STATE["build"] = None
    # The index is keyed by the platforms in force while it loads; a request's own
    # platform choice must not leave the cached index half-built.
    VPG.PLATFORMS = ("linux", "windows")
    index = VPG.load_snapshot_index(os.path.join(REPO_ROOT, "gamesymbols", f"{gamever}.yaml"))
    VPG._SNAPSHOT_INDEX.update(index)
    candidates = []
    for plugin, path in shipped_files(gamever):
        with open(path, "r", encoding="utf-8-sig") as handle:
            text = handle.read()
        shipped, note = VPG.load_gamedata_text(text)
        if not note:
            candidates.append((plugin, path, shipped, VPG.vtable_blocks_of(text)))
    _STATE.update(build=gamever, index=index, binaries=VPG.Binaries(os.path.join(REPO_ROOT, bindir), gamever),
                  config=os.path.join(REPO_ROOT, "configs", f"{gamever}.yaml"), shipped=candidates)
    return _STATE


def worker_init(warm_build, bindir):
    os.chdir(REPO_ROOT)
    if REPO_ROOT not in sys.path:
        sys.path.insert(0, REPO_ROOT)
    if warm_build:
        _use_build(warm_build, bindir)


def job_verify(gamever, bindir, text, filename, platforms):
    state = _use_build(gamever, bindir)
    VPG.PLATFORMS = platforms
    entries, note = VPG.load_gamedata_text(text)
    if len(entries) > MAX_ENTRIES:
        return {"error": f"more than {MAX_ENTRIES} entries"}
    match = match_shipped(entries, filename, [(p, path, s) for p, path, s, _ in state["shipped"]])
    plugin, path = (match[0], match[1]) if match else (None, None)
    results, note = VPG.verify_text(text, state["index"], state["binaries"], state["config"],
                                    plugin=plugin, output=path)
    if note:
        return {"build": gamever, "note": note, "results": []}
    unhealthy, tally, _, _ = VPG.summarize(results)
    shipped_vtables = next((v for p, sp, _, v in state["shipped"] if sp == path), {})
    fixes = suggest_fixes(results, entries, match[2] if match else None,
                          VPG.vtable_blocks_of(text), shipped_vtables)
    # A KeyValues file writes signatures as \x escapes; a spaced pattern placed into
    # one would read as a different value, so record signatures are only offered to
    # files that write patterns the way the records do.
    if "\\x" not in text:
        aliases = VPG.load_alias_map(state["config"]) if os.path.isfile(state["config"]) else {}
        fixes += record_signature_fixes(
            results, entries, fixes,
            lambda name, platform: VPG.resolve_record(state["index"], name, platform, aliases),
            lambda module, platform, pattern: VPG.check_signature(state["binaries"], module, platform, pattern))
    return {"build": gamever, "platforms": list(platforms),
            "matched": ({"plugin": plugin, "file": os.path.relpath(path, REPO_ROOT)} if match else None),
            "unhealthy": unhealthy, "verification": tally, "results": results, "fixes": fixes}


def job_check(gamever, bindir, module, platform, pattern):
    state = _use_build(gamever, bindir)
    return {"build": gamever, "module": module, "platform": platform,
            **VPG.check_signature(state["binaries"], module, platform, pattern)}


# -- request validation (front process) ---------------------------------------

def _build(body, builds):
    build = body.get("build") or (builds[0] if builds else None)
    if not build:
        raise BadRequest("no build has binaries on this server")
    if not isinstance(build, str) or not BUILD_RE.match(build):
        raise BadRequest("build must look like 14192")
    if build not in builds:
        raise BadRequest(f"build {build} cannot be scanned here; try one of {', '.join(builds[:5])}")
    return build


def parse_verify(body, builds):
    text = body.get("gamedata")
    if not isinstance(text, str) or not text.strip():
        raise BadRequest("gamedata must be the file's text")
    filename = body.get("filename") or ""
    if not isinstance(filename, str) or len(filename) > 200:
        raise BadRequest("filename must be a short string")
    wanted = body.get("platform") or "linux,windows"
    platforms = tuple(p for p in ("linux", "windows") if isinstance(wanted, str) and p in wanted.split(","))
    if not platforms:
        raise BadRequest("platform must be linux, windows or linux,windows")
    return _build(body, builds), text, os.path.basename(filename), platforms


def parse_check(body, builds):
    pattern = body.get("signature")
    if not isinstance(pattern, str) or not pattern.strip() or len(pattern) > MAX_PATTERN:
        raise BadRequest(f"signature must be 1-{MAX_PATTERN} characters")
    platform = body.get("platform")
    if platform not in ("linux", "windows"):
        raise BadRequest("platform must be linux or windows")
    module = VPG.LIBRARY_TO_MODULE.get(str(body.get("module") or "server"))
    if not module:
        raise BadRequest("unknown module")
    return _build(body, builds), module, platform, pattern.strip().strip("`")


# -- front process: HTTP, queue cap, result cache -----------------------------

class Service:
    def __init__(self, executor, bindir="bin", workers=4, queue=20, timeout=60, cache_size=256):
        self.executor, self.bindir, self.timeout = executor, bindir, timeout
        self.capacity = workers + queue
        self.inflight = 0
        self.lock = threading.Lock()
        self.cache, self.cache_size = OrderedDict(), cache_size

    def builds(self):
        return scannable_builds(REPO_ROOT, self.bindir)

    def run(self, cache_key, fn, *args):
        """-> (http status, payload). Identical requests are answered from the cache."""
        with self.lock:
            if cache_key in self.cache:
                self.cache.move_to_end(cache_key)
                return 200, {**self.cache[cache_key], "cached": True}
            if self.inflight >= self.capacity:
                return 429, {"error": "busy, try again shortly"}
            self.inflight += 1
        try:
            payload = self.executor.submit(fn, *args).result(timeout=self.timeout)
        except cf.TimeoutError:
            return 504, {"error": "the scan took too long"}
        except Exception:  # noqa: BLE001 - a crashed job is the service's fault, not the caller's
            traceback.print_exc()
            return 500, {"error": "internal error"}
        finally:
            with self.lock:
                self.inflight -= 1
        status = 400 if "error" in payload else 200
        if status == 200:
            with self.lock:
                self.cache[cache_key] = payload
                while len(self.cache) > self.cache_size:
                    self.cache.popitem(last=False)
        return status, payload

    def handle(self, method, path, body):
        path = path.split("?", 1)[0]
        if path.startswith("/api/"):
            path = path[4:]
        if method == "GET" and path == "/health":
            return 200, {"ok": True, "inflight": self.inflight, "capacity": self.capacity}
        if method == "GET" and path == "/builds":
            return 200, {"builds": self.builds()}
        if method != "POST" or path not in ("/verify", "/check"):
            return 404, {"error": "not found"}
        try:
            request = json.loads(body or b"{}")
        except ValueError:
            return 400, {"error": "body must be JSON"}
        if not isinstance(request, dict):
            return 400, {"error": "body must be a JSON object"}
        try:
            builds = self.builds()
            if path == "/verify":
                build, text, filename, platforms = parse_verify(request, builds)
                key = ("verify", build, platforms, filename, hashlib.sha256(text.encode()).hexdigest())
                return self.run(key, job_verify, build, self.bindir, text, filename, platforms)
            build, module, platform, pattern = parse_check(request, builds)
            return self.run(("check", build, module, platform, pattern), job_check,
                            build, self.bindir, module, platform, pattern)
        except BadRequest as error:
            return 400, {"error": str(error)}


def make_handler(service, max_body=MAX_BODY):
    class Handler(BaseHTTPRequestHandler):
        server_version = "cs2vibe-verify"

        def _send(self, status, payload):
            data = json.dumps(payload, separators=(",", ":")).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            if status == 429:
                self.send_header("Retry-After", "10")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            self._send(*service.handle("GET", self.path, None))

        def do_POST(self):
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = -1
            if length < 0 or length > max_body:
                self.close_connection = True
                return self._send(413, {"error": f"body must be at most {max_body} bytes"})
            self._send(*service.handle("POST", self.path, self.rfile.read(length)))

        def log_message(self, fmt, *args):
            # The real client address is nginx's X-Real-IP; the socket peer is always loopback.
            sys.stderr.write(f"{self.headers.get('X-Real-IP', '-') if self.headers else '-'} {fmt % args}\n")

    return Handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-host", default="127.0.0.1")
    parser.add_argument("-port", type=int, default=8787)
    parser.add_argument("-workers", type=int, default=4)
    parser.add_argument("-queue", type=int, default=20, help="requests waiting beyond the workers before 429")
    parser.add_argument("-timeout", type=int, default=60, help="seconds one request may take")
    parser.add_argument("-bindir", default="bin")
    args = parser.parse_args()

    builds = scannable_builds(REPO_ROOT, args.bindir)
    # spawn, not fork: the front process runs threads, and a forked child would inherit their locks.
    executor = cf.ProcessPoolExecutor(max_workers=args.workers, mp_context=multiprocessing.get_context("spawn"),
                                      initializer=worker_init, initargs=(builds[0] if builds else None, args.bindir))
    service = Service(executor, args.bindir, args.workers, args.queue, args.timeout)
    server = ThreadingHTTPServer((args.host, args.port), make_handler(service))
    server.daemon_threads = True
    print(f"verify_service on {args.host}:{args.port}, {args.workers} workers, builds: {', '.join(builds) or 'none'}",
          flush=True)
    try:
        server.serve_forever()
    finally:
        executor.shutdown(cancel_futures=True)


if __name__ == "__main__":
    sys.exit(main())
