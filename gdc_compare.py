#!/usr/bin/env python3
"""Compare gdc's signature verdicts with verify_plugin_gamedata's own scanner.

gdc (tools/gdc) is a second, independent implementation of the signature half of
verify_plugin_gamedata: its own ELF/PE reader, pattern parser and scan, in .NET,
sharing no code with validate_artifacts.py. Where both read the same file the same
way and still disagree about a signature, one of the two scanners is wrong, and
that is worth a look before the verdict is trusted.

Only the binary scan is compared (check_signature with no record): offsets need this
repo's analysis, which gdc does not have, and ok / ok-midfunction / ok-globalref
differ only in what the analysis says about the hit, so all three count as "ok".

  uv run gdc_compare.py -gamever 14192 -gdc .autopilot/gdc-14192.json

Prints a one-line summary, then one line per disagreement. Exit 0 when they agree,
1 when they do not, 2 when the input cannot be read.
"""

import argparse
import json
import sys

import verify_plugin_gamedata as VPG


def verdict(info):
    """-> the comparable part of a status: the class, and where it resolved."""
    status = info.get("status")
    if status in ("ok", "ok-midfunction", "ok-globalref"):
        return "ok", info.get("at")
    return status, None


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("-gamever", required=True)
    parser.add_argument("-gdc", required=True, help="gdc --json output")
    parser.add_argument("-bindir", default="bin")
    args = parser.parse_args()

    try:
        with open(args.gdc, encoding="utf-8") as handle:
            report = json.load(handle)
    except (OSError, ValueError) as error:
        print(f"gdc_compare: cannot read {args.gdc}: {error}")
        return 2

    binaries = VPG.Binaries(args.bindir, args.gamever)
    compared, disagreements = 0, []
    for file in report.get("files", []):
        path = file["file"]
        entries, note = VPG.load_gamedata(path)
        if note or file.get("note"):
            if bool(note) != bool(file.get("note")):
                disagreements.append(f"{path}: reference note {note!r}, gdc note {file.get('note')!r}")
            continue
        for row in file["entries"]:
            entry = entries.get(row["name"])
            if entry is None:
                disagreements.append(f"{path}: {row['name']} read by gdc only")
                continue
            if entry["kind"] != row["kind"] or VPG.LIBRARY_TO_MODULE.get(
                    str(entry.get("library") or "server"), "server") != row["module"]:
                disagreements.append(f"{path}: {row['name']} read differently "
                                     f"(reference {entry['kind']}, gdc {row['kind']}/{row['module']})")
                continue
            if row["kind"] != "signature":
                continue
            for platform, theirs in row["platforms"].items():
                value = entry["values"].get(platform)
                if value in (None, ""):
                    ours = {"status": "not-shipped"}
                else:
                    ours = VPG.check_signature(binaries, row["module"], platform, value)
                    if not entry.get("library") and ours.get("status") == "broken":
                        ours = _other_module(binaries, row["module"], platform, value) or ours
                compared += 1
                if verdict(ours) != verdict(theirs):
                    disagreements.append(f"{path}: {row['name']}.{platform} reference "
                                         f"{_describe(ours)}, gdc {_describe(theirs)}")
        unread = set(entries) - {row["name"] for row in file["entries"]}
        disagreements.extend(f"{path}: {name} read by the reference only" for name in sorted(unread))

    print(f"gdc_compare: {compared} signature values compared, {len(disagreements)} disagreement(s)")
    for line in disagreements:
        print(line)
    return 1 if disagreements else 0


def _other_module(binaries, module, platform, value):
    """A file with no library leaves the module to the plugin (cs2-menus hard-codes
    libengine2 for IsHearingClient): the one other module the pattern resolves in, the
    rule gdc's Scanner.Check applies. None when it resolves in none or in several."""
    names = VPG.BIN_LINUX if platform == "linux" else VPG.BIN_WIN
    found = [(other, info) for other in names if other != module
             for info in [VPG.check_signature(binaries, other, platform, value)]
             if info.get("status") in ("ok", "ok-midfunction")]
    if len(found) != 1:
        return None
    other, info = found[0]
    return dict(info, module=other)


def _describe(info):
    extra = [f"{key}={info[key]}" for key in ("at", "count", "outside_code") if key in info]
    return info.get("status", "?") + (f" ({', '.join(extra)})" if extra else "")


if __name__ == "__main__":
    sys.exit(main())
