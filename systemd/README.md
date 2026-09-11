# Autopilot on the analysis box

`autopilot.sh` asks Steam whether there is a new CS2 build and, if there is,
takes it through the whole pipeline: register the tag, re-assert this fork's
config decisions, analyse both platforms, run the verification battery as a
gate, generate gamedata, commit and push. Whether it also deploys to the plugin
repos is decided by `autopilot_safe_gate.py`.

Nothing listens on a port. The box asks; nobody tells it. That is deliberate:
this machine holds the Steam credentials and the IDA licence, and
`mrc4tt/CS2_VibeSignatures` is a public repository, so a self-hosted GitHub
runner here would let anyone's pull request execute code on it.

## Install

    sudo cp systemd/cs2vibe-autopilot.service systemd/cs2vibe-autopilot.timer /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable --now cs2vibe-autopilot.timer

## Operate

    systemctl list-timers cs2vibe-autopilot.timer     # when does it next look
    journalctl -u cs2vibe-autopilot -f                # what is it doing
    sudo systemctl start cs2vibe-autopilot.service    # look right now
    sudo systemctl stop cs2vibe-autopilot.timer       # the whole emergency brake

    ./autopilot.sh -n                                 # what would it do
    ./autopilot.sh 14182                              # force one tag

## Settings, in `.env`

    AUTOPILOT_DEPLOY=safe        # safe (default) | auto | off
    AUTOPILOT_NOTIFY_URL=        # ntfy topic or Discord webhook, outgoing only
    AUTOPILOT_MIN_FREE_GB=40     # refuse to start a depot download below this
    AUTOPILOT_MAX_ATTEMPTS=2     # then stop retrying that build

`safe` deploys only when the build is a rebuild relocation and nothing more:
no key appeared or disappeared, no offset or vtable slot moved, coverage did not
drop, and no symbol lost a platform. Measured over the 15 build transitions on
this box, that holds 12 and deploys 3, so expect to approve most builds by hand.
The held ones are held for a reason worth seeing: CS2Fixes lost six keys in
14175, eighteen symbols lost a platform in 14180, three offsets moved in 14181.

## State

`.autopilot/` holds the lock, the per-build attempt counter, and the last
generation log, gate verdict and missing report. It is gitignored. Deleting
`.autopilot/attempts-<build>` lets a failed build be tried again.

## What stops the chain

Any of these ends the run before a file reaches a plugin repo: uncommitted
changes in the working tree, less than `AUTOPILOT_MIN_FREE_GB` free, a missing
DepotDownloader or agent CLI, a non-zero exit from either analysis script, a
snapshot that disagrees with the config, a gamedata warning diagnostic, a
validator error, or a duplicate-VA cluster.
