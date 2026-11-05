#!/usr/bin/env python3
"""Bring every stored user gamedata file (user_files.py) up to date for one build.

    uv run user_gamedata.py -gamever 14197            # what autopilot runs after publish
    uv run user_gamedata.py -gamever 14197 -dry-run   # report, write nothing
    uv run user_gamedata.py -gamever 14197 -no-ida    # skip the hunter stage

A value is only ever replaced with proof, cheapest first:

  1. known  - the key is one this repo ships or records: the value verify_service would
              offer (the matching shipped file's value, or the record's own pattern where
              it lands once on the record's address). The same rule as the site's fix.
  2. relocated - the key is unknown here, but its value worked on the file's previous
              build. A signature that landed on one function head where a record of ours
              sat takes that record's new signature (scanned unique, on its address). A
              bare vtable index on <Class>_<Method> / <Class>::<Method>: the slot held a
              record whose method has the same name, so the record's new slot (read from
              the class's primary vtable via RTTI) is the new index.
  3. hunted - the function is one no record names. The previous IDB gives its facts and
              the hunter (hunt_core, the pipeline's own evidence rule) finds it in the new
              build; the emitted signature must scan unique on the found address.

Everything else is left exactly as it was and reported as unresolved, per key and
platform, on the manage page, in manual_todo/<VER>/user-uploads.txt (key names and our
own values only - never a user's file) and in an optional Discord webhook message.
"""

import argparse
import collections
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

import gamedata_patch as GP
import user_files as UF
import verify_plugin_gamedata as VPG
import verify_service as VS

REPO = VS.REPO_ROOT
PLATFORMS = ("linux", "windows")


def bad(info):
    return info.get("status") in VS.BAD_STATUSES or info.get("verification") == "contradicted"


def split_key(name):
    """[(class, method)] candidates, longest class first: CCSPlayer_ItemServices_Foo is
    ambiguous until a vtable says which prefix is a class."""
    if "::" in name:
        cls, _, method = name.rpartition("::")
        return [(cls, method)]
    parts = name.split("_")
    return [("_".join(parts[:i]), "_".join(parts[i:])) for i in range(len(parts) - 1, 0, -1)]


def method_of(symbol):
    return symbol.replace("::", "_").rsplit("_", 1)[-1].lower() if symbol else ""


class Build:
    """One build's snapshot index (va -> symbols, name -> record) and binaries."""

    def __init__(self, gamever, bindir):
        self.gamever = gamever
        path = os.path.join(REPO, "gamesymbols", f"{gamever}.yaml")
        self.ok = os.path.isfile(path) and os.path.isdir(os.path.join(REPO, bindir, gamever))
        self.index = VPG.load_snapshot_index(path) if self.ok else {}
        self.binaries = VPG.Binaries(os.path.join(REPO, bindir), gamever)
        self.by_va = collections.defaultdict(list)
        for platforms in self.index.values():
            for platform, record in platforms.items():
                va = VPG._int(record.get("func_va")) if isinstance(record, dict) else None
                if va is not None:
                    self.by_va[(record.get("_module") or "server", platform, va)].append(record)

    def record(self, symbol, platform):
        return (self.index.get(VPG.fold(symbol)) or {}).get(platform)

    def slots(self, module, platform, class_name):
        blob, info, relocs = self.binaries.get(module, platform)
        if blob is None:
            return None
        tables = VPG.primary_vtables(blob, info, relocs, class_name)
        return tables[0][1] if len(tables) == 1 else None


def verified_signature(build, module, platform, record):
    """The record's func_sig when it scans unique on the record's address in `build`."""
    if not record or not record.get("func_sig") or record.get("func_va") is None:
        return None
    hit = VPG.check_signature(build.binaries, module, platform, record["func_sig"], record)
    if hit.get("status") == "ok" and VPG._int(hit.get("at")) == VPG._int(record["func_va"]):
        return str(record["func_sig"]).strip()
    return None


def new_slot(new, module, platform, class_name, record):
    """record's slot in class_name's primary vtable of the new build, read from the binary."""
    slots = new.slots(module, platform, class_name)
    va = VPG._int(record.get("func_va")) if record else None
    if not slots or va is None:
        return None
    hits = [i for i, slot in enumerate(slots) if slot == va]
    return hits[0] if len(hits) == 1 else None


def relocate_signature(prev, new, module, platform, value):
    """-> (new value, how) | (None, why) | ("HUNT", prev head va)."""
    hit = VPG.check_signature(prev.binaries, module, platform, value)
    if hit.get("status") == "no-binary":
        return None, f"build {prev.gamever} binaries are gone"
    if hit.get("status") != "ok":
        return None, f"did not land on one function head in {prev.gamever} either ({hit.get('status')})"
    head = VPG._int(hit["at"])
    for old in prev.by_va.get((module, platform, head), []):
        record = new.record(old["_symbol"], platform)
        sig = verified_signature(new, module, platform, record)
        if sig:
            return sig, f"landed on {old['_symbol']} in {prev.gamever}; its {new.gamever} signature"
    return "HUNT", head


def relocate_index(prev, new, module, platform, name, value):
    """A bare vtable index: -> (new index, how) | (None, why) | ("HUNT", (class, va))."""
    try:
        index = int(value)
    except (TypeError, ValueError):
        return None, "not a number"
    for class_name, method in split_key(name):
        slots = prev.slots(module, platform, class_name)
        if not slots:
            continue
        if not 0 <= index < len(slots) or slots[index] is None:
            return None, f"{class_name} has no slot {index} in {prev.gamever}"
        fn = slots[index]
        owners = prev.by_va.get((module, platform, fn), [])
        same = [o for o in owners if method_of(o["_symbol"]) == method.lower()]
        for old in same:
            record = new.record(old["_symbol"], platform)
            slot = new_slot(new, module, platform, class_name, record)
            if slot is not None:
                return slot, f"slot {index} of {class_name} held {old['_symbol']} in {prev.gamever}; slot {slot} now"
        if owners and not same:
            return None, (f"slot {index} of {class_name} held {owners[0]['_symbol']} in {prev.gamever}, "
                          f"which is not a {method}")
        return "HUNT", (class_name, fn)
    return None, "no class in the key name has a vtable"


def in_style_of(old, new):
    """new written with old's wildcard token: a file that writes "?" keeps "?"."""
    if not isinstance(old, str) or not isinstance(new, str):
        return new
    tokens = old.split()
    if "?" in tokens and "??" not in tokens:
        return " ".join("?" if t == "??" else t for t in new.split())
    if "??" in tokens and "?" not in tokens:
        return " ".join("??" if t == "?" else t for t in new.split())
    return new


def synthetic_name(module, platform, category, va, extra=""):
    digest = hashlib.sha1(f"{module}/{platform}/{category}/{va:x}/{extra}".encode()).hexdigest()[:12]
    return f"USER_{digest}"


def run_idat(ida, idb, binary, args, timeout):
    """idat on a throw-away copy of idb (the warm database is never touched)."""
    with tempfile.TemporaryDirectory(prefix="cs2_userhunt_") as scratch:
        copy = os.path.join(scratch, os.path.basename(idb))
        shutil.copyfile(idb, copy)
        os.symlink(os.path.realpath(binary), os.path.join(scratch, os.path.basename(binary)))
        log = os.path.join(scratch, "ida.log")
        script = os.path.join(REPO, "ida_user_hunt.py")
        command = [ida, "-A", f"-L{log}", f"-S{script} {' '.join(args)}", copy]
        env = dict(os.environ, TVHEADLESS="1")
        proc = subprocess.run(command, cwd=scratch, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, timeout=timeout, check=False)
        if proc.returncode != 0:
            tail = open(log, errors="replace").read()[-800:] if os.path.isfile(log) else proc.stdout[-800:]
            print(f"[user] idat exited {proc.returncode}: {tail}")


def hunt_stage(jobs, prev, new, bindir, ida_path, timeout, log=print):
    """jobs: {(module, platform): {symbol: job}} -> {symbol: (record, how)}."""
    import hunt_core
    from emit_artifact import BINARY_NAMES, find_ida
    try:
        ida = find_ida(ida_path)
    except SystemExit as error:
        log(f"[user] hunter stage skipped: {error}")
        return {}
    found = {}
    for (module, platform), wanted in sorted(jobs.items()):
        name = BINARY_NAMES.get((module, platform))
        prev_bin = os.path.join(REPO, bindir, prev.gamever, module, name or "-")
        new_bin = os.path.join(REPO, bindir, new.gamever, module, name or "-")
        facts_file = hunt_core.facts_path(REPO, prev.gamever, module, platform)
        if not all(os.path.isfile(p) for p in (f"{prev_bin}.i64", f"{new_bin}.i64", facts_file)):
            log(f"[user] {module}/{platform}: no warm IDB or baseline facts, {len(wanted)} left unresolved")
            continue
        with tempfile.TemporaryDirectory(prefix="cs2_userjobs_") as work:
            jobs_json = os.path.join(work, "jobs.json")
            with open(jobs_json, "w", encoding="utf-8") as handle:
                json.dump(list(wanted.values()), handle)
            synthetic_facts = os.path.join(work, "synthetic.json")
            run_idat(ida, f"{prev_bin}.i64", prev_bin,
                     ["facts", REPO, os.path.join(REPO, "bin_artifacts", prev.gamever, module), platform,
                      jobs_json, synthetic_facts], timeout)
            if not os.path.isfile(synthetic_facts):
                continue
            with open(facts_file, "r", encoding="utf-8") as handle:
                facts = json.load(handle)
            with open(synthetic_facts, "r", encoding="utf-8") as handle:
                facts["symbols"].update(json.load(handle))
            merged = os.path.join(work, "facts.json")
            with open(merged, "w", encoding="utf-8") as handle:
                json.dump(facts, handle)
            synthetic_dir = os.path.join(work, "baseline")
            os.makedirs(synthetic_dir)
            for symbol, job in wanted.items():
                data = {"func_name": symbol, "func_va": job["va"]}
                if job.get("func_sig"):
                    data["func_sig"] = job["func_sig"]
                if job["category"] == "vfunc":
                    data.update(vtable_name=job["vtable_name"], vfunc_index=job["vfunc_index"],
                                vfunc_offset=hex(8 * job["vfunc_index"]))
                with open(os.path.join(synthetic_dir, f"{symbol}.{platform}.yaml"), "w", encoding="utf-8") as h:
                    h.write(hunt_core.render_yaml(data))
            # the hunter reads the build's own artifacts as "already resolved" (one address,
            # one name); its output goes beside them in this scratch folder only
            out_dir = os.path.join(work, "out")
            os.makedirs(out_dir)
            artifacts = os.path.join(REPO, "bin_artifacts", new.gamever, module)
            for entry in os.listdir(artifacts) if os.path.isdir(artifacts) else ():
                if entry.endswith(f".{platform}.yaml"):
                    os.symlink(os.path.join(artifacts, entry), os.path.join(out_dir, entry))
            result = os.path.join(work, "result.json")
            run_idat(ida, f"{new_bin}.i64", new_bin,
                     ["hunt", REPO, new.gamever, module, platform, merged, synthetic_dir, out_dir, result], timeout)
            if not os.path.isfile(result):
                continue
            with open(result, "r", encoding="utf-8") as handle:
                report = json.load(handle)
            for symbol, row in report.get("solved", {}).items():
                found[symbol] = (row["record"], row["how"])
            log(f"[user] {module}/{platform}: hunter solved {len(report.get('solved', {}))} of {len(wanted)}")
    return found


def notify(webhook, filename, build, changes, unresolved, dry_run):
    if not webhook or dry_run or (not changes and not unresolved):
        return
    lines = [f"**{filename}** for CS2 build {build}: {len(changes)} value(s) updated"
             + (f", {len(unresolved)} could not be updated" if unresolved else "")]
    for row in unresolved[:10]:
        lines.append(f"- {row['key']} ({row['platform']}): {row['why']}")
    payload = json.dumps({"content": "\n".join(lines)[:1900], "allowed_mentions": {"parse": []}}).encode()
    request = urllib.request.Request(webhook, data=payload, method="POST",
                                     headers={"Content-Type": "application/json",
                                              "User-Agent": "cs2vibe-user-gamedata/1.0"})
    try:
        urllib.request.urlopen(request, timeout=15).close()
    except Exception as error:  # noqa: BLE001 - a dead webhook never fails the run
        print(f"[user] webhook not delivered: {type(error).__name__}")


def plan_file(file_id, text, meta, new, prev_builds, bindir, platforms=PLATFORMS):
    """Stages 1 and 2 for one file. -> (text, changes, unresolved, hunt jobs, demand keys)."""
    filename = meta.get("filename") or UF.DEFAULT_FILENAME
    verdict = VS.job_verify(new.gamever, bindir, text, filename, platforms)
    if verdict.get("error") or verdict.get("note"):
        return text, [], [{"key": "*", "platform": "*", "why": verdict.get("error") or verdict.get("note")}], {}, set()
    fixes = verdict.get("fixes") or []
    text, _applied, skipped = GP.apply_fixes(text, fixes)
    placed = {(f["key"], f["platform"]) for f in fixes} - {(s["key"], s["platform"]) for s in skipped}
    changes = [{"key": f["key"], "platform": f["platform"], "from": f["from"], "to": f["to"],
                "how": f"known value ({f.get('source')})"} for f in fixes if (f["key"], f["platform"]) in placed]
    unresolved = [{"key": s["key"], "platform": s["platform"], "why": f"value could not be placed ({s['reason']})"}
                  for s in skipped]
    entries, _ = VPG.load_gamedata_text(text)
    prev = prev_builds.get(meta.get("baseline_build"))
    jobs, demand = {}, set()
    for row in verdict["results"]:
        name, kind, module = row["name"], row.get("kind"), row.get("module", "server")
        for platform, info in row["platforms"].items():
            if (name, platform) in placed or info.get("status") == "not-shipped":
                continue
            value = ((entries.get(name) or {}).get("values") or {}).get(platform)
            if info.get("unrecorded"):
                demand.add(name)
            wants_signature = kind == "signature" and bad(info)
            # an index this repo has no record of cannot be judged in the new build alone:
            # it is re-derived from the old one whenever the file moved builds
            wants_index = kind == "offset" and info.get("unrecorded") and prev is not None and prev.gamever != new.gamever
            if not (wants_signature or wants_index):
                if kind == "offset" and bad(info):
                    unresolved.append({"key": name, "platform": platform, "why": f"{info.get('status')}, no known value"})
                continue
            if prev is None or not prev.ok or prev.gamever == new.gamever:
                unresolved.append({"key": name, "platform": platform,
                                   "why": f"{info.get('status')}; the build it was written for is not on this server"})
                continue
            if wants_signature:
                outcome, how = relocate_signature(prev, new, module, platform, value)
                category, extra = "func", {}
            else:
                outcome, how = relocate_index(prev, new, module, platform, name, value)
                category, extra = "vfunc", {}
            if outcome == "HUNT":
                if category == "func":
                    va = how
                    symbol = synthetic_name(module, platform, "func", va)
                    job = {"symbol": symbol, "category": "func", "va": hex(va), "func_sig": str(value)}
                else:
                    class_name, va = how
                    symbol = synthetic_name(module, platform, "vfunc", va, class_name)
                    job = {"symbol": symbol, "category": "vfunc", "va": hex(va), "vtable_name": class_name,
                           "vfunc_index": int(value)}
                    extra = {"class": class_name}
                jobs.setdefault((module, platform), {})[symbol] = job
                unresolved.append({"key": name, "platform": platform, "why": "HUNT", "symbol": symbol,
                                   "from": value, "category": category, "module": module, **extra})
            elif outcome is None:
                unresolved.append({"key": name, "platform": platform, "why": how})
            elif str(outcome) != str(value):
                to = str(outcome) if isinstance(value, str) and category == "vfunc" else in_style_of(value, outcome)
                text, applied, skip = GP.apply_fixes(text, [{"key": name, "platform": platform, "from": value, "to": to}])
                if applied:
                    changes.append({"key": name, "platform": platform, "from": value, "to": to, "how": how})
                else:
                    unresolved.append({"key": name, "platform": platform,
                                       "why": f"found ({how}) but could not be placed ({skip[0]['reason']})"})
    return text, changes, unresolved, jobs, demand


def finish_hunted(text, changes, unresolved, found, new, hunted=True):
    """Place what the hunter proved; the rest of the HUNT rows get their final reason."""
    still = []
    for row in unresolved:
        if row.get("why") != "HUNT":
            still.append(row)
            continue
        hit = found.get(row["symbol"])
        record, how = hit if hit else (None, None)
        to = None
        if record and row["category"] == "func":
            record = dict(record, _module=row["module"])
            to = in_style_of(row["from"], verified_signature(new, row["module"], row["platform"], record))
        elif record and record.get("vfunc_index") is not None:
            # the emitted slot must hold the emitted function in the class's primary vtable,
            # the one table CounterStrikeSharp reads
            slots = new.slots(row["module"], row["platform"], row["class"])
            index = int(record["vfunc_index"])
            if slots and index < len(slots) and slots[index] == VPG._int(record.get("func_va")):
                to = str(index) if isinstance(row["from"], str) else index
        if to is None:
            why = ("not a function this repo knows, and the hunter found no proof where it went; left as it was"
                   if hunted else "not a function this repo knows; the hunter stage did not run, left as it was")
            still.append({"key": row["key"], "platform": row["platform"], "why": why})
            continue
        if str(to) == str(row["from"]):
            continue
        text, applied, skip = GP.apply_fixes(text, [{"key": row["key"], "platform": row["platform"],
                                                     "from": row["from"], "to": to}])
        if applied:
            changes.append({"key": row["key"], "platform": row["platform"], "from": row["from"], "to": to,
                            "how": f"hunted: {how}"[:300], "proposal": True})
        else:
            still.append({"key": row["key"], "platform": row["platform"],
                          "why": f"hunted but could not be placed ({skip[0]['reason']})"})
    return text, changes, still


def write_report(gamever, rows, demand, dry_run):
    """manual_todo/<VER>/user-uploads.txt: key names and our values, never a user's file."""
    lines = [f"# user-uploaded gamedata, build {gamever} ({time.strftime('%Y-%m-%d %H:%M')})",
             "# unresolved: key, platform, why, how many stored files carry it", ""]
    counted = collections.Counter((r["key"], r["platform"], r["why"]) for r in rows["unresolved"])
    for (key, platform, why), n in sorted(counted.items()):
        lines.append(f"unresolved {key} {platform} x{n}: {why}")
    lines += ["", "# proposals: keys the hunter found with proof that no record of ours names",
              "# (candidates for FORK_OWNED_SYMBOLS - decide the name first, rule 19)"]
    for (key, platform), how in sorted(rows["proposals"].items()):
        lines.append(f"proposal {key} {platform}: {how}")
    lines += ["", "# demand: keys with no record here, by how many stored files carry them"]
    for key, n in demand.most_common():
        lines.append(f"demand {key} x{n}")
    out = os.path.join(REPO, "manual_todo", gamever, "user-uploads.txt")
    if not dry_run:
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
    print(f"[user] report: {out} ({len(counted)} unresolved, {len(rows['proposals'])} proposals, "
          f"{len(demand)} demanded keys)")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-gamever", required=True)
    parser.add_argument("-root", default=UF.ROOT)
    parser.add_argument("-bindir", default="bin")
    parser.add_argument("-only", help="one stored file id")
    parser.add_argument("-dry-run", dest="dry_run", action="store_true")
    parser.add_argument("-no-ida", dest="no_ida", action="store_true")
    parser.add_argument("-ida")
    parser.add_argument("-timeout", type=int, default=1800)
    parser.add_argument("-force", action="store_true", help="redo files already updated for this build")
    args = parser.parse_args(argv)

    os.chdir(REPO)
    if not args.dry_run:
        for gone in UF.expire(args.root):
            print(f"[user] expired {gone[:6]}...")
    ids = [args.only] if args.only else UF.list_ids(args.root)
    new = Build(args.gamever, args.bindir)
    if not new.ok:
        print(f"[user] build {args.gamever} has no snapshot or binaries")
        return 1
    prev_builds = {}
    plans = {}
    for file_id in ids:
        try:
            meta = UF.load_meta(file_id, args.root)
            text = UF.current_text(file_id, args.root)
        except (UF.StoreError, OSError, ValueError) as error:
            print(f"[user] {file_id[:6]}...: {error}")
            continue
        done = any(h.get("build") == args.gamever and h.get("event") == "update" for h in meta.get("history") or [])
        if done and not args.force:
            continue
        baseline = meta.get("baseline_build")
        if baseline and baseline not in prev_builds:
            prev_builds[baseline] = Build(baseline, args.bindir) if baseline != args.gamever else new
        plans[file_id] = (meta, *plan_file(file_id, text, meta, new, prev_builds, args.bindir))

    by_prev = collections.defaultdict(lambda: collections.defaultdict(dict))
    for file_id, (meta, _t, _c, _u, file_jobs, _d) in plans.items():
        for key, wanted in file_jobs.items():
            by_prev[meta.get("baseline_build")][key].update(wanted)
    found = {}
    if not args.no_ida:
        for baseline, wanted in by_prev.items():
            found.update(hunt_stage(wanted, prev_builds[baseline], new, args.bindir, args.ida, args.timeout))

    rows = {"unresolved": [], "proposals": {}}
    demand = collections.Counter()
    for file_id, (meta, text, changes, unresolved, _jobs, wanted) in plans.items():
        text, changes, unresolved = finish_hunted(text, changes, unresolved, found, new, not args.no_ida)
        demand.update(wanted)
        rows["unresolved"] += unresolved
        for change in changes:
            if change.get("proposal"):
                rows["proposals"][(change["key"], change["platform"])] = change["how"]
        print(f"[user] {file_id[:6]}... {meta.get('filename')}: {len(changes)} updated, {len(unresolved)} unresolved")
        if not args.dry_run:
            UF.record_update(file_id, args.gamever, text, changes, unresolved, root=args.root)
            notify(meta.get("webhook"), meta.get("filename"), args.gamever, changes, unresolved, args.dry_run)
    write_report(args.gamever, rows, demand, args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
