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

The editor's IDA session is a second, independent unit:

    sudo cp systemd/cs2vibe-ida-session.service /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable --now cs2vibe-ida-session.service

It runs `ida_session.py`, which starts `idalib-mcp` on 127.0.0.1:13337 (where
`.mcp.json` points) with the newest `bin/<VER>/server/libserver.so` that already
has a `.i64`. Other binaries are opened on demand through the supervisor's
`idalib_open` tool, one worker each. `run_linux.sh`, `run_windows.sh` and
`gen_references.sh` stop it for the length of a run and start it again on exit,
so it never holds a database a run needs, and each restart moves it to the build
that run produced. `MemoryMax=16G` keeps it from competing with a run.

    journalctl -u cs2vibe-ida-session -f              # what is it doing
    uv run python ida_session.py -print               # which binary it opens

## Operate

    systemctl list-timers cs2vibe-autopilot.timer     # when does it next look
    journalctl -u cs2vibe-autopilot -f                # what is it doing
    sudo systemctl start cs2vibe-autopilot.service    # look right now
    sudo systemctl stop cs2vibe-autopilot.timer       # the whole emergency brake

    ./autopilot.sh -n                                 # what would it do
    ./autopilot.sh 14182                              # force one tag

## Settings, in `.env`

    AUTOPILOT_DEPLOY=safe        # safe (default) | verified | auto | off
    AUTOPILOT_NOTIFY_URL=        # ntfy topic or Discord webhook, outgoing only
    AUTOPILOT_MIN_FREE_GB=40     # refuse to start a depot download below this
    AUTOPILOT_MAX_ATTEMPTS=2     # then stop retrying that build
    AUTOPILOT_IMPACT_PLUGINS=    # plugin dirs (a:b) for the schema impact line in the notification

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

A build the chain committed but did not finish (push or deploy failed) is not
"done": the next tick resumes it at the push - `git pull --rebase --autostash`,
three tries - and then the deploy decision, without re-running the analysis.
`.autopilot/finish-attempts-<build>` caps that at `AUTOPILOT_MAX_FINISH_ATTEMPTS`
(default 6); `.autopilot/finished-<build>` marks a build that reached the end.

## What stops the chain

Any of these ends the run before a file reaches a plugin repo: uncommitted
changes in the working tree, less than `AUTOPILOT_MIN_FREE_GB` free, a missing
DepotDownloader or agent CLI, a non-zero exit from either analysis script, a
snapshot that disagrees with the config, a gamedata warning diagnostic, a
validator error, or a duplicate-VA cluster.
