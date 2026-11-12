#!/usr/bin/env python3
"""Convars, commands, interfaces, logging channels and networked classes of a build.

DumpSource2 (tools/build_dumpsource2.sh) loads the game's Linux modules offline and writes
what GameTracking-CS2 publishes under DumpSource2/. This runs it on a build's own binaries,
keeps the text files under source2dumps/<VER>/ and says what changed since the previous
build, so the notification lists the convars Valve renamed or removed instead of a guess
from the binaries' strings.

    source2_dump.py run  -gamever <VER> [-prev <VER>]   download, dump, store, diff
    source2_dump.py diff -old <VER> -new <VER>          diff two stored dumps

Only depot 2347773 (the Linux binaries, ~1.4 GB) is downloaded, at the manifest
download.yaml pins for the build, into source2_depot/ (gitignored, kept between builds so
DepotDownloader only fetches what changed). The dump needs no VPK or gameinfo.

Exit: 0 fine, 1 the dump or the download failed, 2 usage. The last line is the summary.
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent
DUMP_DIR = REPO / "source2dumps"
DEPOT_DIR = REPO / "source2_depot"
LINUX_DEPOT = "2347773"
# The files kept per build. schemas/ and schemas.json are left out: schema_dump.py already
# tracks the schema, and schemas.json alone is 7 MB a build.
KEEP = ["convars.txt", "commands.txt", "interfaces.txt", "logging_channels.txt",
        "network/client.txt", "network/server.txt"]
FILELIST = [r"regex:^game/bin/linuxsteamrt64/", r"regex:^game/csgo/bin/linuxsteamrt64/"]
DETAIL_LIMIT = 40


def tool_path():
    return Path(os.environ.get("DUMPSOURCE2_BIN")
                or Path(os.environ.get("DUMPSOURCE2_DIR", Path.home() / "tools/DumpSource2")) / "build/DumpSource2-CS2")


def manifest_for(ver):
    data = yaml.safe_load((REPO / "download.yaml").read_text(encoding="utf-8")) or {}
    for entry in data.get("downloads") or []:
        if str(entry.get("tag")) == str(ver):
            manifest = (entry.get("manifests") or {}).get(LINUX_DEPOT)
            if manifest:
                return str(manifest), entry.get("branch")
    raise SystemExit(f"download.yaml has no depot {LINUX_DEPOT} manifest for {ver}")


def download(ver):
    from download_depot import download_manifests

    manifest, branch = manifest_for(ver)
    DEPOT_DIR.mkdir(exist_ok=True)
    username = os.getenv("DEPOTDOWNLOADER_STEAM_USERNAME")
    password = os.getenv("DEPOTDOWNLOADER_STEAM_PASSWORD")
    # -remember-password reuses the stored login token, as download_depot.py does; without
    # it Steam refuses the fresh login ("Unable to get steam3 credentials") and a historical
    # manifest, which anonymous gets a 401 for, cannot be fetched.
    download_manifests({LINUX_DEPOT: manifest}, "730", "linux", str(DEPOT_DIR), FILELIST, branch=branch,
                       username=username, password=password, remember_password=bool(username and password))


def dump(ver):
    tool = tool_path()
    if not tool.is_file():
        raise SystemExit(f"{tool} not found: build it with tools/build_dumpsource2.sh")
    game = DEPOT_DIR / "game"
    bins = game / "bin/linuxsteamrt64"
    libpath = f"{bins}:{game / 'csgo/bin/linuxsteamrt64'}"
    with tempfile.TemporaryDirectory() as out:
        env = dict(os.environ, LD_LIBRARY_PATH=libpath)
        proc = subprocess.run([str(tool), out], cwd=bins, env=env, capture_output=True, text=True,
                              errors="replace", timeout=1800)
        log = proc.stdout + proc.stderr
        problems = [line for line in log.splitlines() if "[critical]" in line or "[error]" in line]
        if proc.returncode != 0:
            print("\n".join(problems[-10:]) or log[-2000:], file=sys.stderr)
            raise SystemExit(f"DumpSource2 exited with {proc.returncode}")
        target = DUMP_DIR / str(ver)
        if target.exists():
            shutil.rmtree(target)
        for name in KEEP:
            src = Path(out) / name
            if not src.is_file():
                raise SystemExit(f"DumpSource2 wrote no {name}")
            dst = target / name
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
    return target


# --- parsing and diffing ---------------------------------------------------------------

HEADER = re.compile(r"^(?P<name>\S+)(?: (?P<default>.*?))? \((?P<attrs>[^()]*)\)$")


def parse_entries(text):
    """{name: {"default", "min", "max", "flags", "help"}} from convars.txt or commands.txt."""
    entries = {}
    current = None
    for line in text.splitlines():
        if not line.strip():
            current = None
            continue
        if line.startswith("\t"):
            if current is not None:
                current["help"].append(line[1:])
            continue
        m = HEADER.match(line)
        if not m:
            current = None
            continue
        attrs = m.group("attrs")
        entry = {"default": m.group("default"), "min": None, "max": None, "flags": [], "help": []}
        for part in [p.strip() for p in attrs.split(",")]:
            if part.startswith("min: "):
                entry["min"] = part[5:]
            elif part.startswith("max: "):
                entry["max"] = part[5:]
            else:
                entry["flags"] = part.split()
        entries[m.group("name")] = entry
        current = entry
    return entries


def describe(entry):
    bits = []
    if entry["default"] is not None:
        bits.append(entry["default"])
    rng = ", ".join(f"{k}: {entry[k]}" for k in ("min", "max") if entry[k] is not None)
    if rng:
        bits.append(f"({rng})")
    help_line = next((h for h in entry["help"] if h and h != "<no description>"), "")
    if help_line:
        bits.append(f"- {help_line[:120]}")
    return " ".join(bits)


def diff_entries(old, new):
    added = sorted(set(new) - set(old), key=str.lower)
    removed = sorted(set(old) - set(new), key=str.lower)
    changed = []
    for name in sorted(set(old) & set(new), key=str.lower):
        a, b = old[name], new[name]
        what = []
        if a["default"] != b["default"]:
            what.append(f"default {a['default']} -> {b['default']}")
        for k in ("min", "max"):
            if a[k] != b[k]:
                what.append(f"{k} {a[k]} -> {b[k]}")
        if a["flags"] != b["flags"]:
            plus = [f for f in b["flags"] if f not in a["flags"]]
            minus = [f for f in a["flags"] if f not in b["flags"]]
            what.append("flags " + " ".join([f"+{f}" for f in plus] + [f"-{f}" for f in minus]))
        if a["help"] != b["help"]:
            what.append("help text")
        if what:
            changed.append((name, what))
    return added, removed, changed


# Renamed: a removed and an added entry with the same default, range and help text.
def pair_renames(old, new, added, removed):
    pairs = []
    left = list(added)
    for r in removed:
        key = (old[r]["default"], old[r]["min"], old[r]["max"], tuple(old[r]["help"]))
        if not any(h and h != "<no description>" for h in old[r]["help"]):
            continue
        for a in left:
            if (new[a]["default"], new[a]["min"], new[a]["max"], tuple(new[a]["help"])) == key:
                pairs.append((r, a))
                left.remove(a)
                break
    return pairs


def section_lines(kind, old, new):
    added, removed, changed = diff_entries(old, new)
    renames = pair_renames(old, new, added, removed)
    renamed_old = {r for r, _ in renames}
    renamed_new = {a for _, a in renames}
    added = [a for a in added if a not in renamed_new]
    removed = [r for r in removed if r not in renamed_old]
    lines = []
    for r, a in renames[:DETAIL_LIMIT]:
        lines.append(f"  ~ {r} -> {a} (renamed, same default and help)")
    for a in added[:DETAIL_LIMIT]:
        lines.append(f"  + {a} {describe(new[a])}".rstrip())
    for r in removed[:DETAIL_LIMIT]:
        lines.append(f"  - {r}")
    for name, what in changed[:DETAIL_LIMIT]:
        lines.append(f"  ! {name}: {'; '.join(what)}")
    hidden = max(0, len(renames) - DETAIL_LIMIT) + max(0, len(added) - DETAIL_LIMIT) \
        + max(0, len(removed) - DETAIL_LIMIT) + max(0, len(changed) - DETAIL_LIMIT)
    if hidden:
        lines.append(f"  ... {hidden} more")
    counts = f"+{len(added)} -{len(removed)} ~{len(renames)} !{len(changed)}"
    return counts, lines


def network_counts(old_text, new_text):
    def classes(text):
        out, current = {}, None
        for line in text.splitlines():
            if not line.strip():
                current = None
            elif not line.startswith("\t"):
                current = line.strip()
                out[current] = []
            elif current is not None:
                out[current].append(line.strip())
        return out
    a, b = classes(old_text), classes(new_text)
    fields_changed = sum(1 for c in set(a) & set(b) if a[c] != b[c])
    return len(set(b) - set(a)), len(set(a) - set(b)), fields_changed


def report(old_ver, new_ver):
    old_dir, new_dir = DUMP_DIR / str(old_ver), DUMP_DIR / str(new_ver)
    if not old_dir.is_dir():
        return f"source2 dump {new_ver}: no dump of {old_ver} to compare with", []
    lines = []
    parts = []
    for kind in ("convars", "commands"):
        old = parse_entries((old_dir / f"{kind}.txt").read_text(encoding="utf-8", errors="replace"))
        new = parse_entries((new_dir / f"{kind}.txt").read_text(encoding="utf-8", errors="replace"))
        counts, detail = section_lines(kind, old, new)
        parts.append(f"{kind} {counts}")
        if detail:
            lines.append(f"[{kind}] {old_ver} -> {new_ver}")
            lines.extend(detail)
    for side in ("server", "client"):
        rel = f"network/{side}.txt"
        if (old_dir / rel).is_file() and (new_dir / rel).is_file():
            added, removed, changed = network_counts((old_dir / rel).read_text(errors="replace"),
                                                     (new_dir / rel).read_text(errors="replace"))
            if added or removed or changed:
                parts.append(f"network/{side} +{added} -{removed} classes, {changed} changed")
    summary = f"source2 {old_ver} -> {new_ver}: " + ", ".join(parts) \
        + " (+added -removed ~renamed !changed)"
    return summary, lines


def previous_dump(ver):
    def key(v):
        m = re.match(r"^(\d+)([a-z]?)$", v)
        return (int(m.group(1)), m.group(2)) if m else (0, v)
    older = [p.name for p in DUMP_DIR.iterdir() if p.is_dir() and key(p.name) < key(str(ver))] \
        if DUMP_DIR.is_dir() else []
    return max(older, key=key) if older else None


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run")
    run.add_argument("-gamever", required=True)
    run.add_argument("-prev", help="build to compare with (default: the newest older dump)")
    run.add_argument("-no-download", action="store_true", help="use source2_depot/ as it is")
    d = sub.add_parser("diff")
    d.add_argument("-old", required=True)
    d.add_argument("-new", required=True)
    args = ap.parse_args()

    if args.cmd == "run":
        if not args.no_download:
            try:
                download(args.gamever)
            except subprocess.CalledProcessError as exc:
                # never str(exc): its command line carries the Steam password
                raise SystemExit(f"download failed: DepotDownloader exited with {exc.returncode}")
        target = dump(args.gamever)
        print(f"stored {', '.join(KEEP)} in {target.relative_to(REPO)}")
        prev = args.prev or previous_dump(args.gamever)
        if not prev:
            print(f"source2 dump {args.gamever}: first dump, nothing to compare with")
            return 0
        summary, lines = report(prev, args.gamever)
    else:
        summary, lines = report(args.old, args.new)
    for line in lines:
        print(line)
    print(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
