#!/usr/bin/env python3
"""Check every artifact of a gamever against its task's declared fields.

A wrong record resolves cleanly in the binary, so validate_artifacts and the
identity audits pass it. 14190 shipped CBaseEntity_OnTakeDamage.windows filed as
CBasePlayerPawn_OnTakeDamage on CBasePlayerPawn's vtable, g_pGameEntitySystem.linux
read from another instruction, and eight virtuals whose declared vfunc_sig had been
replaced by func_va/func_sig - all written by an agent after a preprocessor failed.

Per artifact (artifact_contract.artifact_contract_issues):
  name      func_name/gv_name/patch_name is the file's symbol, or the previous
            gamever's value (upstream's historical renames)
  class     vtable_name/struct_name/member_name equal the previous gamever's
  fields    nothing outside the task's GENERATE_YAML_DESIRED_FIELDS (the previous
            gamever's fields when no task declares the symbol), and nothing dropped
            that the previous gamever carried and the task still asks for

The run applies the same check to every hunter and agent output and rejects a
failing one; this catches what reached the artifacts any other way (review-issue
confirmations, Ctrl-Alt-E/D, hand edits, an older run).

The fix for a finding is never an edit of the artifact (rule 18): re-run its task,
  uv run ida_analyze_bin.py -gamever <VER> -platform <p> -modules <m> -skill <task> -require_warm_idb
and if the task itself cannot produce the field, change the task's field list.

  uv run audit_artifact_contract.py -gamever 14190
  uv run audit_artifact_contract.py -gamever 14190 -old 14188 -module server

Exit status: 0 when nothing is reported, 1 otherwise, 2 on usage errors.
"""

from __future__ import annotations

import argparse
import glob
import os
import sys

from artifact_contract import artifact_contract_issues
from audit_identity_drift import previous_gamever


def audit(gamever, old, platforms, artifactdir, module_filter=None):
    issues = []
    checked = 0
    root = os.path.join(artifactdir, gamever)
    for module in sorted(os.listdir(root)):
        if module_filter and module != module_filter:
            continue
        module_dir = os.path.join(root, module)
        if not os.path.isdir(module_dir):
            continue
        old_dir = os.path.join(artifactdir, old, module) if old else None
        for platform in platforms:
            paths = sorted(glob.glob(os.path.join(module_dir, f"*.{platform}.yaml")))
            checked += len(paths)
            issues.extend(f"{module}/{issue}" for issue in artifact_contract_issues(paths, platform, old_dir))
    return checked, issues


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("-gamever", required=True)
    parser.add_argument("-old", help="gamever to compare against (default: the one before -gamever)")
    parser.add_argument("-platform", default="linux,windows")
    parser.add_argument("-module", help="only this module")
    parser.add_argument("-bindir", default="bin")
    parser.add_argument("-artifactdir", default="bin_artifacts")
    args = parser.parse_args(argv)
    if not os.path.isdir(os.path.join(args.artifactdir, args.gamever)):
        print(f"no artifacts for {args.gamever} under {args.artifactdir}", file=sys.stderr)
        return 2
    old = args.old or previous_gamever(args.artifactdir, args.gamever, args.bindir)
    platforms = [p for p in args.platform.split(",") if p]
    checked, issues = audit(args.gamever, old, platforms, args.artifactdir, args.module)
    for issue in issues:
        print(f"  BAD  {issue}")
    print(f"audit_artifact_contract {args.gamever} vs {old}: {checked} artifacts, {len(issues)} bad")
    return 1 if issues else 0


if __name__ == "__main__":
    sys.exit(main())
