---
name: post-change-update
description: |
  Run repository-mutating post-change maintenance in two ordered phases around C++ validation.
  Use phase=before-validation for format_repo_files and update_gamedata, and phase=after-validation for
  gamesymbol_snapshot pack after post-change-validation passed for the same game version.
disable-model-invocation: true
---

# Post-Change Update

Run the repository-maintenance commands that can change tracked content. This skill does not validate C++
layouts and does not commit; callers must place `/post-change-validation` between its two phases.

## Inputs

- `phase` — required; exactly `before-validation` or `after-validation`.
- `gamever` — use the caller-provided value. If omitted, read `CS2VIBE_GAMEVER` from `.env`.

Stop if the phase is missing or invalid. Stop if no non-empty game version can be resolved.

## Safety Rules

- Run from the repository root.
- Preserve unrelated pre-existing work and never stage or commit changes.
- Stop on the first failed command and report its command, exit code, and relevant output.
- Never skip snapshot packing because its CLI is unavailable.
- Never run the after-validation phase without explicit success from `/post-change-validation` for the same
  game version in the current calling task.

## Phase: before-validation

Record `git status --short`, then run these commands in order:

```bash
uv run python format_repo_files.py
uv run python format_repo_files.py --check
uv run update_gamedata.py -gamever "$GAMEVER" -debug
```

The write-mode formatter is intentional. The following `--check` proves the resulting tracked Python/YAML
files are clean. If formatting, the check, or gamedata generation fails, stop the calling task and report the
failure; do not continue to C++ validation.

On success, report which tracked files changed and return control to the caller so it can run
`/post-change-validation`.

## Phase: after-validation

First confirm that `/post-change-validation` passed for the same `GAMEVER` during the current calling task. If
that evidence is absent or the validation failed, stop without modifying the snapshot.

Require the snapshot CLI to exist:

```bash
test -f gamesymbol_snapshot.py
```

If it is missing, stop explicitly:

```text
<skill_error>post-change-update cannot pack gamever GAMEVER: gamesymbol_snapshot.py is missing.</skill_error>
```

Do not treat this as optional and do not permit the caller to commit. When the CLI exists, run:

```bash
uv run gamesymbol_snapshot.py pack -gamever "$GAMEVER" -debug
```

If packing fails, report the exit code and canonical-pack diagnostics, then stop before commit. On success,
run `git status --short`, report the snapshot and other tracked files changed by both phases, and return control
to the caller's commit step.
