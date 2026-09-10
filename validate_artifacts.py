#!/usr/bin/env python3
"""Verify every per-symbol artifact against the binary it claims to describe.

The snapshot contract checks that declared artifacts EXIST and the schema gate
checks that they are SHAPED right, but nothing checked that their contents are
still true of the binary. Every defect found by hand on 14181 was of that kind:

  * gv_va holding the match address instead of the data address the instruction
    refers to (3 artifacts)
  * a cross-module signature that matched once in a binary the class is not even
    present in (CNetChan in engine2)
  * a vfunc_index copied from the other platform where the slot differs
  * func_size cut short at the first ret+padding, missing a tail block reached
    only by a forward jump (0x4af instead of 0x885)
  * signatures with literal rel8 branch displacements ("74 D4"), which shift as
    soon as the block moves

Checks are split by severity: an error means the artifact is provably wrong for
this binary, a warning means it is suspicious and worth a look. -strict makes
warnings fail too.

Usage:
    uv run validate_artifacts.py -gamever 14181
    uv run validate_artifacts.py -gamever 14181 -module server -platform linux
    uv run validate_artifacts.py -gamever 14181 -json
"""

import argparse
import glob
import json
import os
import re
import struct
import sys
from collections import defaultdict

import yaml

try:
    import capstone
    _MD = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
except Exception:            # the size check degrades gracefully without it
    capstone = None
    _MD = None

from auto_hunt_headless import BIN_LINUX, BIN_WIN, load_binary, off_to_va, va_to_off
from source_artifact_schema import canonical_symbol_yaml_bytes

MIN_SIG_BYTES = 24
PADDING = (0xCC, 0x90)

SIG_FIELDS = {
    "func_sig": "func_va",
    "gv_sig": "gv_sig_va",
    "vfunc_sig": None,          # a call-site pattern; no VA is stored with it
    "patch_sig": "patch_va",
    "offset_sig": None,         # structmember; the VA is not part of the schema
}


# ---------------------------------------------------------------------------
# signature helpers
# ---------------------------------------------------------------------------

def parse_sig(sig):
    """Signature text -> list of ints, with None for a wildcard byte."""
    out = []
    for tok in str(sig).split():
        # Artifact YAML spells a wildcard "??" (and upstream sometimes "?").
        # "2A" is NOT a wildcard here even though cs2kz gamedata writes \x2A for
        # one - in an artifact it is the literal byte 0x2A, and treating it as a
        # wildcard invented multi-match reports.
        if tok in ("?", "??"):
            out.append(None)
        else:
            try:
                out.append(int(tok, 16))
            except ValueError:
                return None
    return out


def matches_at(blob, off, pat):
    if off < 0 or off + len(pat) > len(blob):
        return False
    for i, b in enumerate(pat):
        if b is not None and blob[off + i] != b:
            return False
    return True


def _longest_literal_run(pat):
    """(start, length) of the longest wildcard-free stretch - the search anchor."""
    best = (0, 0)
    run = 0
    for i, b in enumerate(pat):
        if b is None:
            run = 0
            continue
        run += 1
        if run > best[1]:
            best = (i - run + 1, run)
    return best


def find_all(blob, pat, limit=64):
    """Every offset where pat matches, anchored on its longest literal run.

    Scanning the whole image with a wildcard regex costs far more than letting
    bytes.find (memchr) locate the anchor and checking the rest by hand.
    """
    start, length = _longest_literal_run(pat)
    if length == 0:
        return []                       # all wildcards: refuse rather than match
    needle = bytes(pat[start:start + length])
    hits = []
    i = blob.find(needle)
    while i != -1 and len(hits) < limit:
        off = i - start
        if matches_at(blob, off, pat):
            hits.append(off)
        i = blob.find(needle, i + 1)
    return hits


def literal_branch_bytes(pat, blob, off):
    """Branch displacements left literal in the signature.

    rel8 and rel32 targets move whenever surrounding code shifts, so upstream
    wildcards them. Returns the offsets inside the signature that look like a
    literal displacement.
    """
    bad = []
    i = 0
    while i < len(pat) - 1:
        b = pat[i]
        if b is None:
            i += 1
            continue
        # short jcc (0x70-0x7f) and short jmp (0xeb): 1 displacement byte
        if (0x70 <= b <= 0x7F or b == 0xEB) and i + 1 < len(pat) and pat[i + 1] is not None:
            bad.append(i + 1)
            i += 2
            continue
        # near call/jmp (0xe8/0xe9): 4 displacement bytes
        if b in (0xE8, 0xE9) and i + 4 < len(pat) and any(pat[i + k] is not None for k in range(1, 5)):
            bad.append(i + 1)
            i += 5
            continue
        # two-byte jcc (0x0f 0x80-0x8f): 4 displacement bytes
        if b == 0x0F and pat[i + 1] is not None and 0x80 <= pat[i + 1] <= 0x8F \
                and i + 5 < len(pat) and any(pat[i + k] is not None for k in range(2, 6)):
            bad.append(i + 2)
            i += 6
            continue
        i += 1
    return bad


# ---------------------------------------------------------------------------
# binary helpers
# ---------------------------------------------------------------------------

def is_exec(info, off):
    return any(fo <= off < fo + fs and (fl & 0x1) for fo, _v, fs, fl in info["segs"])


def is_boundary(blob, info, va):
    """Does va look like a function head: padding before it, or 16-aligned."""
    off = va_to_off(info, va)
    if off is None or off == 0:
        return False
    return blob[off - 1] in PADDING or va % 16 == 0


TERMINATORS = ("ret", "retf", "jmp", "ud2", "int3", "hlt")


def ends_clean(blob, info, va, size):
    """Does the claimed range end where a function can end?

    Requiring padding or 16-byte alignment after the end is the wrong invariant:
    GCC packs the next function directly after a tail jmp at arbitrary alignment,
    which flagged 25 correct upstream sizes on 14181 (CGameEventManager_Shutdown
    is a genuine 6-byte thunk). The real invariant is that the last instruction
    in the range transfers control away.
    """
    end = va + size
    off = va_to_off(info, end)
    if off is None or off >= len(blob):
        return False
    if blob[off] in PADDING:
        return True
    if _MD is None:
        return end % 16 == 0
    start = va_to_off(info, va)
    last = None
    for ins in _MD.disasm(blob[start:off], va):
        if ins.address + ins.size > end:
            return False                  # the boundary cuts an instruction in half
        last = ins
    return last is not None and last.address + last.size == end \
        and last.mnemonic in TERMINATORS


def data_sections(info):
    return [(fo, v, fs) for fo, v, fs, fl in info["segs"] if not (fl & 0x1)]


def in_data(info, va):
    return any(v <= va < v + fs for _fo, v, fs in data_sections(info))


# ---------------------------------------------------------------------------
# per-category checks
# ---------------------------------------------------------------------------

def check_sig_field(rec, blob, info, field, sig, claim_va, out, pedantic=False):
    pat = parse_sig(sig)
    if pat is None:
        out.error(rec, f"{field} is not parseable hex")
        return
    if all(b is None for b in pat):
        out.error(rec, f"{field} is entirely wildcards")
        return
    # a gv/patch/offset signature is one instruction plus wildcards, so the
    # 24-byte floor only means anything for a function signature
    if pedantic and field in ("func_sig", "vfunc_sig") and len(pat) < MIN_SIG_BYTES:
        out.warn(rec, f"{field} is {len(pat)} bytes, under the {MIN_SIG_BYTES}-byte minimum")

    hits = find_all(blob, pat)
    vas = [off_to_va(info, o) for o in hits]
    vas = [v for v in vas if v is not None]

    if not hits:
        out.error(rec, f"{field} matches nowhere in {rec['binary']}")
        return
    if claim_va is not None:
        if claim_va not in vas:
            out.error(rec, f"{field} does not match at the stored address "
                           f"{hex(claim_va)} (matches at {[hex(v) for v in vas[:4]]})")
        elif len(vas) > 1:
            out.warn(rec, f"{field} matches {len(vas)} places, "
                          f"{[hex(v) for v in vas[:4]]}")
    elif len(vas) > 1:
        out.warn(rec, f"{field} matches {len(vas)} places, {[hex(v) for v in vas[:4]]}")

    anchor = claim_va if claim_va in vas else vas[0]
    off = va_to_off(info, anchor)
    if pedantic and off is not None:
        for k in literal_branch_bytes(pat, blob, off):
            out.warn(rec, f"{field} keeps a literal branch displacement at byte {k}"
                          f" - wildcard it, offsets shift when code moves")
            break


def check_func(rec, d, blob, info, out):
    va = rec["va"]
    if va is None:
        out.error(rec, "func_va is missing or unparseable")
        return
    if va_to_off(info, va) is None:
        out.error(rec, f"func_va {hex(va)} is outside every mapped segment")
        return
    if not is_exec(info, va_to_off(info, va)):
        out.error(rec, f"func_va {hex(va)} is not in an executable section")
    if not is_boundary(blob, info, va):
        out.warn(rec, f"func_va {hex(va)} has neither padding before it nor 16-byte alignment")

    rva = d.get("func_rva")
    if rva is not None and int(str(rva), 16) != va - info["base"]:
        out.error(rec, f"func_rva {rva} disagrees with func_va - base "
                       f"({hex(va - info['base'])})")

    size = d.get("func_size")
    if size is None or int(str(size), 16) == 0:
        out.warn(rec, "func_size is 0x0 (unknown)")
    elif not ends_clean(blob, info, va, int(str(size), 16)):
        out.warn(rec, f"func_size {size} does not end on padding or a 16-byte boundary")

    if d.get("func_sig"):
        check_sig_field(rec, blob, info, "func_sig", d["func_sig"], va, out, out.pedantic)


def check_gv(rec, d, blob, info, out):
    sig_va = rec["va"]
    gv_va = _hexint(d.get("gv_va"))
    if gv_va is None:
        out.error(rec, "gv_va is missing or unparseable")
        return

    rva = d.get("gv_rva")
    if rva is not None and int(str(rva), 16) != gv_va - info["base"]:
        out.error(rec, f"gv_rva {rva} disagrees with gv_va - base")

    if d.get("gv_sig"):
        check_sig_field(rec, blob, info, "gv_sig", d["gv_sig"], sig_va, out, out.pedantic)

    # gv_va must be the address the instruction refers to, not the match address
    if sig_va is not None:
        inst = sig_va + int(d.get("gv_inst_offset") or 0)
        length = int(d.get("gv_inst_length") or 0)
        disp_at = inst + int(d.get("gv_inst_disp") or 0)
        doff = va_to_off(info, disp_at)
        if length and doff is not None and doff + 4 <= len(blob):
            want = inst + length + struct.unpack_from("<i", blob, doff)[0]
            if want != gv_va:
                out.error(rec, f"gv_va {hex(gv_va)} is not what the instruction at "
                               f"{hex(sig_va)} refers to ({hex(want)}) - writing the "
                               f"match address here is a known defect")
    if not in_data(info, gv_va) and va_to_off(info, gv_va) is not None:
        out.warn(rec, f"gv_va {hex(gv_va)} lands in an executable section, not data")


def check_vfunc(rec, d, blob, info, out):
    idx = d.get("vfunc_index")
    off = d.get("vfunc_offset")
    if idx is not None and off is not None:
        if int(str(off), 16) != 8 * int(idx):
            out.error(rec, f"vfunc_offset {off} is not 8 * vfunc_index {idx}")
    if d.get("func_va"):
        check_func(rec, d, blob, info, out)
    elif d.get("vfunc_sig"):
        check_sig_field(rec, blob, info, "vfunc_sig", d["vfunc_sig"], None, out, out.pedantic)
    elif idx is None:
        out.error(rec, "vfunc artifact carries neither an address, a signature, nor an index")


def check_vtable(rec, d, blob, info, out):
    va = _hexint(d.get("vtable_va"))
    if va is None:
        out.error(rec, "vtable_va is missing or unparseable")
        return
    rva = d.get("vtable_rva")
    if rva is not None and int(str(rva), 16) != va - info["base"]:
        out.error(rec, f"vtable_rva {rva} disagrees with vtable_va - base")

    n = d.get("vtable_numvfunc")
    size = d.get("vtable_size")
    if n is not None and size is not None and int(str(size), 16) != 8 * int(n):
        out.error(rec, f"vtable_size {size} is not 8 * vtable_numvfunc {n}")

    entries = d.get("vtable_entries") or {}
    if n is not None and len(entries) != int(n):
        out.warn(rec, f"vtable_entries has {len(entries)} rows but vtable_numvfunc is {n}")

    # every declared slot must still hold a pointer into executable memory
    bad, unresolved = [], 0
    for k, v in sorted(entries.items(), key=lambda kv: int(kv[0])):
        want = _hexint(v)
        if want is None:
            bad.append((k, "unparseable"))
            continue
        if want == 0:
            # a PIE stores the slot in .rela.dyn, not in the file bytes, so the
            # generator records 0 for pure-virtual and relocated slots alike
            unresolved += 1
            continue
        toff = va_to_off(info, want)
        if toff is None or not is_exec(info, toff):
            bad.append((k, hex(want)))
    if bad:
        out.error(rec, f"{len(bad)} vtable slot(s) do not point at code: {bad[:4]}")
    if unresolved and out.pedantic:
        out.warn(rec, f"{unresolved} vtable slot(s) recorded as 0x0 (relocated or pure virtual)")


def check_structmember(rec, d, blob, info, out):
    if d.get("offset") is None:
        out.error(rec, "structmember artifact has no offset")
    if d.get("offset_sig"):
        check_sig_field(rec, blob, info, "offset_sig", d["offset_sig"], None, out, out.pedantic)


def check_patch(rec, d, blob, info, out):
    va = _hexint(d.get("patch_va"))
    if d.get("patch_sig"):
        check_sig_field(rec, blob, info, "patch_sig", d["patch_sig"], va, out, out.pedantic)
    if not d.get("patch_bytes"):
        out.warn(rec, "patch artifact has no patch_bytes - gamedata generation "
                      "reports patch_yaml_missing_or_invalid for it")


CHECKS = {
    "func": check_func,
    "gv": check_gv,
    "vfunc": check_vfunc,
    "vtable": check_vtable,
    "structmember": check_structmember,
    "patch": check_patch,
}


# ---------------------------------------------------------------------------
# driver
# ---------------------------------------------------------------------------

def _hexint(v):
    if v is None:
        return None
    try:
        return int(str(v), 16)
    except ValueError:
        return None


def category_of(d):
    if "vtable_class" in d:
        return "vtable"
    if "gv_name" in d or "gv_sig" in d:
        return "gv"
    if "patch_name" in d or "patch_sig" in d or "patch_bytes" in d:
        return "patch"
    if "struct_name" in d and "member_name" in d:
        return "structmember"
    if "vtable_name" in d or any(k.startswith("vfunc_") for k in d):
        return "vfunc"
    if "func_name" in d:
        return "func"
    return None


class Report:
    def __init__(self, pedantic=False):
        self.rows = []
        self.pedantic = pedantic

    def _add(self, rec, severity, message):
        self.rows.append({"severity": severity, "artifact": rec["path"],
                          "module": rec["module"], "platform": rec["platform"],
                          "symbol": rec["symbol"], "category": rec["category"],
                          "message": message})

    def error(self, rec, message):
        self._add(rec, "error", message)

    def warn(self, rec, message):
        self._add(rec, "warning", message)

    @property
    def errors(self):
        return [r for r in self.rows if r["severity"] == "error"]

    @property
    def warnings(self):
        return [r for r in self.rows if r["severity"] == "warning"]


def cross_platform_vfunc_check(artifacts, out):
    """A vtable slot index must agree between modules on the SAME platform.

    The same C++ interface has one layout per build, so two modules disagreeing
    about a slot means one of them was copied from somewhere it did not belong.
    Across platforms it may legitimately differ (MSVC deleting-dtor pairs), so
    that comparison is deliberately not made.
    """
    seen = defaultdict(dict)
    for rec, d in artifacts:
        if rec["category"] != "vfunc":
            continue
        vt, idx = d.get("vtable_name"), d.get("vfunc_index")
        if not vt or idx is None:
            continue
        key = (vt, rec["symbol"], rec["platform"])
        seen[key][rec["module"]] = (int(idx), d.get("func_va"), d.get("func_size"))
    for (vt, sym, plat), by_mod in seen.items():
        idxs = {m: v[0] for m, v in by_mod.items()}
        if len(set(idxs.values())) == 1:
            continue
        # Two modules can legitimately disagree: client and server compile
        # different definitions of some classes (CSkeletonInstance differs by one
        # slot on both platforms across every gamever, with different func_size).
        # A disagreement is only provably wrong when a side has no address of its
        # own, i.e. the index was copied from a module it did not belong to.
        copied = [m for m, v in by_mod.items() if not v[1]]
        sizes = {m: v[2] for m, v in by_mod.items()}
        severity = "error" if copied else "warning"
        detail = (f" - {copied} carries no address of its own, so its index was copied"
                  if copied else
                  f" - both analysed independently (func_size {sizes}), so the classes"
                  f" may genuinely differ; confirm before copying either way")
        out.rows.append({
            "severity": severity, "artifact": "-", "module": ",".join(sorted(by_mod)),
            "platform": plat, "symbol": sym, "category": "vfunc",
            "message": f"{vt} slot for {sym} disagrees between modules on {plat}: "
                       f"{idxs}{detail}",
        })


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-gamever", required=True)
    ap.add_argument("-module", help="only this module")
    ap.add_argument("-platform", choices=("linux", "windows"), help="only this platform")
    ap.add_argument("-artifactdir", default="bin_artifacts")
    ap.add_argument("-bindir", default="bin", help="root holding <gamever>/<module>/<binary>")
    ap.add_argument("-strict", action="store_true", help="exit non-zero on warnings too")
    ap.add_argument("-json", action="store_true", dest="as_json")
    ap.add_argument("-quiet", action="store_true", help="only print the summary")
    ap.add_argument("-pedantic", action="store_true",
                    help="also report signature style: under the 24-byte floor, literal "
                         "branch displacements, unresolved vtable slots. Upstream ships "
                         "over a thousand of these, so they are off by default.")
    args = ap.parse_args()

    root = os.path.join(args.artifactdir, args.gamever)
    if not os.path.isdir(root):
        print(f"no artifacts at {root}", file=sys.stderr)
        return 2

    cache = {}

    def binary_for(module, platform):
        key = (module, platform)
        if key in cache:
            return cache[key]
        names = BIN_LINUX if platform == "linux" else BIN_WIN
        name = names.get(module)
        path = os.path.join(args.bindir, args.gamever, module, name) if name else None
        if not path or not os.path.exists(path):
            cache[key] = (None, None, path)
        else:
            blob, info = load_binary(path)
            cache[key] = (blob, info, path)
        return cache[key]

    out = Report(pedantic=args.pedantic)
    artifacts = []
    skipped_no_binary = set()
    n = 0

    for path in sorted(glob.glob(os.path.join(root, "*", "*.yaml"))):
        module = os.path.basename(os.path.dirname(path))
        base = os.path.basename(path)
        if base.count(".") < 2:
            continue
        symbol, platform, _ext = base.rsplit(".", 2)
        if platform not in ("linux", "windows"):
            continue
        if args.module and module != args.module:
            continue
        if args.platform and platform != args.platform:
            continue

        try:
            with open(path, "r", encoding="utf-8") as f:
                d = yaml.safe_load(f)
        except Exception as exc:
            out.rows.append({"severity": "error", "artifact": path, "module": module,
                             "platform": platform, "symbol": symbol, "category": "?",
                             "message": f"YAML does not parse: {exc}"})
            continue
        if not isinstance(d, dict):
            continue

        category = category_of(d)
        rec = {"path": path, "module": module, "platform": platform,
               "symbol": symbol, "category": category or "?", "binary": None,
               "va": None}
        if category is None:
            out.error(rec, "cannot tell which category this artifact is")
            continue

        # the schema gate is the definition of a well-formed artifact
        try:
            canonical_symbol_yaml_bytes(d, category=category)
        except Exception as exc:
            out.error(rec, f"rejected by the schema gate: {exc}")
            continue

        blob, info, binpath = binary_for(module, platform)
        artifacts.append((rec, d))
        n += 1
        if blob is None:
            skipped_no_binary.add(f"{module}/{platform}")
            continue
        rec["binary"] = os.path.basename(binpath)

        for va_field in ("func_va", "gv_sig_va", "patch_va", "vtable_va"):
            if d.get(va_field) is not None:
                rec["va"] = _hexint(d[va_field])
                break

        CHECKS[category](rec, d, blob, info, out)

    cross_platform_vfunc_check(artifacts, out)

    if args.as_json:
        print(json.dumps({"gamever": args.gamever, "artifacts": n,
                          "errors": out.errors, "warnings": out.warnings}, indent=2))
    else:
        if not args.quiet:
            for row in out.errors + out.warnings:
                tag = "ERROR  " if row["severity"] == "error" else "warning"
                print(f"{tag} {row['module']}/{row['symbol']}.{row['platform']} "
                      f"[{row['category']}]: {row['message']}")
        if skipped_no_binary:
            print(f"\nno binary present for: {', '.join(sorted(skipped_no_binary))} "
                  f"(hydrate bin/ from bin_artifacts/ or download the depot)")
        print(f"\n{n} artifacts checked: {len(out.errors)} errors, {len(out.warnings)} warnings")

    if out.errors:
        return 1
    if args.strict and out.warnings:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
