# CS2_VibeSignatures Discord bot

Posts each build to `#gamedata-updates` and answers slash commands from the data
the pipeline already wrote. It only reads the repository (`gamedata/history.json`,
`diagnostics/<build>.json`, `gamedata/<build>/**/*.metadata.json`); the one file it
writes is `bot/state.json` (which message belongs to which build).

## What it does

- **One message per build**, edited as autopilot reports each stage
  (`started`, `linux-*`, `deployed` / `held` / `analysed` / `failed`), with a timeline
  and how long the run took.
- **A thread under it** with the per-plugin answer, one line per file: which changed
  against the previous build (and how many keys), verification, and the files that
  need nothing. `/changes file:` lists one file's keys. Changes come from
  `gamedata/history.json`, not the generator's `*.metadata.json`, whose "before" is the
  plugin's template rather than the previous build.
- **Gamedata files as attachments** on the build message (so followers of the channel
  get them too), chosen by an admin with `/settings`: which files (max 10, Discord's
  limit) and whether only the ones the build changed or all of them. Saved to
  `bot/settings.json` and read on every build - no restart, no `.env` edit.
  "Apply now" re-attaches to the newest build's message.
- **Announcement channel**: when `#gamedata-updates` is one, each build message is
  published, so other servers can follow the channel.
- **Failures** go in full (hint commands, log paths) to `DISCORD_ADMIN_CHANNEL_ID` only;
  the public message just says the previous gamedata stays in place.

## Not spamming

Each rule is covered by `test/announce.test.ts` against a fake Discord.

- **One public message per build.** Every stage edits it; edits notify nobody. A retry
  of a failed run continues the same message; only a re-run more than 6 h after the
  last event gets a new one.
- **`started` is posted silently** (`@silent`): nobody's phone buzzes for a run that
  may end in "nothing changed". The finished state arrives as an edit.
- **One summary per build** in its thread, edited when windows follows linux.
- **Refusals stay private.** A failure while no run of that build is open (low disk,
  dirty tree - repeated on every 5-minute timer tick), `sdk-abi`, and any other
  outcome that is not a build stage go to the admin channel only.
- **A repeated failure edits one admin message** with a counter ("seen 6x since ...")
  for 12 h instead of posting again.
- **Command answers are visible to the asker only** unless `share:true`, and never
  public in the updates channel. 3 s cooldown per user.
- **No mentions.** `allowedMentions` is empty, so no relayed text can ping anyone.

## Status line

Under its name the bot shows `Gamedata for CS2 <newest build> · /help`, or
`Analysing CS2 <build>…` while a run is open. It follows each autopilot event at once
and re-reads the repository every 5 minutes.

## Commands

| Command | |
|---|---|
| `/help` | every command (built from the definitions, so it never goes stale) |
| `/status` | newest build, running autopilot, shipped files' health |
| `/changes [build] [file]` | which plugins need a new file, or one file's changed keys |
| `/gamedata file [build]` | the generated file as an attachment |
| `/key key` | current linux/windows value and the builds it changed in |

| `/settings` | admins (Manage Server) only: files attached to build messages |

Every command except `/settings` takes `share:true` to post the answer for everyone.

## Setup

1. Discord developer portal: new application, add a bot, copy the token. No privileged
   intents are needed. Invite it with the `bot` and `applications.commands` scopes and
   the permissions *Send Messages*, *Embed Links*, *Attach Files*,
   *Create Public Threads*, *Send Messages in Threads* and (announcement channel)
   *Manage Messages* for publishing.
2. `cp .env.example .env` and fill it in.
3. `npm install && npm run register` (again whenever a command definition changes).
4. Add to the repository's `.env` (the one `cs2vibe-autopilot.service` reads):
   ```
   AUTOPILOT_BOT_URL=http://127.0.0.1:13410/event
   AUTOPILOT_BOT_SECRET=<same as BOT_EVENT_SECRET>
   ```
   `AUTOPILOT_NOTIFY_URL` can stay as a fallback or be removed.
5. Run it:
   ```bash
   sudo cp ../systemd/cs2vibe-discord-bot.service /etc/systemd/system/
   sudo systemctl daemon-reload && sudo systemctl enable --now cs2vibe-discord-bot.service
   journalctl -u cs2vibe-discord-bot -f
   ```

Test an event by hand (no autopilot run needed):

```bash
AUTOPILOT_NOTIFY_URL= AUTOPILOT_BOT_URL=http://127.0.0.1:13410/event \
AUTOPILOT_BOT_SECRET=<secret> ../autopilot_notify.sh deployed 14192 "took 0h 1m"
```

## Development

Node 24 runs the TypeScript directly (type stripping), so there is no build step.
`npm run typecheck` and `npm test`; the tests render every embed against the
repository's real data and check it against Discord's size limits.
