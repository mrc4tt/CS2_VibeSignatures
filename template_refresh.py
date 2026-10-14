#!/usr/bin/env python3
"""
Between game builds: follow the plugins' own gamedata files and republish the newest build.

autopilot only works when Valve ships a build, but a plugin moves on in between - it adds
a key, renames one, its author fixes a value. This runs on the autopilot tick that finds
no new build, at most every -every hours. When sync_plugin_templates.py changes a
template it regenerates the newest build's gamedata, holds every shipped file to the same
verified gate as a build (verify_plugin_gamedata -require-verified), and only then
commits and pushes the templates and the regenerated files, so the site and anyone
fetching the files get the plugin's current keys without waiting for the next CS2 update.
When the gate fails the change is rolled back and nothing is committed.

  uv run template_refresh.py -gamever 14190            # respects -every
  uv run template_refresh.py -gamever 14190 -force     # now

Exit 0 nothing to do or published, 1 held back (gate failed), 2 a step failed.
"""

import argparse
import os
import subprocess
import sys
import time

STATE = ".autopilot"


def run(cmd, **kwargs):
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


def notify(outcome, tag, text):
    if os.access("./autopilot_notify.sh", os.X_OK):
        run(["./autopilot_notify.sh", outcome, tag, text])


def changed_paths(paths):
    done = run(["git", "status", "--porcelain", "--"] + paths)
    return [line[3:] for line in done.stdout.splitlines() if line.strip()]


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("-gamever", required=True)
    parser.add_argument("-every", type=float, default=6.0, help="hours between checks (default 6)")
    parser.add_argument("-force", action="store_true")
    parser.add_argument("-no-push", dest="push", action="store_false")
    args = parser.parse_args()
    tag = args.gamever

    os.makedirs(STATE, exist_ok=True)
    marker = os.path.join(STATE, f"template-refresh-{tag}")
    if not args.force and os.path.exists(marker) and time.time() - os.path.getmtime(marker) < args.every * 3600:
        return 0
    open(marker, "w").close()

    sync = run([sys.executable, "sync_plugin_templates.py", "-gamever", tag, "-apply"])
    with open(os.path.join(STATE, f"templates-{tag}.txt"), "w", encoding="utf-8") as handle:
        handle.write(sync.stdout + sync.stderr)
    templates = changed_paths(["gamedata-generators"])
    if not templates:
        print(f"template_refresh {tag}: plugin files unchanged")
        return 0

    gamedata = os.path.join("gamedata", tag)
    snapshot = os.path.join("gamesymbols", f"{tag}.yaml")
    gen = run([sys.executable, "update_gamedata.py", "-gamever", tag, "-snapshot", snapshot, "-outputdir", gamedata])
    if gen.returncode != 0 or "Unique warning diagnostics: 0" not in gen.stdout:
        run(["git", "checkout", "--", "gamedata-generators", gamedata])
        notify("failed", tag, "plugin template refresh: gamedata generation failed; templates left as they were")
        return 2

    import publish_site_data
    disabled = publish_site_data.disabled_plugins()
    unhealthy = []
    for base, _dirs, names in os.walk(gamedata):
        for name in names:
            path = os.path.join(base, name)
            if not name.endswith((".json", ".jsonc", ".txt")) or name.endswith(".metadata.json"):
                continue
            if os.path.relpath(path, gamedata).split(os.sep)[0] in disabled:
                continue
            check = run([sys.executable, "verify_plugin_gamedata.py", "-gamever", tag, "-gamedata", path,
                         "-require-verified"])
            if check.returncode != 0:
                unhealthy.append(os.path.relpath(path, gamedata))
    if unhealthy:
        run(["git", "checkout", "--", "gamedata-generators", gamedata])
        notify("held", tag, "plugin template refresh held back - the regenerated files do not verify: "
               + ", ".join(unhealthy) + f"\nsee {STATE}/templates-{tag}.txt")
        print(f"template_refresh {tag}: held back, unhealthy: {', '.join(unhealthy)}")
        return 1

    run([sys.executable, "publish_site_data.py", "-skip-validator"])
    paths = ["gamedata-generators", gamedata, os.path.join("gamedata", "history.json"),
             os.path.join("diagnostics", f"{tag}.json")]
    run(["git", "add", "-A", "--"] + paths)
    summary = [line for line in sync.stdout.splitlines() if line.startswith(("[", "  +", "  -", "  !"))]
    message = (f"chore({tag}): follow the plugins' gamedata files\n\n"
               "sync_plugin_templates.py refreshed the templates from the plugins' own files, and\n"
               "the regenerated gamedata passed the verified gate.\n\n" + "\n".join(summary[:40]))
    commit = run(["git", "commit", "-q", "-m", message])
    if commit.returncode != 0:
        print(f"template_refresh {tag}: nothing to commit")
        return 0
    if args.push:
        pushed = run(["git", "push", "-q", "origin", "HEAD"])
        if pushed.returncode != 0:
            notify("failed", tag, f"plugin template refresh committed but not pushed: {pushed.stderr[-200:]}")
            return 2
    notify("deployed", tag, "plugin templates followed and republished:\n" + "\n".join(summary[:14]))
    print(f"template_refresh {tag}: published ({len(templates)} template(s) changed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
