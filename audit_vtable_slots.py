#!/usr/bin/env python3
"""Check every virtual's slot against the same symbol on the previous gamever.

A vtable slot is fixed by declaration order, so between two builds a slot only moves
when virtuals are added or removed before it - and then it moves the same way as
its neighbours. validate_artifacts cannot see a wrong slot: it checks that the
vtable really holds func_va at vfunc_index, which is just as true of the NEXT
virtual. vtidx_FinishMove.windows named slot 39 (the jump/stamina step after
FinishMove) on 14184 and 14186-14188 while the vtable kept its size, and
bot-controller / bot-improver shipped vtidx::FinishMove = 39.

The rule: a slot's shift (new index - old index) must lie between the shifts of
the nearest artifacts below and above it in the same vtable. With no known
neighbour below, the floor is 0 (nothing before the first slot moved); with none
above, the ceiling is the vtable's change in length. So a vtable that kept its
size and has no neighbours allows no shift at all, and an insertion of N slots
allows 0..N.

Verdicts:
  OK       the shift is inside that range
  SHIFTED  outside it: the record names a different slot than the previous
           build did, with nothing around it moving that way - one of the two
           builds is wrong (decide which with the other platform: on most
           vtables linux = windows + 1)
  SKIP     no previous artifact or index, or nothing bounds the top (an interface
           with no vtable artifact and no known slot above this one)

  uv run audit_vtable_slots.py -gamever 14188              # previous = the gamever before it
  uv run audit_vtable_slots.py -gamever 14184 -old 14183 -symbol FinishMove

The run applies the same rule to every relocation (relocation_slot_verdict) and
discards a SHIFTED one; CS2VIBE_RELOC_SLOT_CHECK=0 turns that off.

Exit status: 0 when nothing is SHIFTED, 1 otherwise, 2 on usage errors.
"""

from __future__ import annotations

import argparse
import glob
import os
import re
import sys

import yaml

from audit_identity_drift import previous_gamever

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def _load(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            doc = yaml.safe_load(f)
    except (OSError, yaml.YAMLError):
        return None
    return doc if isinstance(doc, dict) else None


def _index(doc):
    value = (doc or {}).get("vfunc_index")
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    try:
        text = str(value).strip()
        return int(text, 16) if text.lower().startswith("0x") else int(text)
    except (TypeError, ValueError):
        return None


def _vtable_length(directory, vtable_name, platform):
    stem = vtable_name if vtable_name.endswith("_vtable") else f"{vtable_name}_vtable"  # as the run names it
    doc = _load(os.path.join(directory, f"{stem}.{platform}.yaml"))
    entries = (doc or {}).get("vtable_entries")
    return len(entries) if entries else None


def slot_shift_verdict(old_index, new_index, old_length, new_length, neighbours=(), twin_shift=None):
    """('ok' | 'shifted' | None, reason) for one virtual's move between two builds.

    *neighbours* are (old_index, new_index) pairs of other virtuals of the same
    vtable on both builds; *twin_shift* is the same symbol's shift on the other
    platform. None when the question cannot be answered.
    """
    if old_index is None or new_index is None:
        return None, "missing index"
    shift = new_index - old_index
    if shift and twin_shift == shift:
        # Two compilers agreeing on a move is a layout change, not a misread:
        # CBaseModelEntity_DamageDecal moved +3 on both on 14182 while its
        # vtable grew by 2 (a slot removed above it as three were added below).
        return "ok", f"{old_index} -> {new_index}, the other platform moved {shift:+d} too"
    below = [(o, n - o) for o, n in neighbours if o < old_index]
    above = [(o, n - o) for o, n in neighbours if o > old_index]
    if not above and None in (old_length, new_length):
        # an interface with no vtable artifact: nothing bounds the top
        return None, "no vtable and no known slot above"
    floor = max(below)[1] if below else 0
    ceiling = min(above)[1] if above else new_length - old_length
    low, high = min(floor, ceiling), max(floor, ceiling)
    if low <= shift <= high:
        return "ok", f"{old_index} -> {new_index}"
    return "shifted", (
        f"{old_index} -> {new_index} ({shift:+d}) while "
        f"{'the slot below moved ' + format(floor, '+d') if below else 'nothing below moved'}, "
        f"{'the slot above ' + format(ceiling, '+d') if above else 'the vtable ' + format(ceiling, '+d')}"
    )


_SLOT_FIELD = re.compile(r"^(vtable_name|vfunc_index):[ \t]*['\"]?([^'\"\s#]*)", re.M)
_FILE_CACHE: dict = {}


def _slot_records(directory, platform):
    """{basename: (vtable_name, index)} for every virtual in *directory*.

    Read with a line regex rather than a YAML parse (thousands of files per
    directory), and cached per file on (mtime, size): a run adds and rewrites
    artifacts while it goes, which a directory-level stamp would miss.
    """
    records = {}
    for path in glob.glob(os.path.join(directory, f"*.{platform}.yaml")):
        base = os.path.basename(path)
        if base.endswith(f"_vtable.{platform}.yaml"):
            continue
        try:
            st = os.stat(path)
        except OSError:
            continue
        stamp = (st.st_mtime_ns, st.st_size)
        cached = _FILE_CACHE.get(path)
        if cached is None or cached[0] != stamp:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    fields = dict(_SLOT_FIELD.findall(f.read()))
            except OSError:
                continue
            index = _index(fields)
            record = (fields["vtable_name"], index) if fields.get("vtable_name") and index is not None else None
            cached = _FILE_CACHE[path] = (stamp, record)
        if cached[1]:
            records[base] = cached[1]
    return records


def _neighbours(old_dir, new_dir, vtable_name, platform, exclude):
    """(old, new) slot pairs of the other virtuals of *vtable_name* found in both dirs."""
    new_records = _slot_records(new_dir, platform)
    pairs = []
    for base, (name, old_index) in _slot_records(old_dir, platform).items():
        if base == exclude or name != vtable_name:
            continue
        new = new_records.get(base)
        if new and new[0] == vtable_name:
            pairs.append((old_index, new[1]))
    return pairs


OTHER_PLATFORM = {"linux": "windows", "windows": "linux"}


def _twin_shift(old_dir, new_dir, base, platform):
    """The same symbol's slot shift on the other platform, or None."""
    other = OTHER_PLATFORM.get(platform)
    twin = base.replace(f".{platform}.yaml", f".{other}.yaml") if other else None
    if not twin:
        return None
    old = _slot_records(old_dir, other).get(twin)
    new = _slot_records(new_dir, other).get(twin)
    return new[1] - old[1] if old and new and old[0] == new[0] else None


def relocation_slot_verdict(platform, vtable_name, new_index, new_binary_dir, old_yaml_path):
    """Judge a fresh relocation's slot inside a run: 'shifted' | 'ok' | None.

    Only 'shifted' is meant to reject. The neighbours come from whatever this run
    has already written next to the binary, so early in a run the range falls
    back to the vtable's change in length - which is exactly the FinishMove case.
    """
    if not vtable_name or not new_binary_dir or not old_yaml_path or not os.path.exists(old_yaml_path):
        return None
    old_doc = _load(old_yaml_path)
    if not old_doc or old_doc.get("vtable_name") != vtable_name:
        return None
    old_dir = os.path.dirname(os.path.abspath(old_yaml_path))
    verdict, _why = slot_shift_verdict(
        _index(old_doc),
        _index({"vfunc_index": new_index}),
        _vtable_length(old_dir, vtable_name, platform),
        _vtable_length(new_binary_dir, vtable_name, platform),
        _neighbours(old_dir, new_binary_dir, vtable_name, platform, os.path.basename(old_yaml_path)),
        _twin_shift(old_dir, new_binary_dir, os.path.basename(old_yaml_path), platform),
    )
    return verdict


def audit(gamever, old, platforms, artifactdir, symbol_filter, verbose):
    counts = {"OK": 0, "SHIFTED": 0, "SKIP": 0}
    for path in sorted(glob.glob(os.path.join(artifactdir, gamever, "*", "*.yaml"))):
        module = os.path.basename(os.path.dirname(path))
        base = os.path.basename(path)
        name, _, platform = base[: -len(".yaml")].rpartition(".")
        if platform not in platforms or (symbol_filter and symbol_filter.lower() not in name.lower()):
            continue
        doc = _load(path)
        vtable_name = (doc or {}).get("vtable_name")
        if not vtable_name or _index(doc) is None or name.endswith("_vtable"):
            continue
        old_dir = os.path.join(artifactdir, old, module)
        new_dir = os.path.dirname(path)
        old_doc = _load(os.path.join(old_dir, base))
        if not old_doc or old_doc.get("vtable_name") != vtable_name:
            counts["SKIP"] += 1
            continue
        verdict, why = slot_shift_verdict(
            _index(old_doc),
            _index(doc),
            _vtable_length(old_dir, vtable_name, platform),
            _vtable_length(new_dir, vtable_name, platform),
            _neighbours(old_dir, new_dir, vtable_name, platform, base),
            _twin_shift(old_dir, new_dir, base, platform),
        )
        label = {"ok": "OK", "shifted": "SHIFTED"}.get(verdict, "SKIP")
        counts[label] += 1
        if label == "SHIFTED" or (verbose and label == "OK"):
            print(f"  {label:<7} {module}/{base[:-5]} {vtable_name}: {why}")
    print(
        f"audit_vtable_slots {gamever} vs {old}: {counts['OK']} ok, {counts['SHIFTED']} shifted, "
        f"{counts['SKIP']} skipped"
    )
    return counts["SHIFTED"]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("-gamever", required=True)
    parser.add_argument("-old", help="gamever to compare against (default: the one before -gamever)")
    parser.add_argument("-platform", default="linux,windows")
    parser.add_argument("-bindir", default="bin")
    parser.add_argument("-artifactdir", default="bin_artifacts")
    parser.add_argument("-symbol", help="only symbols whose name contains this text")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    os.chdir(SCRIPT_DIR)
    old = args.old or previous_gamever(args.artifactdir, args.gamever, args.bindir)
    if not old:
        print(f"audit_vtable_slots: no gamever before {args.gamever!r}", file=sys.stderr)
        return 2
    platforms = [p.strip() for p in args.platform.split(",") if p.strip() in ("linux", "windows")]
    return 1 if audit(args.gamever, old, platforms, args.artifactdir, args.symbol, args.verbose) else 0


if __name__ == "__main__":
    sys.exit(main())
