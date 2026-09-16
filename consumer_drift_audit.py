#!/usr/bin/env python3
"""Consumer drift audit: does our generated gamedata point at the SAME functions as the
consumer projects' own upstream gamedata?

Why: `audit_duplicate_va.py` and sig uniqueness cannot catch a wrong *identification*
(right-looking, unique sig on the wrong function). But every consumer (CounterStrikeSharp,
CS2Fixes, cs2kz, cs2surf, modsharp, plugify, swiftlys2) maintains its own gamedata, hand-
verified by its authors. Resolving both their sig and ours on the same binary and comparing
the resulting addresses turns that into a free, deterministic cross-check. This is exactly
how the EmitSoundFilter / NetworkStateChanged / ProcessMovement / EndTouch misidentifications
were found (2026-09-16).

For every generator with ``templates/upstream.json`` the audit fetches the consumer's current
upstream file(s) (raw GitHub, cached under ``-cache``), parses both files into
``key -> {platform: sig | offset}``, resolves each sig on ``bin/<VER>/<module>/`` binaries
and classifies:

  SAME             same address on both sides
  WRAPPER          different address but one function directly calls/jumps to the other
                   (thunk vs body - harmless, both ABI-compatible by construction)
  UPSTREAM_STALE   upstream sig no longer matches this build (their problem, not ours)
  UPSTREAM_AMBIG   upstream sig matches several addresses
  OURS_MISSING     ours has no sig / no hit          <- our pipeline gap
  OURS_AMBIG       ours matches several addresses   <- broken sig
  DIFFERENT        both unique, different functions <- identity drift, investigate (IDA)
  OFFSET_DIFF      numeric offsets differ (informational: upstreams lag the build / other class)
  TEMPLATE_PASSTHROUGH  our sig is the unchanged template sig and no longer matches: the symbol
                   was never analyzed for this build (coverage gap, informational)
  BOTH_STALE       neither sig matches this build (informational)
  UPSTREAM_MISALIGNED  upstream sig starts a few bytes inside our function (informational)
  DISABLED         generator has MODULE_ENABLED = False; skipped unless -include-disabled

Exit code 1 when any DIFFERENT / OURS_MISSING / OURS_AMBIG is found (unless listed in
``ACCEPTED_DIFFERENCES``).

    uv run consumer_drift_audit.py                    # newest gamever, all generators
    uv run consumer_drift_audit.py -gamever 14181 -only CounterStrikeSharp,CS2Fixes -v
    uv run consumer_drift_audit.py -offline           # use templates/ (recorded upstream commit)
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import struct
import sys
import urllib.request

import abi_guard

GENERATORS_DIR = "gamedata-generators"
GAMEDATA_DIR = "gamedata"
DEFAULT_CACHE = os.path.join(".cache", "consumer_upstream")

# Known, reviewed differences that are NOT drift. (generator, key, platform) -> reason.
ACCEPTED_DIFFERENCES = {
    # cs2surf keeps two ProcessMovement-family keys; ours matches theirs. Nothing here yet.
}

PLATFORM_ALIASES = {
    "linux": "linux",
    "linuxsteamrt64": "linux",
    "windows": "windows",
    "win64": "windows",
}
MODULE_BINARY = {
    "linux": {
        "server": "libserver.so",
        "engine": "libengine2.so",
        "engine2": "libengine2.so",
        "tier0": "libtier0.so",
        "networksystem": "libnetworksystem.so",
        "matchmaking": "libmatchmaking.so",
        "vphysics2": "libvphysics2.so",
        "scenesystem": "libscenesystem.so",
    },
    "windows": {
        "server": "server.dll",
        "engine": "engine2.dll",
        "engine2": "engine2.dll",
        "tier0": "tier0.dll",
        "networksystem": "networksystem.dll",
        "matchmaking": "matchmaking.dll",
        "vphysics2": "vphysics2.dll",
        "scenesystem": "scenesystem.dll",
    },
}
MODULE_DIR = {"engine2": "engine"}
SIG_RE = re.compile(r"^(?:[0-9A-Fa-f]{2}|\?\??)(?:\s+(?:[0-9A-Fa-f]{2}|\?\??))+$")


# --- parsing --------------------------------------------------------------------------------


def strip_jsonc(text: str) -> str:
    """Remove // and /* */ comments outside strings (URLs like https:// inside strings survive),
    then trailing commas."""
    out = []
    i, n = 0, len(text)
    in_str = False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 1
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
            out.append(c)
        elif text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j < 0 else j
            continue
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        else:
            out.append(c)
        i += 1
    return re.sub(r",(\s*[}\]])", r"\1", "".join(out))


def _norm_sig(value: str) -> str | None:
    value = value.strip()
    if "\\x" in value:  # KeyValues style "\x40\x53\x2A"
        toks = re.findall(r"\\x([0-9A-Fa-f]{2})", value)
        return " ".join("?" if t.upper() == "2A" else t.upper() for t in toks) if toks else None
    if SIG_RE.match(value):
        return " ".join("?" if t.startswith("?") else t.upper() for t in value.split())
    return None


def parse_json_gamedata(text: str) -> dict:
    """Walk any JSON/JSONC gamedata; every dict holding platform keys becomes one entry."""
    data = json.loads(strip_jsonc(text), strict=False)
    out: dict = {}

    def visit(node, path):
        if isinstance(node, dict):
            plat_items = {PLATFORM_ALIASES[k]: v for k, v in node.items() if k in PLATFORM_ALIASES}
            if plat_items and path and not any(str(seg).lower() in ("patches", "patch") for seg in path[:-1]):
                key = path[-1]
                lib = node.get("library") or node.get("lib")
                entry = out.setdefault(key, {"library": lib, "sig": {}, "offset": {}})
                if lib and not entry.get("library"):
                    entry["library"] = lib
                for plat, v in plat_items.items():
                    if isinstance(v, str):
                        sig = _norm_sig(v)
                        if sig:
                            entry["sig"][plat] = sig
                    elif isinstance(v, (int, float)) and not isinstance(v, bool):
                        entry["offset"][plat] = int(v)
            for k, v in node.items():
                visit(v, path + [k])
        elif isinstance(node, list):
            for v in node:
                visit(v, path)

    visit(data, [])
    return out


def parse_keyvalues_gamedata(text: str) -> dict:
    """Minimal Valve KeyValues parser for *.games.txt (cs2kz)."""
    text = strip_jsonc(text)  # KeyValues files also carry // comments
    tokens = re.findall(r'"((?:[^"\\]|\\.)*)"|([{}])', text)
    stack: list = []
    root: dict = {}
    cur = root
    pending = None
    for quoted, brace in tokens:
        if brace == "{":
            new: dict = {}
            cur[pending if pending is not None else f"_anon{len(cur)}"] = new
            stack.append(cur)
            cur = new
            pending = None
        elif brace == "}":
            cur = stack.pop() if stack else root
        elif pending is None:
            pending = quoted
        else:
            cur[pending] = quoted
            pending = None
    out: dict = {}

    def visit(node, path):
        if not isinstance(node, dict):
            return
        plat_items = {PLATFORM_ALIASES[k]: v for k, v in node.items() if k in PLATFORM_ALIASES}
        if plat_items and path:
            entry = out.setdefault(path[-1], {"library": node.get("library"), "sig": {}, "offset": {}})
            for plat, v in plat_items.items():
                sig = _norm_sig(v)
                if sig:
                    entry["sig"][plat] = sig
                elif re.fullmatch(r"-?\d+", v.strip()):
                    entry["offset"][plat] = int(v)
        for k, v in node.items():
            visit(v, path + [k])

    visit(root, [])
    return out


def parse_gamedata_file(path: str) -> dict:
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()
    if path.endswith(".txt"):
        return parse_keyvalues_gamedata(text)
    return parse_json_gamedata(text)


# --- upstream fetch ------------------------------------------------------------------------


def fetch_upstream(repo_url: str, source_path: str, cache_dir: str, refresh: bool) -> str | None:
    repo = repo_url.rstrip("/").replace("https://github.com/", "")
    cache = os.path.join(cache_dir, repo.replace("/", "__"), source_path.replace("/", "__"))
    if os.path.exists(cache) and not refresh:
        return cache
    os.makedirs(os.path.dirname(cache), exist_ok=True)
    for branch in ("main", "master"):
        url = f"https://raw.githubusercontent.com/{repo}/{branch}/{source_path}"
        try:
            with urllib.request.urlopen(url, timeout=30) as resp:
                body = resp.read()
        except Exception:
            continue
        with open(cache, "wb") as f:
            f.write(body)
        return cache
    return None


# --- resolution ------------------------------------------------------------------------------


class Binaries:
    def __init__(self, bindir: str, gamever: str):
        self.bindir, self.gamever = bindir, gamever
        self._cache: dict = {}

    def get(self, platform: str, library: str | None):
        lib = (library or "server").lower()
        name = MODULE_BINARY[platform].get(lib)
        if not name:
            return None
        path = os.path.join(self.bindir, self.gamever, MODULE_DIR.get(lib, lib), name)
        if path not in self._cache:
            self._cache[path] = open(path, "rb").read() if os.path.exists(path) else None
        return self._cache[path]


def direct_targets(data: bytes, platform: str, off: int, span: int = 48) -> set[int]:
    """Addresses reached by `call rel32` / `jmp rel32` within the first `span` bytes."""
    out = set()
    for i in range(off, min(off + span, len(data) - 5)):
        if data[i] in (0xE8, 0xE9):
            rel = struct.unpack_from("<i", data, i + 1)[0]
            out.add(i + 5 + rel)
    return out


def classify_sig(ours: str | None, theirs: str | None, data: bytes, platform: str) -> tuple[str, str]:
    ho = abi_guard.sig_hits(ours, data) if ours else []
    ht = abi_guard.sig_hits(theirs, data) if theirs else []
    va = lambda off: f"{abi_guard.offset_to_va(data, platform, off) or off:#x}"  # noqa: E731
    if not ours or not ho:
        return "OURS_MISSING", f"ours={'none' if not ours else 'no hit'} theirs={[va(o) for o in ht[:3]]}"
    if len(ho) > 1:
        return "OURS_AMBIG", f"ours hits={len(ho)}"
    if not ht:
        return "UPSTREAM_STALE", f"ours={va(ho[0])}"
    if len(ht) > 1:
        return ("SAME", va(ho[0])) if ho[0] in ht else ("UPSTREAM_AMBIG", f"theirs hits={len(ht)} ours={va(ho[0])}")
    if ho[0] == ht[0]:
        return "SAME", va(ho[0])
    if 0 < ht[0] - ho[0] < 32:
        # Upstream's pattern starts a few bytes into the same function (mid-instruction sig).
        return "UPSTREAM_MISALIGNED", f"ours={va(ho[0])} theirs={va(ht[0])} (+{ht[0] - ho[0]})"
    if ht[0] in direct_targets(data, platform, ho[0]) or ho[0] in direct_targets(data, platform, ht[0]):
        return "WRAPPER", f"ours={va(ho[0])} theirs={va(ht[0])}"
    return "DIFFERENT", f"ours={va(ho[0])} theirs={va(ht[0])}"


def generator_enabled(gen_dir: str) -> bool:
    """Mirror gamedata_contract.discover_generator_modules: MODULE_ENABLED = False generators are not
    generated or shipped, so their leftover outputs must not be audited (read textually, no import)."""
    path = os.path.join(gen_dir, "gamedata.py")
    if not os.path.exists(path):
        return False
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        m = re.search(r"^MODULE_ENABLED\s*=\s*(True|False)", f.read(), re.M)
    return m is None or m.group(1) == "True"


def audit_generator(name: str, gen_dir: str, out_dir: str, bins: Binaries, cache: str, offline: bool, refresh: bool):
    meta_path = os.path.join(gen_dir, "templates", "upstream.json")
    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)
    rows = []
    for fl in meta.get("files", []):
        template_name = fl.get("template") or os.path.basename(fl["source_path"])
        ours_path = None
        for root, _dirs, files in os.walk(out_dir):  # os.walk sees hidden dirs such as .asset/
            if template_name in files:
                ours_path = os.path.join(root, template_name)
                break
        if not ours_path:
            rows.append((name, template_name, "-", "OURS_MISSING", "no generated file"))
            continue
        if offline:
            theirs_path = os.path.join(gen_dir, "templates", template_name)
        else:
            theirs_path = fetch_upstream(meta["repository"], fl["source_path"], cache, refresh)
        if not theirs_path or not os.path.exists(theirs_path):
            rows.append((name, template_name, "-", "UPSTREAM_STALE", "could not fetch upstream file"))
            continue
        ours, theirs = parse_gamedata_file(ours_path), parse_gamedata_file(theirs_path)
        template_path = os.path.join(gen_dir, "templates", template_name)
        template = parse_gamedata_file(template_path) if os.path.exists(template_path) else {}
        for key in sorted(k for k in set(ours) | set(theirs) if isinstance(k, str)):
            if key.endswith("Patch") or key.startswith("_anon"):
                continue  # byte patches are not function sigs; anonymous KV blocks carry no symbol
            o, t = ours.get(key, {"sig": {}, "offset": {}}), theirs.get(key, {"sig": {}, "offset": {}})
            tpl = template.get(key, {"sig": {}, "offset": {}})
            lib = o.get("library") or t.get("library")
            for platform in ("linux", "windows"):
                so, st = o["sig"].get(platform), t["sig"].get(platform)
                if so or st:
                    data = bins.get(platform, lib)
                    if data is None:
                        rows.append((name, key, platform, "SKIP", f"no binary for library {lib!r}"))
                        continue
                    if not st:
                        continue  # key not in upstream on this platform: nothing to compare
                    verdict, detail = classify_sig(so, st, data, platform)
                    if verdict in ("OURS_MISSING", "OURS_AMBIG") and so and so == tpl["sig"].get(platform):
                        # We never analyzed this symbol: the generator passed the (stale) template
                        # sig through unchanged. A coverage gap, not an identity error.
                        verdict = "TEMPLATE_PASSTHROUGH"
                    elif verdict == "OURS_MISSING" and so and not abi_guard.sig_hits(st, data):
                        verdict = "BOTH_STALE"
                    rows.append((name, key, platform, verdict, detail))
                oo, ot = o["offset"].get(platform), t["offset"].get(platform)
                if oo is not None and ot is not None and oo != ot:
                    # Informational: consumers' upstreams lag the current build (vtables shift by +1/+2)
                    # and some name a different class's slot. Verify with the RTTI walk, not here.
                    rows.append((name, key, platform, "OFFSET_DIFF", f"ours={oo} theirs={ot}"))
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("-gamever")
    ap.add_argument("-bindir", default="bin")
    ap.add_argument("-generators", default=GENERATORS_DIR)
    ap.add_argument("-gamedata", default=GAMEDATA_DIR)
    ap.add_argument("-only", help="comma-separated generator names")
    ap.add_argument("-cache", default=DEFAULT_CACHE)
    ap.add_argument("-offline", action="store_true", help="compare against templates/ instead of fetching upstream")
    ap.add_argument("-refresh", action="store_true", help="re-download upstream files")
    ap.add_argument("-v", "--verbose", action="store_true", help="also print SAME/WRAPPER/UPSTREAM_* rows")
    ap.add_argument("-include-disabled", action="store_true", help="also audit generators with MODULE_ENABLED = False")
    args = ap.parse_args(argv)

    gamever = args.gamever or abi_guard.newest_gamever(args.gamedata)
    if not gamever:
        print("consumer_drift_audit: no gamever", file=sys.stderr)
        return 2
    only = {x.strip() for x in args.only.split(",")} if args.only else None
    bins = Binaries(args.bindir, gamever)
    rows = []
    for meta in sorted(glob.glob(os.path.join(args.generators, "*", "templates", "upstream.json"))):
        gen_dir = os.path.dirname(os.path.dirname(meta))
        name = os.path.basename(gen_dir)
        if only and name not in only:
            continue
        if not args.include_disabled and not generator_enabled(gen_dir):
            rows.append((name, "-", "-", "DISABLED", "MODULE_ENABLED = False (not generated/shipped by this fork)"))
            continue
        out_dir = os.path.join(args.gamedata, gamever, name)
        if not os.path.isdir(out_dir):
            rows.append((name, "-", "-", "OURS_MISSING", f"no output dir {out_dir}"))
            continue
        rows.extend(audit_generator(name, gen_dir, out_dir, bins, args.cache, args.offline, args.refresh))

    bad_kinds = {"DIFFERENT", "OURS_MISSING", "OURS_AMBIG"}
    info_kinds = {"OFFSET_DIFF", "TEMPLATE_PASSTHROUGH", "BOTH_STALE", "UPSTREAM_MISALIGNED", "DISABLED"}
    counts: dict = {}
    failed = 0
    print(f"consumer_drift_audit: gamever {gamever}")
    for name, key, platform, verdict, detail in rows:
        counts[verdict] = counts.get(verdict, 0) + 1
        accepted = (name, key, platform) in ACCEPTED_DIFFERENCES
        if verdict in bad_kinds and not accepted:
            failed += 1
        if verdict in bad_kinds or verdict in info_kinds or args.verbose:
            flag = " (accepted)" if accepted else ""
            print(f"  {verdict:14s} {name:22s} {key:55s} {platform:7s} {detail}{flag}")
    print("  summary: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    if failed:
        print(
            f"consumer_drift_audit: {failed} finding(s) need review (IDA-verify, then fix the finder or add to ACCEPTED_DIFFERENCES)",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
