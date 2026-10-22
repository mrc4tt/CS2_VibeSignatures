#!/usr/bin/env python3
"""
Repair the shipped values verify_plugin_gamedata contradicts, from the binary, and only
when an independent signal confirms the repair.

The gate (verify_plugin_gamedata -require-verified) stops a build whose shipped values
cannot be confirmed. Most such values are not hard: the record read the right signature
but the wrong instruction inside it, or took the other platform's layout for granted.
This finds, for each contradicted struct offset, the instruction that holds the field,
rebuilds that one artifact with emit_artifact.py (the sanctioned rebuild: same sig maker
as Ctrl-Alt-E, then validate_artifacts), and lets the gate judge the result again.

A repair is planned only with evidence that does not come from the repair itself:

  xplat-evidence  the other platform is anchored in an identified function F, and F on
                  this platform accesses the other platform's value at the field's width
                  (verify_plugin_gamedata.anchor_disagreement names the instruction)
  in-signature    another instruction inside this record's own offset_sig touches the
                  whole field, AND its value equals the other platform's verified value

  rtti            a virtual's index is wrong: the class's primary vtable names the slot
                  that holds its function, taken only when the function's own signature
                  lands on it or a call site of it uses exactly that slot

A value flagged only by "unique" (it shares an offset with a wrong neighbour) is not
touched: it clears once the neighbour is repaired. Anything else is reported and left
for a person - the build stays held.

  uv run auto_repair.py -gamever 14190            # plan only
  uv run auto_repair.py -gamever 14190 -apply     # emit, pack, generate, verify again

Exit codes: 0 every shipped value verifies (after any repairs), 1 still unhealthy,
2 a repair or a pipeline step failed.
"""

import argparse
import json
import os
import subprocess
import sys

import validate_artifacts as V
import verify_plugin_gamedata as P

PLUGIN_SUFFIXES = (".json", ".jsonc", ".txt")


def shipped_files(gamever, gamedata_root="gamedata"):
    """Every file an enabled generator ships for this build (the autopilot gate's set)."""
    import publish_site_data
    disabled = publish_site_data.disabled_plugins()
    root = os.path.join(gamedata_root, gamever)
    out = []
    for base, _dirs, names in os.walk(root):
        for name in names:
            if not name.endswith(PLUGIN_SUFFIXES) or name.endswith(".metadata.json"):
                continue
            path = os.path.join(base, name)
            plugin = os.path.relpath(path, root).split(os.sep)[0]
            if plugin not in disabled:
                out.append(path)
    return sorted(out)


def verify(gamever, path, snapshot=None, platform=None):
    """verify_plugin_gamedata's JSON report for one file."""
    cmd = [sys.executable, "verify_plugin_gamedata.py", "-gamever", gamever, "-gamedata", path,
           "-require-verified", "-json"]
    if platform:
        cmd += ["-platform", platform]
    if snapshot:
        cmd += ["-snapshot", snapshot]
    done = subprocess.run(cmd, capture_output=True, text=True)
    try:
        return json.loads(done.stdout)
    except ValueError:
        return {"gamedata": path, "results": [], "unhealthy": -1, "error": done.stderr[-300:]}


def _in_signature(binaries, platform, record_cell, other_cell, artifact):
    """(ea, value) of another instruction inside the record's own offset_sig that touches
    the whole field and carries the other platform's verified value, or None."""
    if not other_cell or other_cell.get("verification") != "verified":
        return None
    rec, want = record_cell["record"], (other_cell.get("record") or {}).get("offset")
    size = rec.get("size")
    # the signature of the record that was JUDGED, not whatever the artifact says now
    sig = rec.get("offset_sig") or artifact.get("offset_sig")
    if want is None or size not in (1, 2, 4, 8) or not sig:
        return None
    blob, info, _ = binaries.get(rec["module"], platform)
    if blob is None:
        return None
    hits = P._code_hits(blob, info, sig)
    if len(hits) != 1:
        return None
    start = V.off_to_va(info, hits[0])
    pattern = V.parse_sig(sig)
    accesses = P._field_accesses(blob, info, start, start + len(pattern), size)
    if want in accesses and want != rec["offset"]:
        return accesses[want], want
    return None


def plan(gamever, reports, binaries):
    """[(symbol, platform, ea, value, record, strategy)] and [(symbol, platform, why)] left."""
    import yaml
    repairs, left, seen = [], [], set()
    for report in reports:
        for row in report.get("results", []):
            for platform, cell in row["platforms"].items():
                if cell.get("verification") != "contradicted":
                    continue
                vrec = cell.get("vrecord")
                if vrec and vrec.get("symbol") and cell.get("rtti") == "mismatch":
                    # A virtual's index: RTTI names the slot that holds the function. Taken
                    # only when the function's own signature still lands on it (sig ok), so
                    # the index follows an identified function, not a guess.
                    key = (vrec["symbol"], platform)
                    if key not in seen:
                        seen.add(key)
                        if cell.get("slot_found") is not None and cell.get("slot_evidence"):
                            repairs.append((vrec["symbol"], platform, cell["slot_found"], cell["slot_found"],
                                            dict(vrec, kind="vfunc", offset=vrec["index"]),
                                            f"rtti: {vrec['class']} primary vtable holds it at slot "
                                            f"{cell['slot_found']}, confirmed by its {cell['slot_evidence']}"))
                        else:
                            left.append((vrec["symbol"], platform,
                                         "slot mismatch without a uniquely placed, identified function"))
                    continue
                rec = cell.get("record")
                if not rec or not rec.get("symbol"):
                    left.append((row["name"], platform, "not a struct offset this tool can rebuild"))
                    continue
                key = (rec["symbol"], platform)
                if key in seen:
                    continue
                seen.add(key)
                reasons = {m for m in ("width", "unique", "xplat", "align", "schema", "insn")
                           if cell.get(m) == "mismatch"}
                path = os.path.join("bin_artifacts", gamever, rec["module"], f"{rec['symbol']}.{platform}.yaml")
                artifact = yaml.safe_load(open(path, encoding="utf-8")) if os.path.isfile(path) else {}
                other = row["platforms"].get("windows" if platform == "linux" else "linux")
                if reasons == {"unique"}:
                    # Two members on one offset: the one the other platform agrees with keeps
                    # it; the one it disagrees with is the misread (linux m_nEntityIndex 0x48
                    # beside m_nClientSlot 0x48, windows 0x4c / 0x48).
                    other_offset = ((other or {}).get("record") or {}).get("offset")
                    found = None
                    if other_offset is not None and other_offset != rec["offset"]:
                        found = _in_signature(binaries, platform, cell, other, artifact)
                    if found:
                        repairs.append((rec["symbol"], platform, found[0], found[1], rec,
                                        "in-signature, resolves a shared offset, equals the other platform"))
                    else:
                        left.append((rec["symbol"], platform,
                                     f"shares its offset with {cell.get('shares_offset_with')}; clears once they are repaired"))
                    continue
                if cell.get("evidence_at") and cell.get("expected") is not None:
                    repairs.append((rec["symbol"], platform, int(cell["evidence_at"], 16), cell["expected"], rec,
                                    f"xplat-evidence in {cell.get('evidence_in')}"))
                    continue
                found = _in_signature(binaries, platform, cell, other, artifact)
                if found:
                    repairs.append((rec["symbol"], platform, found[0], found[1], rec,
                                    "in-signature, equals the other platform"))
                    continue
                left.append((rec["symbol"], platform, "no instruction with independent evidence ("
                             + ", ".join(sorted(reasons)) + ")"))
    return repairs, left


def emit(gamever, symbol, platform, ea, rec):
    if rec.get("kind") == "vfunc":
        # ea is the slot index here; emit_artifact reads the function out of that slot
        cmd = [sys.executable, "emit_artifact.py", "-gamever", gamever, "-module", rec["module"],
               "-platform", platform, "-symbol", symbol, "-kind", "vfunc", "-class", rec["class"],
               "-index", str(ea)]
    else:
        cmd = [sys.executable, "emit_artifact.py", "-gamever", gamever, "-module", rec["module"],
               "-platform", platform, "-symbol", symbol, "-kind", "structmember", "-ea", hex(ea),
               "-struct", rec["struct"], "-member", rec["member"], "-size", str(rec["size"])]
    done = subprocess.run(cmd, capture_output=True, text=True)
    ok = done.returncode == 0 and ": ok ->" in done.stdout
    return ok, (done.stdout + done.stderr)[-400:]


def rebuild(gamever, platform=None):
    """Pack and generate exactly as autopilot does. With one platform (the linux-first
    release) pack and generate only that one; check-contract stays red until both exist."""
    snapshot = os.path.join("gamesymbols", f"{gamever}.yaml")
    only = ["-platform", platform] if platform else []
    steps = [["gamesymbol_snapshot.py", "pack", "-gamever", gamever, "-snapshot", snapshot] + only]
    if not platform:
        steps.append(["gamesymbol_snapshot.py", "check-contract", "-gamever", gamever, "-snapshot", snapshot])
    steps.append(["update_gamedata.py", "-gamever", gamever, "-snapshot", snapshot,
                  "-outputdir", os.path.join("gamedata", gamever)] + only)
    for cmd in steps:
        done = subprocess.run([sys.executable] + cmd, capture_output=True, text=True)
        if done.returncode != 0:
            return f"{cmd[0]} failed: {(done.stdout + done.stderr)[-300:]}"
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("-gamever", required=True)
    parser.add_argument("-apply", action="store_true", help="emit the planned artifacts, then pack, generate, verify")
    parser.add_argument("-snapshot", default=None, help="judge against this snapshot (plan only)")
    parser.add_argument("-gamedata", action="append", default=None,
                        help="only these shipped files (default: every enabled file of the build)")
    parser.add_argument("-platform", choices=("linux", "windows"), default=None,
                        help="judge and repair only this platform (autopilot's linux-first release)")
    parser.add_argument("-json", action="store_true")
    args = parser.parse_args()

    files = args.gamedata or shipped_files(args.gamever)
    reports = [verify(args.gamever, path, args.snapshot, args.platform) for path in files]
    unhealthy = sum(max(0, r.get("unhealthy", 0)) for r in reports)
    if unhealthy == 0 and all(r.get("unhealthy", 0) >= 0 for r in reports):
        print(f"auto-repair {args.gamever}: every shipped value verifies, nothing to repair")
        return 0

    P._SNAPSHOT_INDEX.update(P.load_snapshot_index(args.snapshot or os.path.join("gamesymbols", f"{args.gamever}.yaml")))
    binaries = P.Binaries("bin", args.gamever)
    repairs, left = plan(args.gamever, reports, binaries)
    for symbol, platform, ea, value, rec, strategy in repairs:
        if rec.get("kind") == "vfunc":
            print(f"[repair] {symbol}.{platform}: vfunc_index {rec['offset']} -> {value} ({strategy})")
        else:
            print(f"[repair] {symbol}.{platform}: {hex(rec['offset'])} -> {hex(value)} at {hex(ea)} ({strategy})")
    for symbol, platform, why in left:
        print(f"[left]   {symbol}.{platform}: {why}")
    if args.json:
        print(json.dumps({"repairs": [{"symbol": s, "platform": p, "ea": hex(e), "from": r["offset"], "to": v,
                                       "strategy": st} for s, p, e, v, r, st in repairs],
                          "left": [{"symbol": s, "platform": p, "why": w} for s, p, w in left]}, indent=1))
    if not args.apply:
        return 1
    if args.snapshot:
        print("auto-repair: -apply rebuilds this build's own snapshot; drop -snapshot", file=sys.stderr)
        return 2

    for symbol, platform, ea, value, rec, strategy in repairs:
        ok, tail = emit(args.gamever, symbol, platform, ea, rec)
        print(f"  emit {symbol}.{platform}: {'ok' if ok else 'FAILED'}")
        if not ok:
            print(tail)
            return 2
    if repairs:
        failure = rebuild(args.gamever, args.platform)
        if failure:
            print(f"auto-repair: {failure}")
            return 2
    after = [verify(args.gamever, path, platform=args.platform) for path in files]
    still = sum(max(0, r.get("unhealthy", 0)) for r in after)
    print(f"auto-repair {args.gamever}: {len(repairs)} repaired, {still} still unhealthy")
    for report in after:
        for row in report.get("results", []):
            for platform, cell in row["platforms"].items():
                if cell.get("verification") in ("contradicted", "unverified"):
                    print(f"  still {cell['verification']}: {row['name']}.{platform}")
    return 0 if still == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
