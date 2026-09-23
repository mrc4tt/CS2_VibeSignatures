"""ida_baseline_facts.py - IDA runner for hunt_core.extract_facts on a BASELINE IDB.

Run headless by baseline_facts.py over a copy of the baseline database:

    idat -A -S"ida_baseline_facts.py <repo> <artifact_dir> <platform> <out.json>" <baseline>.i64

The facts format is tool-neutral (hunt_core.py); ghidra_hunt.py writes the same
JSON from Ghidra. Kept as a script so the plugin loader and idat both find it.
"""
import json
import os
import sys

import ida_auto
import idc


def main():
    repo, artifact_dir, platform, out_path = idc.ARGV[1:5]
    sys.path.insert(0, repo)
    import hunt_core
    import ida_backend
    ida_auto.auto_wait()
    backend = ida_backend.IdaBackend()
    facts = hunt_core.extract_facts(
        backend, artifact_dir, platform,
        gamever=os.path.basename(os.path.dirname(artifact_dir)),
        module=os.path.basename(artifact_dir),
    )
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(facts, handle)
    print(f"[facts] -> {out_path}")


if __name__ == "__main__":
    try:
        main()
    finally:
        idc.qexit(0)
