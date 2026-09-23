#!/usr/bin/env python3
"""hunt_list.py - what is still missing for a gamever, and how hard each one will be.

A run produces most artifacts by relocating the previous gamever's pattern. This
tool does that relocation check up front, in seconds, without IDA: for every
artifact the previous gamever has and the new one lacks, it scans the baseline
pattern against the new binary and reports the hit count, the producing task and
the anchors that task has beyond relocation, who consumes the symbol, and the
baseline facts a human needs when hunting it by hand (VA, slot, offset). The
last column is the emit_artifact.py command to run once the address is known.

    uv run hunt_list.py -gamever 14182 -platform linux -module server
    uv run hunt_list.py -gamever 14182 -platform linux -module server -only risk      # hits != 1 only
    uv run hunt_list.py -gamever 14182 -platform linux -module server -only consumed  # shipped by an enabled generator
    uv run hunt_list.py ... -json out.json

Reading the columns:
  hits    1 = relocation will land, 0 = pattern dead, 2+ = twins; '-' = no pattern in the baseline
  anchors what the producing task can fall back on: str (string xref), inherit (base-class slot),
          vtrel (vtable relation), llm (needs an LLM key), sigbytes (old head bytes, dies with hits=0)
  consumer enabled generators whose shipped files name the key; empty = nothing pays for a hunt
"""
import argparse
import glob
import json
import os
import re
import sys

import yaml

REPO = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, REPO)
from auto_hunt_headless import load_binary, scan_sig  # noqa: E402

BINARY_NAMES = {
    ("server", "linux"): "libserver.so", ("server", "windows"): "server.dll",
    ("engine", "linux"): "libengine2.so", ("engine", "windows"): "engine2.dll",
    ("client", "linux"): "libclient.so", ("client", "windows"): "client.dll",
    ("networksystem", "linux"): "libnetworksystem.so", ("networksystem", "windows"): "networksystem.dll",
    ("matchmaking", "linux"): "libmatchmaking.so", ("matchmaking", "windows"): "matchmaking.dll",
    ("vphysics2", "linux"): "libvphysics2.so", ("vphysics2", "windows"): "vphysics2.dll",
    ("scenesystem", "linux"): "libscenesystem.so", ("scenesystem", "windows"): "scenesystem.dll",
    ("worldrenderer", "linux"): "libworldrenderer.so", ("worldrenderer", "windows"): "worldrenderer.dll",
}
SIG_FIELDS = ("func_sig", "vfunc_sig", "gv_sig", "offset_sig", "patch_sig")
ANCHOR_PATTERNS = (
    ("str", r'"xref_strings":\s*\[\s*"'),
    ("func", r'"xref_funcs":\s*\[\s*"'),
    ("gv", r'"xref_gvs":\s*\[\s*"'),
    ("sigbytes", r'"xref_signatures":\s*\[\s*"'),
    ("inherit", r"INHERIT_VFUNCS\s*=\s*\[\s*\("),
    ("vtrel", r"FUNC_VTABLE_RELATIONS\s*=\s*\[\s*\("),
    ("llm", r"LLM_DECOMPILE\s*=\s*\[\s*\{"),
)


def version_key(name):
    m = re.match(r"^(\d+)([a-z]*)$", name)
    return (int(m.group(1)), m.group(2)) if m else (0, name)


def previous_gamever(gamever, artifact_root):
    versions = [d for d in os.listdir(artifact_root) if os.path.isdir(os.path.join(artifact_root, d)) and version_key(d) < version_key(gamever)]
    return max(versions, key=version_key) if versions else None


def category_of(rec):
    if "patch_name" in rec:
        return "patch"
    if "gv_name" in rec:
        return "gv"
    if "struct_name" in rec:
        return "structmember"
    if "vtable_class" in rec and "func_va" not in rec:
        return "vtable"
    if "vfunc_index" in rec:
        return "vfunc"
    return "func"


def producing_tasks(config, module, platform):
    """artifact base name -> [(task name, anchors, platform key)]; tasks named after anchors, so search outputs."""
    out = {}
    for mod in config.get("modules", []):
        if mod["name"] != module:
            continue
        for task in mod.get("skills", []) or []:
            if task.get("platform") and task["platform"] != platform:
                continue
            outputs = (task.get("expected_output") or []) + (task.get("optional_output") or [])
            for output in outputs:
                name = output.replace("{platform}", platform)
                if not name.endswith(f".{platform}.yaml"):
                    continue
                out.setdefault(name[: -len(f".{platform}.yaml")], []).append(task["name"])
    return out


def task_anchors(task):
    path = os.path.join(REPO, "ida_preprocessor_scripts", f"{task}.py")
    if not os.path.exists(path):
        return "NO-PREPROC"
    text = open(path, encoding="utf-8").read()
    found = [label for label, rx in ANCHOR_PATTERNS if re.search(rx, text)]
    return ",".join(found) or "reloc"


def enabled_generator_texts():
    try:
        import publish_site_data
        disabled = set(publish_site_data.disabled_plugins())
    except Exception:
        disabled = set()
    texts = {}
    for plugin_dir in glob.glob(os.path.join(REPO, "gamedata-generators", "*", "")):
        plugin = os.path.basename(plugin_dir.rstrip("/"))
        if plugin in disabled:
            continue
        chunks = []
        for path in glob.glob(os.path.join(plugin_dir, "**", "*"), recursive=True):
            if os.path.isfile(path) and path.endswith((".json", ".jsonc", ".txt", ".yaml", ".py")):
                chunks.append(open(path, errors="ignore").read())
        texts[plugin] = "\n".join(chunks)
    return texts


def emit_hint(symbol, category, module, platform, gamever, rec):
    base = f"uv run emit_artifact.py -gamever {gamever} -module {module} -platform {platform} -symbol {symbol} -kind {category}"
    if category == "vfunc":
        return f"{base} -class {rec.get('vtable_name', '<Class>')} -index <slot>"
    if category == "structmember":
        return f"{base} -ea <insn> -struct {rec.get('struct_name')} -member {rec.get('member_name')} -size {rec.get('size', 4)}"
    if category == "patch":
        return f"{base} -ea <insn> -patch_bytes \"{rec.get('patch_bytes', '')}\""
    if category == "vtable":
        return "(vtable: produced by its own task once the class resolves via RTTI)"
    return f"{base} -ea <va>"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-gamever", required=True)
    ap.add_argument("-module", required=True)
    ap.add_argument("-platform", default="linux", choices=("linux", "windows"))
    ap.add_argument("-baseline", help="previous gamever (default: newest older one under bin_artifacts)")
    ap.add_argument("-bindir", default="bin")
    ap.add_argument("-artifactdir", default="bin_artifacts")
    ap.add_argument("-only", choices=("all", "risk", "consumed"), default="all")
    ap.add_argument("-json")
    args = ap.parse_args()

    artifact_root = os.path.join(REPO, args.artifactdir)
    baseline = args.baseline or previous_gamever(args.gamever, artifact_root)
    if not baseline:
        raise SystemExit("no baseline gamever found")
    binary = os.path.join(REPO, args.bindir, args.gamever, args.module, BINARY_NAMES[(args.module, args.platform)])
    if not os.path.isfile(binary):
        raise SystemExit(f"binary not found: {binary}")
    blob, info = load_binary(binary)
    config = yaml.safe_load(open(os.path.join(REPO, "configs", f"{args.gamever}.yaml"), encoding="utf-8"))
    tasks = producing_tasks(config, args.module, args.platform)
    symbol_aliases = {}
    for mod in config.get("modules", []):
        if mod["name"] == args.module:
            for sym in mod.get("symbols", []) or []:
                symbol_aliases[sym["name"]] = {sym["name"], *(sym.get("alias") or [])}
    texts = enabled_generator_texts()

    have = {os.path.basename(p) for p in glob.glob(os.path.join(artifact_root, args.gamever, args.module, f"*.{args.platform}.yaml"))}
    rows = []
    for path in sorted(glob.glob(os.path.join(artifact_root, baseline, args.module, f"*.{args.platform}.yaml"))):
        name = os.path.basename(path)
        if name in have:
            continue
        symbol = name[: -len(f".{args.platform}.yaml")]
        rec = yaml.safe_load(open(path, encoding="utf-8")) or {}
        category = category_of(rec)
        sig = next((str(rec[k]) for k in SIG_FIELDS if rec.get(k)), None)
        hits = len(scan_sig(blob, info, sig.replace("??", "?"))) if sig else None
        producers = tasks.get(symbol) or []
        anchors = ";".join(f"{t}[{task_anchors(t)}]" for t in producers) or "UNDECLARED"
        keys = symbol_aliases.get(symbol, {symbol})
        consumers = [p for p, t in texts.items() if any(re.search(r'"%s"' % re.escape(k), t) for k in keys)]
        ref = rec.get("func_va") or rec.get("gv_va") or rec.get("patch_va") or rec.get("vtable_va") or ""
        detail = []
        if rec.get("vfunc_index") is not None:
            detail.append(f"{rec.get('vtable_name', '?')}[{rec['vfunc_index']}]")
        if rec.get("offset") is not None:
            detail.append(f"offset={rec['offset']}")
        if rec.get("patch_bytes"):
            detail.append(f"patch={rec['patch_bytes']}")
        row = {
            "symbol": symbol, "category": category, "hits": hits, "baseline_va": ref, "baseline": " ".join(detail),
            "tasks": anchors, "consumers": consumers, "emit": emit_hint(symbol, category, args.module, args.platform, args.gamever, rec),
        }
        risk = hits != 1
        if args.only == "risk" and not risk:
            continue
        if args.only == "consumed" and not consumers:
            continue
        rows.append(row)

    if args.json:
        json.dump({"gamever": args.gamever, "baseline": baseline, "module": args.module, "platform": args.platform, "rows": rows}, open(args.json, "w"), indent=2)
    print(f"{args.module}/{args.platform}: {len(rows)} missing vs {baseline} (filter: {args.only})")
    for r in rows:
        hits = "-" if r["hits"] is None else str(r["hits"])
        print(f"  hits={hits:<2} {r['category']:12} {r['symbol']:58} {r['baseline_va']:12} {r['baseline']:34} {','.join(r['consumers']) or '-':28} {r['tasks']}")
    if rows:
        print("\nemit once the address is known, e.g.:")
        for r in rows[:3]:
            print("  " + r["emit"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
