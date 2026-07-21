# Post-Change Update

## Overview
Repository-mutating post-change maintenance skill that rebuilds and republishes the tracked symbol snapshot and versioned gamedata around a mandatory `/post-change-validation` gate. Defined in `.claude/skills/post-change-update/SKILL.md`; never runs validation itself and never commits.

## Responsibilities
- Resolve `GAMEVER` (caller value or `CS2VIBE_GAMEVER`) and enforce `ANALYSIS_CONFIG=configs/<GAMEVER>.yaml`.
- Phase `before-validation`: format tracked files, build an isolated symbol candidate snapshot + session, build isolation versioned gamedata candidate + session, guard both, and `mark` the gamedata step.
- Phase `after-validation`: re-guard both candidates, publish the validated symbol candidate bytes to `gamesymbols/<GAMEVER>.yaml`, publish the gamedata candidate to `gamedata/<GAMEVER>`, and verify candidate SHA equals published SHA.
- Stop at the first failing command; never resume after validation failure or bypass the validation gate between phases.

## Involved Files & Symbols
- `.claude/skills/post-change-update/SKILL.md` - phase contract.
- `format_repo_files.py` - write-mode + `--check` canonicalization gate.
- `gamesymbol_candidate.py` - `build`, `guard`, `mark`, `publish` subcommands; see `gamesymbol_snapshot_lib.candidate.{build_candidate_snapshot, guard_candidate, complete_candidate_step, publish_candidate}`.
- `gamedata_candidate.py` - `build`, `guard`, `publish` subcommands; see `update_gamedata.generate_gamedata` and `gamedata_candidate.{build_candidate, guard_candidate, publish_candidate, verify_published_gamedata}`.
- `release_workflow_lib/hashing.py` - `sha256_file`, `write_canonical_json`, `load_json_object`.

## Architecture
```text
configs/<GAMEVER>.yaml + bin/<GAMEVER>/
  --> gamesymbol_candidate build  --> $CANDIDATE_ROOT/<GAMEVER>.yaml + .session.json
  --> gamedata_candidate build    --> $CANDIDATE_ROOT/gamedata-candidate/gamedata/<GAMEVER> + .gamedata.session.json
  --> [post-change-validation gate, external to this skill]
  --> gamesymbol_candidate publish --> gamesymbols/<GAMEVER>.yaml
  --> gamedata_candidate publish   --> gamedata/<GAMEVER>
```

Candidate root is a fresh `mktemp -d /tmp/gamesymbol-candidate-<GAMEVER>-XXXXXX`. The candidate snapshot is rebuilt with `LATEST_CONFIG_DIGEST_VERSION` (currently 2) and the latest schema version, and its `config_sha256` tracks the current `configs/<GAMEVER>.yaml`; therefore adding/removing skills in the config invalidates a prior snapshot and forces a fresh candidate build in this workflow.

## Dependencies
- `/post-change-validation` must return explicit success for the same `GAMEVER`, candidate, and session between the two phases.
- `bin/<GAMEVER>/` must already contain every `required_output` YAML for every active skill; this skill neither runs IDA preprocessors nor regenerates symbol YAML files.
- `configs/<GAMEVER>.yaml` must resolve via `analysis_config.resolve_analysis_config`.
- Trusted generator modules under `gamedata-generators/` for gamedata conversion.

## Notes
- The skill never stages or commits; the caller is responsible for committing after `after-validation` succeeds.
- `before-validation` uses `format_repo_files.py` write mode followed by `--check`; both must pass before the candidate build.
- `after-validation` refuses to run without prior `/post-change-validation` success recorded in the same calling task for the same candidate/session, and never rebuilds or reserializes the candidate after validation begins.
- Candidate and published snapshot bytes must match by SHA-256; any mismatch stops publication before commit.
- This is the preferred release-grade path for refreshing tracked snapshot + gamedata after a config or generator change; use `pack-snapshot` directly only when the full gamedata + C++ validation gate is not required.

## Callers
- Manual repository maintenance after editing `configs/<GAMEVER>.yaml`, generator modules, or symbol YAML.
- Followed by `/post-change-validation` between its two phases.