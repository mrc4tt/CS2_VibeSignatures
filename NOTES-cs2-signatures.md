# What the tracker side needs to do

Notes for whoever works on `git.miksen.me/mikkel/cs2-signatures`. The analysis
box (`mrc4tt/CS2_VibeSignatures` on the 9950X3D) now runs its own timer and does
not need to be told when a new game build appears: it asks Steam every 15
minutes. So nothing here has to push, and nothing on that box listens. Two
one-directional jobs are all that is left.

## 1. Notice a new build without scraping

The published site exposes a small document for exactly this:

    curl -s https://sig.miksen.me/latest.json

    {
      "schemaVersion": 1,
      "latest": {
        "gameVersion": "14181",
        "lastPublishTime": "2026-09-11T07:57:31Z",
        "configSha256": "sha256:db7361ca…",
        "symbolRecords": 3763,
        "pluginKeys": 904,
        "pluginKeysCovered": 459
      },
      "builds": ["14181", "14180", "14178b", "14178", "14175"],
      "generatedAt": "2026-09-11T20:25:11Z"
    }

Poll it on whatever schedule the tracker already uses. When `latest.gameVersion`
differs from the build the tracker last compared against, run the comparison
again. `configSha256` changes whenever the analysis config changes, so it is a
second, finer trigger: the same build can be re-published with more symbols.

Do not poll the 2 MB snapshot to find this out. There is also a payload-free
companion in `gamesymbols/index.json` (`versions[].light`, about a fifth of the
size) if the tracker only needs names, modules and kinds rather than signatures.

A badge is published per build if a readme wants one:

    ![gamedata](https://sig.miksen.me/badge/latest.svg)

## 2. Ask for a re-hunt of specific symbols

A new build is not the only reason to re-analyse. The tracker is the only side
that knows which symbols stopped resolving in the plugins it watches, and
re-running the two tasks behind three symbols is minutes where a full pipeline is
hours.

Keep the queue in **your own** repository and let the box read it over HTTPS.
The tracker then never needs write access to `mrc4tt/CS2_VibeSignatures`, which
is one less credential to hold and one less thing that can push to a public repo.

    cs2-signatures/rehunt.json
    {"gamever": "14181", "symbols": ["CBaseTrigger_EndTouch", "ClientPrint"]}

On the box, pointed straight at your raw URL:

    uv run rehunt_queue.py -queue https://git.miksen.me/mikkel/cs2-signatures/raw/branch/main/rehunt.json
    uv run rehunt_queue.py -queue https://git.miksen.me/mikkel/cs2-signatures/raw/branch/main/rehunt.json -run

Plain `http` is refused, and only the first megabyte is read. Adjust the path if
Gitea serves raw files differently in your setup; a local file path works too.

Symbols are mapped to their producing task through every task's
`expected_output`, not by guessing `find-<Symbol>`, because tasks are named after
their anchor and one task emits several symbols. The example above maps to two
tasks, and the run writes into a scratch directory so `bin_artifacts/` is only
touched once someone has compared the result.

Put only symbol names in the queue. A name the config does not produce is
reported back as "needs a config entry" rather than silently skipped, which is
the honest answer: `CCSPlayerPawn_GetMaxSpeed` on windows is that case today.

## What not to build

- **No webhook into the box.** It holds the Steam credentials and the IDA
  licence, it sits behind a home router, and an HTTP endpoint that starts shell
  work there is the one thing worth refusing. Pull, never push.
- **No self-hosted GitHub runner**, on either machine, for this repository.
  `mrc4tt/CS2_VibeSignatures` is public, so a pull request from anyone would
  execute its own workflow code on the runner.
- **No runner on the VPS for the analysis.** It has no IDA, no depot binaries
  and not the disk. Its job is to know the result, not to produce it.

## Where the loop closes

    Steam ──poll 15 min──> analysis box ──run──> snapshot + gamedata
                                                      │
                                         push ──> deploy-pages.yml (ubuntu-latest)
                                                      │
                                              latest.json ──poll──> tracker
                                                      │
                                       rehunt.json <──commit── tracker

`deploy-pages.yml` is already unguarded and fork-local: it rebuilds the site on
every push that touches `gamesymbols/`, `gamedata/` or `pages/`, on a
GitHub-hosted runner. That half has been automatic all along.
