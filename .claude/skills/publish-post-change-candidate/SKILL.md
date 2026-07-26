---
name: publish-post-change-candidate
description: |
  Publish the same immutable symbol and gamedata candidates that passed `/post-change-validation`.
  Use only after successful C++ validation for the exact game version, candidate, and session being published.
---

# Publish Post-Change Candidate

Publish already-validated candidate bytes to the tracked symbol snapshot and versioned gamedata. This skill does not
format files, rebuild or reserialize candidates, run C++ validation, stage changes, or commit.

## Inputs

- `gamever` — use the caller-provided value. If omitted, read `CS2VIBE_GAMEVER` from `.env`.
- `candidate` — required candidate snapshot path returned by `/prepare-post-change-candidate`.
- `session` — required candidate session path paired with that candidate.
- `gamedata_session` — required gamedata session path returned by `/prepare-post-change-candidate`.

Stop if no non-empty game version can be resolved. Set `ANALYSIS_CONFIG="configs/$GAMEVER.yaml"` and stop if it is
not a file. Stop if any required candidate or session path is absent.

## Safety Rules

- Run from the repository root.
- Preserve unrelated pre-existing work and never stage or commit changes.
- Stop on the first failed command and report its command, exit code, and relevant output.
- Keep every candidate, snapshot, gamedata, and config path constrained to the resolved `GAMEVER`; never fan out to
  historical or neighboring versions.
- Never publish without explicit `/post-change-validation` success for the same game version, candidate, and candidate
  session in the current calling task.
- Never rebuild or reserialize a candidate after downstream validation begins.
- Never fall back to `bin` or a tracked head snapshot.

## Method

Confirm that `/post-change-validation` passed for the exact `GAMEVER`, candidate, and candidate session. The candidate
session must contain the successful `cpp_tests` step; the publish command enforces the validated session state. If
that evidence is absent or validation failed, stop without modifying tracked snapshot or gamedata files.

Run these commands in order:

```bash
uv run gamesymbol_candidate.py guard -candidate "$CANDIDATE" -session "$CANDIDATE_SESSION"
uv run gamedata_candidate.py guard -session "$GAMEDATA_SESSION"
uv run gamesymbol_candidate.py publish -candidate "$CANDIDATE" -session "$CANDIDATE_SESSION" -snapshot "gamesymbols/$GAMEVER.yaml"
uv run gamedata_candidate.py publish -session "$GAMEDATA_SESSION" -outputdir "gamedata/$GAMEVER"
```

If publication fails, report the exit code and diagnostics, then stop before commit. On success, verify that the
published snapshot SHA-256 equals the candidate SHA-256, run `git status --short`, report the snapshot and other
tracked files changed by preparation and publication, and return control to the caller's commit step.
