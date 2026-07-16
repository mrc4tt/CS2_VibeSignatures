---
name: post-change-update
description: |
  Run repository-mutating post-change maintenance in two ordered phases around C++ validation.
  Use phase=before-validation for formatting, candidate build, and candidate-backed gamedata, then use
  phase=after-validation to publish the same validated candidate bytes.
disable-model-invocation: true
---

# Post-Change Update

Run the repository-maintenance commands that can change tracked content. This skill does not validate C++
layouts and does not commit; callers must place `/post-change-validation` between its two phases.

## Inputs

- `phase` — required; exactly `before-validation` or `after-validation`.
- `gamever` — use the caller-provided value. If omitted, read `CS2VIBE_GAMEVER` from `.env`.
- `candidate` and `session` — required for `after-validation`; use the paths returned by `before-validation`.

Stop if the phase is missing or invalid. Stop if no non-empty game version can be resolved.
Set `ANALYSIS_CONFIG="configs/$GAMEVER.yaml"` and stop if it is not a file.

## Safety Rules

- Run from the repository root.
- Preserve unrelated pre-existing work and never stage or commit changes.
- Stop on the first failed command and report its command, exit code, and relevant output.
- Never run downstream validation directly from `bin` or fall back to a tracked head snapshot.
- Never rebuild or reserialize a candidate after downstream validation begins.
- Never run the after-validation phase without explicit success from `/post-change-validation` for the same
  game version, candidate, and session in the current calling task.

## Phase: before-validation

Record `git status --short`, then run these commands in order:

```bash
uv run python format_repo_files.py
uv run python format_repo_files.py --check
CANDIDATE_ROOT="$(mktemp -d "/tmp/gamesymbol-candidate-${GAMEVER}-XXXXXX")"
CANDIDATE="$CANDIDATE_ROOT/${GAMEVER}.yaml"
CANDIDATE_SESSION="$CANDIDATE_ROOT/${GAMEVER}.session.json"
uv run gamesymbol_candidate.py build -gamever "$GAMEVER" -bindir bin -configyaml "$ANALYSIS_CONFIG" -output "$CANDIDATE" -session "$CANDIDATE_SESSION"
uv run gamesymbol_candidate.py guard -candidate "$CANDIDATE" -session "$CANDIDATE_SESSION"
uv run update_gamedata.py -gamever "$GAMEVER" -snapshot "$CANDIDATE" -debug
uv run gamesymbol_candidate.py guard -candidate "$CANDIDATE" -session "$CANDIDATE_SESSION"
uv run gamesymbol_candidate.py mark -candidate "$CANDIDATE" -session "$CANDIDATE_SESSION" -step gamedata
```

The write-mode formatter is intentional. The following `--check` proves the resulting tracked Python/YAML
files are clean. If formatting, the check, or gamedata generation fails, stop the calling task and report the
failure; do not continue to C++ validation.

On success, report which tracked files changed plus the candidate path, session path, and candidate SHA-256. Return
control to the caller so it can pass those exact paths to `/post-change-validation`.

## Phase: after-validation

First confirm that `/post-change-validation` passed for the same `GAMEVER`, candidate, and session during the current
calling task. If that evidence is absent or validation failed, stop without modifying the tracked snapshot. Then run:

```bash
uv run gamesymbol_candidate.py guard -candidate "$CANDIDATE" -session "$CANDIDATE_SESSION"
uv run gamesymbol_candidate.py publish -candidate "$CANDIDATE" -session "$CANDIDATE_SESSION" -snapshot "gamesymbols/$GAMEVER.yaml"
```

If publication fails, report the exit code and diagnostics, then stop before commit. On success, verify that the
published SHA-256 equals the candidate SHA-256, run `git status --short`, report the snapshot and other tracked files
changed by both phases, and return control to the caller's commit step.
