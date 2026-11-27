#!/usr/bin/env python3
"""
Compare our artifacts with the ones HLND2T/CS2_VibeSignatures publishes for the same build.

Upstream analyses every build with its own finders and commits the result under
bin_artifacts/<gamever>/. Where both sides carry a record for one symbol and platform,
the address, slot or offset must be the same - when it is not, one side named the wrong
thing, and that is the defect none of our own gates see: a wrong identification
relocates cleanly, matches uniquely and sits in a real vtable slot. The first run on
14201 (2921 shared records, 29 differing) found four of ours that had been wrong since
14190: CCSBot_Idle.linux on EscapeFromBomb's twin, UnregisterEngineServices.linux on the
register twin, UnregisterLoopModes.windows on an unrelated loop, and
CEntitySystem_m_entityNames.linux on the map's inner tree.

Only results are compared. Upstream's finders are not read, and nothing is merged.

  differs    both records exist and a compared field is not equal
  accepted   it differs, and upstream_artifact_accept.yaml says why ours stands
  stale      an accepted symbol no longer differs: drop the entry

A differing record of theirs whose own func_name / member_name is not the file's symbol
is skipped (their CSmokeGrenadeProjectile_GetCSWeaponData files GetCSWeaponDataFromKey).

It reports and never blocks: upstream lands hours to a day after us, so the answer for a
new build arrives on a later idle tick. Each finding is decided by hand - verify in the
binary on linux AND windows, then either fix our record through its task (or
emit_artifact.py) or add the symbol to the accept file with the evidence.

  uv run upstream_artifact_check.py -gamever 14201             # report
  uv run upstream_artifact_check.py -gamever 14201 -notify -every 6   # autopilot's idle tick

Exit 0 nothing unaccepted (or upstream has no such build yet), 1 a finding, 2 fetch failed.
"""

import argparse
import hashlib
import io
import json
import os
import subprocess
import sys
import tarfile
import time

import yaml

STATE = os.path.join(".autopilot", "upstream-artifacts.json")
ACCEPT = "upstream_artifact_accept.yaml"
REMOTE = "upstream"
BRANCH = "main"
# What must be equal when both sides have it. func_size is internal, signatures are
# two spellings of one place, vfunc_offset is 8 x vfunc_index.
FIELDS = ("func_va", "gv_va", "vfunc_index", "offset")


def _number(value):
    if isinstance(value, int):
        return value
    try:
        return int(str(value), 0)
    except ValueError:
        return str(value).lower()


def split_name(filename):
    """'CCSBot_Idle.linux.yaml' -> ('CCSBot_Idle', 'linux'); anything else -> None."""
    parts = filename.rsplit(".", 2)
    if len(parts) != 3 or parts[2] != "yaml" or parts[1] not in ("linux", "windows"):
        return None
    return parts[0], parts[1]


def names_itself(symbol, record):
    """False when the record carries a name field and it is another symbol's."""
    if "struct_name" in record and "member_name" in record:
        return symbol == f"{record['struct_name']}_{record['member_name']}"
    for field in ("func_name", "gv_name"):
        if field in record:
            return record[field] == symbol
    return True


def compare(ours, theirs):
    """{field: (ours, theirs)} for every compared field present on both sides and unequal."""
    out = {}
    for field in FIELDS:
        if ours.get(field) is None or theirs.get(field) is None:
            continue
        if _number(ours[field]) != _number(theirs[field]):
            out[field] = (ours[field], theirs[field])
    return out


def load_accept(path=ACCEPT):
    """{'Symbol' or 'Symbol.platform': reason}."""
    if not os.path.isfile(path):
        return {}
    data = yaml.safe_load(open(path, encoding="utf-8")) or {}
    return {str(key): str(value) for key, value in data.items()}


def accepted_reason(accept, symbol, platform):
    return accept.get(f"{symbol}.{platform}") or accept.get(symbol)


def load_ours(gamever, root="bin_artifacts"):
    records = {}
    base = os.path.join(root, gamever)
    for module in sorted(os.listdir(base)) if os.path.isdir(base) else []:
        directory = os.path.join(base, module)
        if not os.path.isdir(directory):
            continue
        for filename in os.listdir(directory):
            name = split_name(filename)
            if not name:
                continue
            try:
                record = yaml.safe_load(open(os.path.join(directory, filename), encoding="utf-8"))
            except yaml.YAMLError:
                continue
            if isinstance(record, dict):
                records[(module, *name)] = record
    return records


def load_theirs(gamever, ref):
    """Their records read straight from the fetched ref - no checkout, no files written."""
    done = subprocess.run(["git", "archive", ref, f"bin_artifacts/{gamever}"], capture_output=True, timeout=300)
    if done.returncode != 0:
        return None
    records = {}
    with tarfile.open(fileobj=io.BytesIO(done.stdout)) as archive:
        for member in archive:
            if not member.isfile():
                continue
            parts = member.name.split("/")
            name = split_name(parts[-1])
            if len(parts) != 4 or not name:
                continue
            try:
                record = yaml.safe_load(archive.extractfile(member).read().decode("utf-8", "replace"))
            except yaml.YAMLError:
                continue
            if isinstance(record, dict):
                records[(parts[2], *name)] = record
    return records


def judge(ours, theirs, accept):
    """-> (findings, accepted, stale, shared, skipped); findings/accepted are sorted lists of
    (module, symbol, platform, {field: (ours, theirs)}[, reason])."""
    findings, accepted, differing, skipped = [], [], set(), 0
    shared = sorted(set(ours) & set(theirs))
    for key in shared:
        module, symbol, platform = key
        delta = compare(ours[key], theirs[key])
        if not delta:
            continue
        if not names_itself(symbol, theirs[key]):
            skipped += 1  # their record says itself that it is another symbol
            continue
        differing.add(symbol)
        differing.add(f"{symbol}.{platform}")
        reason = accepted_reason(accept, symbol, platform)
        if reason:
            accepted.append((module, symbol, platform, delta, reason))
        else:
            findings.append((module, symbol, platform, delta))
    stale = sorted(entry for entry in accept if entry not in differing)
    return findings, accepted, stale, len(shared), skipped


def render(finding):
    module, symbol, platform, delta = finding[:4]
    fields = ", ".join(f"{field} ours {mine} / theirs {other}" for field, (mine, other) in sorted(delta.items()))
    return f"  differs  {module}/{symbol}.{platform}: {fields}"


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("-gamever", required=True)
    parser.add_argument("-notify", action="store_true", help="send findings that changed since the last report")
    parser.add_argument("-every", type=float, default=0,
                        help="hours: do nothing when the last -notify run is more recent (autopilot's idle tick)")
    parser.add_argument("-no-fetch", action="store_true", help="compare against the ref as last fetched")
    parser.add_argument("-accepted", action="store_true", help="also list the accepted differences")
    args = parser.parse_args()

    try:
        state = json.load(open(STATE, encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    if args.every and time.time() - state.get("_last_run", 0) < args.every * 3600:
        return 0

    ref = f"{REMOTE}/{BRANCH}"
    if not args.no_fetch:
        # Fetch only: the remote's push URL is disabled, and nothing here writes to it.
        fetched = subprocess.run(["git", "fetch", "--quiet", "--no-tags", REMOTE, BRANCH],
                                 capture_output=True, text=True, timeout=600)
        if fetched.returncode != 0:
            print(f"upstream_artifact_check {args.gamever}: fetch failed: "
                  f"{(fetched.stderr.strip().splitlines() or ['?'])[-1]}")
            return 2

    def remember(digest=None):
        if not args.notify:
            return
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        state["_last_run"] = int(time.time())
        if digest is not None:
            state[args.gamever] = digest
        with open(STATE, "w", encoding="utf-8") as handle:
            json.dump(state, handle, indent=1, sort_keys=True)

    theirs = load_theirs(args.gamever, ref)
    if not theirs:
        print(f"upstream_artifact_check {args.gamever}: upstream has no artifacts for this build yet")
        remember()
        return 0
    ours = load_ours(args.gamever)
    accept = load_accept()
    findings, accepted, stale, shared, skipped = judge(ours, theirs, accept)

    for finding in findings:
        print(render(finding))
    if args.accepted:
        for item in accepted:
            print(render(item).replace("  differs ", "  accepted", 1) + f"  [{item[4]}]")
    for entry in stale:
        print(f"  stale    {entry}: accepted in {ACCEPT}, no longer differs")
    summary = (f"upstream_artifact_check {args.gamever}: {shared} shared records, {len(findings)} differ, "
               f"{len(accepted)} accepted, {len(stale)} stale accept entries, {skipped} of theirs skipped")
    print(summary)

    lines = [render(finding) for finding in findings]
    digest = hashlib.sha256("\n".join(lines).encode()).hexdigest()[:16]
    if args.notify and lines and state.get(args.gamever) != digest and os.access("./autopilot_notify.sh", os.X_OK):
        body = "\n".join(lines)[:1600] + ("\n\nour record or theirs names the wrong thing: verify in the binary on "
                                          "both platforms, then fix ours or add it to " + ACCEPT)
        subprocess.run(["./autopilot_notify.sh", "upstream-artifacts", args.gamever, body])
    remember(digest)
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
