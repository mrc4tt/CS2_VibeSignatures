"""Record which commit of each plugin repo now carries a build's deployed gamedata.

check_deploy_drift.py proves the deployed files match what was generated. This writes
down where they now live, as deployments/<gamever>.json, which the site serves next to
latest.json. A consumer that installs gamedata on live servers (the fshost panel's plugin
manager) reads it to fetch exactly the file that belongs to a CS2 build.

Commit messages cannot answer that question: a build whose gamedata did not change gets
no commit of its own (14187-14189 had none in CounterStrikeSharp), and the file valid for
it is just the newest one on the path. So the record names that commit explicitly.

The record also separates "analysed" from "deployed". The safe gate can hold a build:
analysed, committed and on the site, but not in any plugin repo. Without a record the
build reads as analysed only, which is the truth.

  uv run record_deploy.py -gamever 14189     # writes deployments/14189.json
  uv run record_deploy.py                    # the newest generated build

Run it after the drift check, so a record always means "deployed and verified in place".
Exits 1 when a target is missing, outside git, or not pushed: the record is still written,
with status "partial", so the gap is visible rather than silent.
"""

import argparse
import datetime
import json
import os
import re
import subprocess
import sys

import check_deploy_drift

SCHEMA_VERSION = 1
RECORD_DIRECTORY = "deployments"


def _git(cwd, *args):
    completed = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True)
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


def web_url(remote):
    """`git@github.com:owner/repo.git` and its https/ssh spellings -> https://host/owner/repo."""
    url = remote.strip()
    match = re.fullmatch(r"(?:ssh://)?[^@/\s]+@([^:/\s]+)[:/](.+?)(?:\.git)?/?", url)
    if match:
        return f"https://{match.group(1)}/{match.group(2)}"
    match = re.fullmatch(r"https?://(?:[^@/\s]+@)?([^/\s]+)/(.+?)(?:\.git)?/?", url)
    if match:
        return f"https://{match.group(1)}/{match.group(2)}"
    return url


def describe_target(target):
    """Where one target's deployed file lives, and the commit that carries it."""
    deployed = os.path.join(check_deploy_drift._root(target), target["install"])
    if not os.path.isfile(deployed):
        return {"error": f"not deployed on this machine: {deployed}"}

    top = _git(os.path.dirname(deployed), "rev-parse", "--show-toplevel")
    if not top:
        return {"error": f"not inside a git repository: {deployed}"}
    path = os.path.relpath(deployed, top).replace(os.sep, "/")

    if _git(top, "status", "--porcelain", "--", path):
        return {"error": f"uncommitted changes in {path}"}

    commit = _git(top, "log", "-1", "--format=%H", "--", path)
    if not commit:
        return {"error": f"{path} has no commit"}

    remote = _git(top, "remote", "get-url", "origin")
    # Pushed means reachable from the upstream branch as this clone last saw it, which
    # deploy_local_plugins.sh's push has just updated.
    pushed = _git(top, "merge-base", "--is-ancestor", commit, "@{u}") is not None

    return {
        "repo": web_url(remote) if remote else None,
        "path": path,
        "commit": commit,
        "pushed": pushed,
    }


def build_record(gamever, describe=describe_target, now=None):
    targets = {target["plugin"]: describe(target) for target in check_deploy_drift.DEPLOY_TARGETS}
    complete = all("error" not in entry and entry.get("pushed") for entry in targets.values())
    recorded_at = (now or datetime.datetime.now(datetime.timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "schemaVersion": SCHEMA_VERSION,
        "gameVersion": gamever,
        "status": "deployed" if complete else "partial",
        "recordedAt": recorded_at,
        "targets": targets,
    }


def write_record(record, directory=RECORD_DIRECTORY):
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, f"{record['gameVersion']}.json")
    temporary = f"{path}.tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(record, handle, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(temporary, path)
    return path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-gamever", default=None, help="default: the newest build under gamedata/")
    args = parser.parse_args()

    builds = check_deploy_drift._generated_builds()
    gamever = args.gamever or (builds[-1] if builds else None)
    if gamever is None:
        print("no generated gamedata under gamedata/", file=sys.stderr)
        return 2

    record = build_record(gamever)
    path = write_record(record)
    print(f"{record['status']}: {path}")
    for plugin, entry in record["targets"].items():
        if "error" in entry:
            print(f"  ❌ {plugin}: {entry['error']}")
        elif not entry["pushed"]:
            print(f"  ❌ {plugin}: {entry['commit'][:12]} is not pushed to {entry['repo']}")
        else:
            print(f"  ✔ {plugin}: {entry['repo']} @ {entry['commit'][:12]}")
    return 0 if record["status"] == "deployed" else 1


if __name__ == "__main__":
    sys.exit(main())
