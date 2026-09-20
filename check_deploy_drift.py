#!/usr/bin/env python3
"""Compare the generated gamedata under gamedata/<gamever>/ with what is actually deployed.

verify_plugin_gamedata.py answers "is every entry in the deployed file still correct against
the binary". It cannot answer "is the deployed file the one this repo generated", because a
stale value that still resolves uniquely is healthy by that test and says nothing about its
own age. That gap is real: the CCSCustomHudLayout win64 signatures sat in the
CounterStrikeSharp install for a full generation after they were regenerated here. Both old
and new resolved to the same address, so every check in the battery passed, while the
deployed pattern still pinned a relative call displacement that the next build would move.

Deployment is a separate step from generation, and two different scripts perform it:

  deploy_local_plugins.sh   copies the file  -> the deployed file must match byte for byte
                            (modulo a trailing newline, which plugin web editors strip)
  update_css_gamedata.sh    MERGES by key    -> install-only keys are kept on purpose, so
                            only the keys this repo generates are compared

Both mappings are declared in those scripts; DEPLOY_TARGETS below mirrors them, and
tests/test_deploy_targets.py asserts the two stay in step wherever the scripts are present
(they are git-ignored local files, so that half of the test skips on a fresh clone).

  uv run check_deploy_drift.py                # the newest generated build
  uv run check_deploy_drift.py -gamever 14181

Only one build is ever deployed, so drift is only a defect for the newest generated build.
Asking about an older one still prints the comparison, but reports it rather than failing,
because gamedata/14180/ differing from an install that holds 14181 is the correct state.

Exit code 1 when anything has drifted, so it can gate a deploy.
"""

import argparse
import json
import os
import re
import sys

from gamedata_utils import strip_jsonc_comments

# (plugin directory under gamedata/<gamever>/, path within it, deployed path, compare mode).
# The deployed path may name an environment variable for its root, matching the deploy script.
DEPLOY_TARGETS = (
    {
        "plugin": "CounterStrikeSharp",
        "dist": "config/addons/counterstrikesharp/gamedata/gamedata.json",
        "root_env": "CSS_INSTALL",
        "root_default": "~/CounterStrikeSharp",
        "install": "configs/addons/counterstrikesharp/gamedata/gamedata.json",
        "mode": "merge",
        "deployed_by": "update_css_gamedata.sh",
    },
    {
        "plugin": "weaponpaints",
        "dist": "gamedata/weaponpaints.json",
        "root_env": "CUSTOMGIT_ROOT",
        "root_default": "~/customGIT",
        "install": "weaponpaints/gamedata/weaponpaints.json",
        "mode": "copy",
        "deployed_by": "deploy_local_plugins.sh",
    },
    {
        "plugin": "matchzy",
        "dist": "gamedata/matchzy.json",
        "root_env": "CUSTOMGIT_ROOT",
        "root_default": "~/customGIT",
        "install": "matchzy/gamedata/matchzy.json",
        "mode": "copy",
        "deployed_by": "deploy_local_plugins.sh",
    },
)


def _generated_builds():
    """Build tags under gamedata/, oldest first - same shape deploy_local_plugins.sh picks from."""
    root = "gamedata"
    if not os.path.isdir(root):
        return []
    tags = [name for name in os.listdir(root)
            if os.path.isdir(os.path.join(root, name)) and re.fullmatch(r"[0-9]+[a-z]?", name)]
    return sorted(tags, key=lambda tag: (int(re.match(r"[0-9]+", tag).group()), tag))


def _root(target):
    return os.path.expanduser(os.environ.get(target["root_env"]) or target["root_default"])


def _load(path):
    with open(path, encoding="utf-8") as handle:
        return json.loads(strip_jsonc_comments(handle.read()))


def _leaves(node, trail=()):
    """Flatten a gamedata document to {dotted key: value}, so a diff names the exact field."""
    if isinstance(node, dict):
        out = {}
        for key, value in node.items():
            out.update(_leaves(value, trail + (str(key),)))
        return out
    return {".".join(trail): node}


def _compare(target, dist_path, install_path):
    """Returns (status, [detail lines])."""
    if target["mode"] == "copy":
        # Byte-exact except for a missing final newline, which is what the deploy script
        # forgives and nothing else.
        with open(dist_path, "rb") as handle:
            dist = handle.read()
        with open(install_path, "rb") as handle:
            installed = handle.read()
        if dist.rstrip(b"\n") == installed.rstrip(b"\n"):
            return "in sync", []
        # Still report by key, because "the bytes differ" is not actionable on its own.
        try:
            details = _diff_keys(_load(dist_path), _load(install_path), generated_only=False)
        except (OSError, ValueError) as error:
            return "DRIFT", [f"contents differ and could not be parsed to say where: {error}"]
        return "DRIFT", details or ["contents differ outside any value (formatting only)"]

    details = _diff_keys(_load(dist_path), _load(install_path), generated_only=True)
    return ("DRIFT", details) if details else ("in sync", [])


def _diff_keys(dist, installed, generated_only):
    dist_leaves = _leaves(dist)
    install_leaves = _leaves(installed)

    details = []
    for key, value in sorted(dist_leaves.items()):
        if key not in install_leaves:
            details.append(f"{key}: missing from the deployed file")
        elif install_leaves[key] != value:
            details.append(f"{key}:\n      generated {value!r}\n      deployed  {install_leaves[key]!r}")

    if not generated_only:
        for key in sorted(set(install_leaves) - set(dist_leaves)):
            details.append(f"{key}: present only in the deployed file")

    return details


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-gamever", default=None, help="default: the newest build under gamedata/")
    parser.add_argument("-outputdir", default=None, help="default: gamedata/<gamever>")
    parser.add_argument("-strict", action="store_true",
                        help="treat a deploy target that is not present on this machine as a failure")
    parser.add_argument("-quiet", action="store_true", help="only print what has drifted")
    args = parser.parse_args()

    builds = _generated_builds()
    gamever = args.gamever or (builds[-1] if builds else None)
    if gamever is None:
        print("no generated gamedata under gamedata/", file=sys.stderr)
        return 2

    out_root = args.outputdir or os.path.join("gamedata", gamever)
    if not os.path.isdir(out_root):
        print(f"no generated gamedata at {out_root}", file=sys.stderr)
        return 2

    # The plugins hold exactly one build. Comparing an older one against them is a valid
    # question - "what changed since 14180" - but it is not a defect, so it must not gate.
    is_current = not builds or gamever == builds[-1]
    if not is_current:
        print(f"note: {gamever} is not the newest generated build ({builds[-1]}); "
              f"the deployed files track the newest, so differences below are expected")

    try:
        from publish_site_data import disabled_plugins
        disabled = disabled_plugins()
    except Exception:  # noqa: BLE001 - the check must not fail over the disabled list
        disabled = set()

    drifted = 0
    skipped = 0

    for target in DEPLOY_TARGETS:
        plugin = target["plugin"]
        label = f"{plugin:22s}"

        if plugin in disabled:
            if not args.quiet:
                print(f"  {label} skipped: generator disabled in this fork")
            continue

        dist_path = os.path.join(out_root, plugin, target["dist"])
        install_path = os.path.join(_root(target), target["install"])

        if not os.path.isfile(dist_path):
            skipped += 1
            print(f"  {label} no generated file at {dist_path}")
            continue

        if not os.path.isfile(install_path):
            skipped += 1
            print(f"  {label} not deployed on this machine ({install_path})")
            continue

        try:
            status, details = _compare(target, dist_path, install_path)
        except (OSError, ValueError) as error:
            drifted += 1
            print(f"  {label} UNREADABLE: {error}")
            continue

        if status == "in sync":
            if not args.quiet:
                print(f"  {label} = in sync ({target['mode']}) {install_path}")
            continue

        drifted += 1
        print(f"  {label} DRIFT vs {install_path}")
        print(f"  {'':22s}   deployed by {target['deployed_by']}; {len(details)} difference(s)")
        for detail in details:
            print(f"      {detail}")

    if drifted:
        if not is_current and not args.strict:
            print(f"\n{drifted} target(s) differ from {gamever}, which is not the deployed build - not a failure")
            return 0
        print(f"\ndeploy drift: {drifted} target(s) behind the generated gamedata")
        return 1

    if skipped and args.strict:
        print(f"\n{skipped} deploy target(s) unavailable and -strict was given")
        return 1

    print(f"\ndeploy drift: none ({skipped} target(s) not present here)" if skipped else "\ndeploy drift: none")
    return 0


if __name__ == "__main__":
    sys.exit(main())
