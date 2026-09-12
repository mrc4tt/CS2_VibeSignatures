# Self-hosted runner for this repository

A self-hosted runner costs no Actions minutes on any plan — GitHub bills only its
own hosted runners. What it costs is a machine that executes whatever a workflow
in this repository says. This repo is **public**, so that is worth setting up
deliberately rather than quickly.

## Why a pull request cannot reach the runner here

Three separate fences, and the first two are in the repository:

1. **No `pull_request` trigger.** `publish-nginx.yml` runs on `push` to `main`
   and on `workflow_dispatch`. A fork PR fires neither, so there is no path from
   an outside PR to the runner. Keep it that way: adding `pull_request` — and
   above all `pull_request_target`, which runs with this repo's secrets — is what
   turns a self-hosted runner into someone else's compute.
2. **A repository guard on the job.** `if: github.repository == 'mrc4tt/CS2_VibeSignatures'`
   refuses to run in a fork that inherited the workflow file.
3. **A GitHub setting** that has to be changed by hand, because it is not in any
   file. Settings → Actions → General → *Fork pull request workflows from
   outside collaborators*: move it from the default **Require approval for
   first-time contributors** to **Require approval for all outside
   collaborators**. The default would let a contributor who has landed one PR
   run a workflow unapproved.

While that setting is in the repository's own configuration rather than in git,
it can be set from the CLI:

```bash
gh api -X PUT repos/mrc4tt/CS2_VibeSignatures/actions/permissions/workflow \
  -f default_workflow_permissions=read \
  -F can_approve_pull_request_reviews=false
gh api -X PUT repos/mrc4tt/CS2_VibeSignatures/actions/permissions/fork-pr-contributor-approval \
  -f approval_policy=all_external_contributors
```

## What else actually protects the box

A PR is not the only way code reaches a runner. Anyone with write access, and
every third-party action a workflow uses, runs on it too.

- **Allowlist the actions.** Settings → Actions → General → *Allow select
  actions*, with "actions created by GitHub" plus anything you pin explicitly.
  `publish-nginx.yml` uses exactly one third-party-shaped action
  (`actions/checkout`) and no `setup-*`, because the box has its own toolchain.
- **A dedicated unprivileged user.** The runner user needs write access to the
  nginx root (`/srv/sig`) and nothing else. Not your login, no sudo, no access to
  `~/CS2_VibeSignatures`, no Steam or LLM credentials — the runner checks out its
  own copy and needs none of that.
- **`--once` or `--ephemeral`.** A job that leaves something behind in the work
  directory cannot affect the next one. A single box does this with a loop that
  registers with a fresh token and runs one job:

  ```bash
  while :; do
    token=$(gh api -X POST repos/mrc4tt/CS2_VibeSignatures/actions/runners/registration-token -q .token)
    ./config.sh --unattended --replace --url https://github.com/mrc4tt/CS2_VibeSignatures \
      --token "$token" --labels self-hosted,linux,X64,cs2vibe --name cs2vibe-$(hostname)
    ./run.sh --once
  done
  ```

  A persistent runner (`./svc.sh install <user>`) is simpler and acceptable while
  the triggers stay as narrow as they are; the loop above is what removes the
  "state survives between jobs" problem.
- **No secrets it does not need.** This workflow reads none. Do not add repo
  secrets that only the Pages job needs.

## Turning it on

The workflow ships **disabled**, and that is deliberate: a job-level `if` skips
the job but GitHub still creates the run, so with no runner registered every push
touching `pages/` left a queued run and a pending check that never resolved. Two
of those had to be cancelled by hand before the workflow was disabled.

So enabling it takes three steps, not one:

```bash
gh workflow enable publish-nginx.yml               # the run is created at all
gh variable set PUBLISH_NGINX --body true          # the job is allowed to run
# and a runner registered with the cs2vibe label, or it queues again
```

To stand it down again: `gh workflow disable publish-nginx.yml`. Removing the
variable alone still leaves skipped runs in the history.

## Labels

The job asks for `[self-hosted, linux, X64, cs2vibe]`. Register with
`--labels self-hosted,linux,X64,cs2vibe` or the job will queue for ever.

## The nginx side

`docs/nginx-sig.miksen.me.conf` serves `/srv/sig/current`, a symlink the
publisher flips only after the build and both asset verifiers pass. Create the
tree once, owned by the runner user:

```bash
sudo mkdir -p /srv/sig/releases
sudo chown -R <runner-user> /srv/sig
```

Rollback is one command, no rebuild:

```bash
ln -sfn /srv/sig/releases/<older-stamp> /srv/sig/current.new
mv -T /srv/sig/current.new /srv/sig/current
```

## Runner or autopilot — pick one publisher

`autopilot.sh` can do the same job with no GitHub involvement at all:
`AUTOPILOT_PUBLISH=nginx` plus `AUTOPILOT_PUBLISH_TARGET=/srv/sig` builds,
verifies and flips the symlink at the end of the pipeline run. It is the same
release layout, so the two are interchangeable — but running both means two
publishers racing for one symlink, so enable whichever one you want and leave
the other at its default (`AUTOPILOT_PUBLISH=off`, or this workflow disabled).

The runner earns its keep if you want GitHub to hold the logs, show a status
check and offer a manual dispatch. Autopilot earns its keep by needing nothing
inbound at all.

## While the DNS still points at GitHub Pages

`deploy-pages.yml` is untouched and keeps publishing. Both can run: they write
to different places, and nothing breaks until `sig.miksen.me` is pointed at
nginx. When it is, either keep Pages as a warm standby or delete the workflow —
but do not forget that its `check-datasets` job is what currently fails a stale
`gamedata/history.json`. The nginx path runs `publish_site_data.py -check` for
the same reason.
