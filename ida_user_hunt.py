"""ida_user_hunt.py - the IDA half of user_gamedata.py's last stage, run headless by idat.

A stored user file can name a function this repo never analysed: its signature still
lands on one function head in the build it was written for, and no record of ours sits
there. That is exactly the hunter's question ("this function moved - where is it now?"),
so the answer comes from the same hunter and the same evidence rule as the pipeline's
own symbols, under synthetic names (USER_<hash>) that never reach any artifact tree.

    facts mode, on a COPY of the previous build's IDB:
      idat -A -S"ida_user_hunt.py facts <repo> <prev_artifact_dir> <platform> <jobs.json> <out.json>" x.i64
    hunt mode, on a COPY of the new build's IDB:
      idat -A -S"ida_user_hunt.py hunt <repo> <gamever> <module> <platform> <facts.json> <synthetic_dir> <out_dir> <out.json>" x.i64

jobs.json: [{"symbol", "category": "func"|"vfunc", "va", "vtable_name"?, "vfunc_index"?}]
"""
import json
import os
import sys

import ida_auto
import idc


def facts_mode(repo, artifact_dir, platform, jobs_path, out_path):
    import hunt_core
    import ida_backend
    backend = ida_backend.IdaBackend()
    fb = hunt_core.FactsBuilder(backend)
    va_to_symbol = {}
    for name in sorted(os.listdir(artifact_dir)):
        if name.endswith(f".{platform}.yaml"):
            rec = hunt_core.parse_yaml(os.path.join(artifact_dir, name))
            va = hunt_core.to_int(rec.get("func_va"))
            if va is not None and hunt_core.category_of(rec) in ("func", "vfunc"):
                va_to_symbol.setdefault(va, name[: -len(f".{platform}.yaml")])
    with open(jobs_path, "r", encoding="utf-8") as handle:
        jobs = json.load(handle)
    data_regions = backend.data_regions()
    out = {}
    for job in jobs:
        entry = {"category": job["category"]}
        try:
            entry.update(fb.function_facts(int(job["va"], 16), va_to_symbol))
            start = hunt_core.to_int(entry.get("va"))
            if start is not None:
                entry["data_holders"] = fb.data_holders(start, va_to_symbol, data_regions)
                entry["call_chains"] = fb.call_chains(start, va_to_symbol)
            if job["category"] == "vfunc":
                entry["vtable_name"] = job.get("vtable_name")
                entry["vfunc_index"] = job.get("vfunc_index")
        except Exception as error:  # one bad job must not lose the others
            entry["error"] = str(error)
        out[job["symbol"]] = entry
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(out, handle)
    print(f"[user-hunt] facts for {len(out)} -> {out_path}")


def hunt_mode(repo, gamever, module, platform, facts_path, synthetic_dir, out_dir, out_path):
    import hunt_core
    import ida_backend
    with open(facts_path, "r", encoding="utf-8") as handle:
        facts = json.load(handle)
    symbols = sorted(s for s in facts["symbols"] if s.startswith("USER_"))
    lines = []
    backend = ida_backend.IdaBackend()
    hunter = hunt_core.Hunter(backend, gamever, module, platform, facts, out_dir, log=lines.append)
    report = hunter.run(symbols, baseline_artifact_dir=synthetic_dir)
    solved = {}
    for row in report["solved"]:
        path = row.get("output")
        if isinstance(path, str) and os.path.isfile(path):
            solved[row["symbol"]] = {"how": row["how"], "record": hunt_core.parse_yaml(path)}
    unresolved = {row["symbol"]: row.get("why") for row in report["unresolved"] + report["changed"]}
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump({"solved": solved, "unresolved": unresolved, "log": lines[-200:]}, handle)
    print(f"[user-hunt] solved {len(solved)} of {len(symbols)} -> {out_path}")


def main():
    mode, repo = idc.ARGV[1], idc.ARGV[2]
    sys.path.insert(0, repo)
    ida_auto.auto_wait()
    if mode == "facts":
        facts_mode(repo, *idc.ARGV[3:7])
    elif mode == "hunt":
        hunt_mode(repo, *idc.ARGV[3:10])
    else:
        raise SystemExit(f"unknown mode {mode}")


if __name__ == "__main__":
    try:
        main()
    finally:
        idc.qexit(0)
