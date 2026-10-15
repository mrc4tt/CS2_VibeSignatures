#!/usr/bin/env python3
"""
Repair the artifacts audit_artifact_contract.py rejects, by re-running what produced them.

The contract audit is right to stop a build whose artifact names the wrong class or has
dropped a field it must carry (rule 18: fix it by re-running the task, never by editing).
Before this, autopilot only told a person to do that, and its retry re-ran the audit
against the same bad file: 14191 failed at 01:46 and again at 03:48 with nothing changed.

For each BAD artifact of this build this removes it (bin/ and bin_artifacts/), re-runs
every task that declares it - in config order, with the warm IDB, through the normal
preprocessor -> hunter -> agent path that holds new output to the contract - keeps bin/
hydrated from what the run wrote to bin_artifacts/, and audits again; an artifact that no
re-run wrote back counts as not repaired. The editor's IDA session is
paused for the run, as run_linux.sh/run_windows.sh do.

  uv run heal_contract.py -gamever 14191 -oldgamever 14190

Exit 0 the contract holds now, 1 it still does not, 2 nothing could be re-run.
"""

import argparse
import os
import re
import shutil
import subprocess
import sys

import yaml

BAD = re.compile(r"^\s*BAD\s+(?P<module>[^/\s]+)/(?P<file>[^:\s]+\.(?P<platform>linux|windows)\.yaml):")
SESSION_UNIT = "cs2vibe-ida-session.service"


def audit(gamever):
    done = subprocess.run([sys.executable, "audit_artifact_contract.py", "-gamever", gamever],
                          capture_output=True, text=True)
    bad = {}
    for line in done.stdout.splitlines():
        found = BAD.match(line)
        if found:
            bad.setdefault((found["module"], found["file"], found["platform"]), []).append(line.strip())
    return bad, done.stdout


def producing_tasks(config_path, module, filename, platform):
    """Task names in `module` that declare `filename` as an output, in config order."""
    symbol = filename[: -len(f".{platform}.yaml")]
    wanted = {filename, f"{symbol}.{{platform}}.yaml"}
    config = yaml.safe_load(open(config_path, encoding="utf-8"))
    tasks = []
    for block in config.get("modules", []):
        if block.get("name") != module:
            continue
        for task in block.get("skills") or []:
            outputs = (task.get("expected_output") or []) + (task.get("optional_output") or [])
            if wanted & set(outputs) and task.get("platform", platform) == platform:
                tasks.append(task["name"])
    return list(dict.fromkeys(tasks))


def session_active():
    return subprocess.run(["systemctl", "is-active", "--quiet", SESSION_UNIT]).returncode == 0


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("-gamever", required=True)
    parser.add_argument("-oldgamever", required=True)
    args = parser.parse_args()

    bad, report = audit(args.gamever)
    if not bad:
        print(f"heal_contract {args.gamever}: the contract holds, nothing to repair")
        return 0
    config = os.path.join("configs", f"{args.gamever}.yaml")
    plan = []
    for (module, filename, platform), lines in sorted(bad.items()):
        tasks = producing_tasks(config, module, filename, platform)
        print(f"[heal] {module}/{filename}: {'; '.join(l.split(': ', 1)[-1] for l in lines)[:220]}")
        print(f"       re-run: {', '.join(tasks) or 'NO declaring task'}")
        if tasks:
            plan.append((module, filename, platform, tasks))
    if not plan:
        return 2

    paused = session_active()
    if paused:
        subprocess.run(["systemctl", "stop", SESSION_UNIT])
    try:
        for module, filename, platform, tasks in plan:
            for root in ("bin", "bin_artifacts"):
                path = os.path.join(root, args.gamever, module, filename)
                if os.path.isfile(path):
                    os.remove(path)
            for task in tasks:
                print(f"  running {task} ({module}/{platform})")
                done = subprocess.run([sys.executable, "ida_analyze_bin.py", "-gamever", args.gamever,
                                       "-oldgamever", args.oldgamever, "-platform", platform,
                                       "-modules", module, "-skill", task, "-require_warm_idb"],
                                      capture_output=True, text=True)
                tail = [l for l in done.stdout.splitlines() if task in l or "Hunter:" in l or "Error" in l][-4:]
                for line in tail:
                    print(f"    {line.strip()[:200]}")
                # the run writes to bin_artifacts/ (its artifact directory); keep bin/ hydrated
                produced = os.path.join("bin_artifacts", args.gamever, module, filename)
                if os.path.isfile(produced):
                    os.makedirs(os.path.join("bin", args.gamever, module), exist_ok=True)
                    shutil.copy2(produced, os.path.join("bin", args.gamever, module, filename))
                    break
    finally:
        if paused:
            subprocess.run(["systemctl", "start", "--no-block", SESSION_UNIT])

    bad, report = audit(args.gamever)
    print(report.strip().splitlines()[-1] if report.strip() else "")
    # a removed artifact that no re-run wrote back is not repaired, it is gone - and the
    # audit cannot see it (it checks the files that exist)
    missing = [f"{m}/{f}" for m, f, _p, _t in plan
               if not os.path.isfile(os.path.join("bin_artifacts", args.gamever, m, f))]
    for (module, filename, _platform), lines in sorted(bad.items()):
        print(f"  still bad: {module}/{filename}")
    for name in missing:
        print(f"  not produced again: {name}")
    return 0 if not bad and not missing else 1


if __name__ == "__main__":
    sys.exit(main())
