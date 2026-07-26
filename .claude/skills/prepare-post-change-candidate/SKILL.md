---
name: prepare-post-change-candidate
description: |
  Format tracked repository files and build immutable symbol and gamedata candidates for one game version.
  Use after analysis outputs, configs, generators, or C++ tests change and before `/post-change-validation`.
---

# Prepare Post-Change Candidate

Prepare the exact candidate bytes consumed by downstream validation and publication. This skill may format tracked
files and create untracked candidate artifacts, but it does not run C++ validation, publish tracked snapshot or
gamedata files, stage changes, or commit.

## Inputs

- `gamever` — use the caller-provided value. If omitted, read `CS2VIBE_GAMEVER` from `.env`.

Stop if no non-empty game version can be resolved. Set `ANALYSIS_CONFIG="configs/$GAMEVER.yaml"` and stop if it is
not a file.

This workflow is single-version scoped: prepare only the resolved `GAMEVER`. Do not rebuild, repack, publish, or
otherwise modify snapshots, gamedata, configs, or candidate artifacts for any other game version.

## Safety Rules

- Run from the repository root.
- Preserve unrelated pre-existing work and never stage or commit changes.
- Stop on the first failed command and report its command, exit code, and relevant output.
- Keep every candidate, gamedata, and config path constrained to the resolved `GAMEVER`; never fan out to historical
  or neighboring versions.
- Never run downstream validation directly from `bin` or fall back to a tracked head snapshot.

## Method

Record `git status --short`, then run these commands in order:

```bash
uv run python format_repo_files.py
uv run python format_repo_files.py --check
CANDIDATE_ROOT="$(mktemp -d "/tmp/gamesymbol-candidate-${GAMEVER}-XXXXXX")"
CANDIDATE="$CANDIDATE_ROOT/${GAMEVER}.yaml"
CANDIDATE_SESSION="$CANDIDATE_ROOT/${GAMEVER}.session.json"
GAMEDATA_ROOT="$CANDIDATE_ROOT/gamedata-candidate"
GAMEDATA_SESSION="$CANDIDATE_ROOT/${GAMEVER}.gamedata.session.json"
uv run gamesymbol_candidate.py build -gamever "$GAMEVER" -bindir bin -configyaml "$ANALYSIS_CONFIG" -output "$CANDIDATE" -session "$CANDIDATE_SESSION"
uv run gamesymbol_candidate.py guard -candidate "$CANDIDATE" -session "$CANDIDATE_SESSION"
uv run gamedata_candidate.py build -gamever "$GAMEVER" -build-id local-1 -snapshot "$CANDIDATE" -configyaml "$ANALYSIS_CONFIG" -candidate-root "$GAMEDATA_ROOT" -session "$GAMEDATA_SESSION" -debug
uv run gamedata_candidate.py guard -session "$GAMEDATA_SESSION"
uv run gamesymbol_candidate.py guard -candidate "$CANDIDATE" -session "$CANDIDATE_SESSION"
uv run gamesymbol_candidate.py mark -candidate "$CANDIDATE" -session "$CANDIDATE_SESSION" -step gamedata
```

The write-mode formatter is intentional. The following `--check` proves the resulting tracked Python/YAML files are
clean. If formatting, the check, candidate construction, or gamedata generation fails, stop the calling task and do
not continue to C++ validation.

On success, report which tracked files changed plus the symbol candidate path, candidate session path, gamedata
session path, and candidate SHA-256. Return control to the caller so it can pass the exact `GAMEVER`, candidate, and
candidate session to `/post-change-validation` while retaining the gamedata session for
`/publish-post-change-candidate`.
