# Versioned Gamedata Publication And Completed Staging Cleanup

## Status

Proposed and approved for implementation. This design supersedes the global tracked `dist/` model described in
`docs/plans/new-release-workflow.md` and the earlier private-staged-gamedata revision of this document.

The implementation must land as one atomic generated-output, manifest, workflow, and directory-protocol migration.
Until that cutover, current workflows and memories continue describing the implemented `dist/` behavior.

## Background

The repository currently stores downstream generator code, module overlays, downloaded baselines, and generated
gamedata together below `dist/`. A release build rewrites that global tree from one `GAMEVER` candidate and commits the
result through a generated-output PR.

That model cannot represent multiple accepted game versions at once. Rebuilding a historical version such as
`14168b` can replace the global files needed by a newer version such as `14171`.

The accepted model is now fully versioned:

- generator implementation and configuration live outside generated output;
- every game version has its own tracked, reviewable, immutable gamedata tree;
- private staging stores only bin and promotion recovery state;
- promotion archives the accepted versioned gamedata directly from the output merge;
- successful promotion removes its heavy private stage through an idempotent completion cleanup protocol.

## Decision Summary

Canonical generated gamedata moves to:

```text
gamedata/<GAMEVER>/<DOWNSTREAM_MODULE>/<TARGET_RELATIVE_PATH>
```

For example:

```text
gamedata/14168/CounterStrikeSharp/config/addons/counterstrikesharp/gamedata/gamedata.json
gamedata/14168/CS2Fixes/gamedata/cs2fixes.jsonc
gamedata/14168/cs2kz-metamod/gamedata/cs2kz-core.games.txt
```

`gamedata/<GAMEVER>/` contains final downstream payloads only. It contains no generator source, YAML overlay, Python
cache, provenance file, or internal manifest.

Generator code and overlays move to:

```text
gamedata-generators/<DOWNSTREAM_MODULE>/...
```

Release archives include the new path directly:

```text
gamedata/<GAMEVER>/...
```

They do not preserve or recreate the legacy `dist/...` archive layout.

## Goals

- Make gamedata canonical, tracked, reviewable, and isolated by `GAMEVER`.
- Allow historical republish without changing another version's gamedata.
- Separate generator implementation from generated downstream payloads.
- Keep candidate gamedata validation before C++ validation and output PR creation.
- Make promotion consume only accepted Git bytes and staged bin; no promotion-time gamedata generation or download.
- Bind every versioned gamedata tree to the release manifest and published provenance.
- Remove gamedata from private staging entirely.
- Automatically remove completed private bin/recovery staging after Release verification.
- Preserve crash-safe, idempotent promotion and cleanup recovery.

## Non-Goals

- Do not retain a tracked `dist/` compatibility mirror.
- Do not preserve `dist/...` inside new Release archives.
- Do not copy generator Python or YAML into `gamedata/<GAMEVER>/`.
- Do not backfill every historical version during the initial migration.
- Do not make file extensions alone the output authorization contract.
- Do not generate or modify gamedata after the generated-output PR merge.
- Do not weaken tag, Release, candidate, C++ test, accepted-bin, or output-merge identity guarantees.
- Do not delete an active or recoverable `READY` staging transaction.

## Core Invariants

1. `gamedata/<GAMEVER>/` contains only final downstream payloads declared by trusted generator metadata.
2. Every generated path is below the exact requested `GAMEVER`; no build may modify another version directory.
3. Generator code, overlay YAML, templates, and download declarations live under `gamedata-generators/`, never under a
   versioned output directory.
4. A gamedata candidate is generated from the same immutable symbol candidate and versioned analysis config used by
   the release build.
5. Candidate `gamedata` validation completes only after the versioned tree passes strict path, completeness, and hash
   validation.
6. The generated-output PR directly contains all versioned gamedata bytes used by the Release archive.
7. Promotion never calls `update_gamedata.py`, downloads upstream gamedata, or reads another version directory.
8. Private staging contains staged bin and transaction metadata only; it contains no gamedata payload.
9. `gamedata_manifest_sha256` identifies the canonical inventory of `gamedata/<GAMEVER>/` and is preserved in Release
   provenance.
10. Completion cleanup is authorized only by a matching durable completion record written after all Release assets are
    uploaded, downloaded, and hash-verified.

## Repository Layout

### Generator Layout

```text
gamedata-generators/
  CounterStrikeSharp/
    gamedata.py
  CS2Fixes/
    gamedata.py
    config.yaml
  cs2kz-metamod/
    gamedata.py
    config.yaml
  cs2surf/
    gamedata.py
    config.yaml
  modsharp-public/
    gamedata.py
    config.yaml
  plugify-plugin-s2sdk/
    gamedata.py
  swiftlys2/
    gamedata.py
    config.yaml
```

Generator directories may contain reviewed source, overlay configuration, schema helpers, and static templates. They
are normal source files and are controlled through ordinary source PRs.

### Versioned Output Layout

```text
gamedata/
  14168/
    CounterStrikeSharp/config/addons/counterstrikesharp/gamedata/gamedata.json
    CS2Fixes/gamedata/cs2fixes.jsonc
    cs2kz-metamod/gamedata/cs2kz-core.games.txt
    cs2surf/gamedata/cs2surf-core.games.jsonc
    modsharp-public/.asset/gamedata/core.games.jsonc
    modsharp-public/.asset/gamedata/engine.games.jsonc
    modsharp-public/.asset/gamedata/EntityEnhancement.games.jsonc
    modsharp-public/.asset/gamedata/log.games.jsonc
    modsharp-public/.asset/gamedata/server.games.jsonc
    modsharp-public/.asset/gamedata/tier0.games.jsonc
    plugify-plugin-s2sdk/assets/gamedata.jsonc
    swiftlys2/plugin_files/gamedata/cs2/core/offsets.jsonc
    swiftlys2/plugin_files/gamedata/cs2/core/signatures.jsonc
  14168b/
    ...
  14171/
    ...
```

The allowed current final formats are JSON, JSONC, and downstream VDF-style `.txt`, but the authoritative contract is
the generator-declared output path list. A future format requires a reviewed generator contract change; it is not
admitted merely by matching a broad extension glob.

The version directory must reject:

- `*.py`, `*.pyc`, `*.yaml`, and `*.yml`;
- `__pycache__/` and temporary/editor files;
- internal manifests, download metadata, logs, and debug output;
- symlinks, junctions, reparse points, traversal, absolute paths, and undeclared files.

Inventory and provenance remain in `release-manifests/<GAMEVER>.json`; no metadata file is added inside
`gamedata/<GAMEVER>/`.

## Generator Contract

### Module Declaration

Each trusted generator module declares its exact outputs and download inputs. The implementation may use Python
constants or a declarative source-side manifest, but there must be one canonical contract consumed by generation and
verification.

Representative shape:

```python
MODULE_NAME = "CounterStrikeSharp"

OUTPUT_PATHS = (
    "config/addons/counterstrikesharp/gamedata/gamedata.json",
)

DOWNLOAD_SOURCES = (
    ("https://.../gamedata.json", OUTPUT_PATHS[0]),
)
```

Requirements:

- every output path is normalized, relative, unique, and contained below the module output root;
- every download target is also a declared output path;
- every declared output exists after generation;
- no undeclared regular file exists in the versioned candidate tree;
- module names satisfy a strict repository path contract and cannot equal a `GAMEVER` or reserved directory name;
- module update APIs receive generator/config paths separately from output paths.

### CLI Boundary

Refactor `update_gamedata.py` so module discovery and output storage are separate concepts:

```text
update_gamedata.py
  -gamever <GAMEVER>
  -snapshot <immutable candidate>
  -configyaml configs/<GAMEVER>.yaml
  -modulesdir gamedata-generators
  -outputdir <candidate-root>/gamedata/<GAMEVER>
  -download_latest
  -strict
```

Remove `-distdir` from release workflows. A temporary compatibility alias may exist only during local migration and
must not remain in the final release path.

Strict release generation must fail on:

- HTTP/download failure;
- missing or duplicate module/output declarations;
- module load or update exception;
- missing declared output;
- undeclared output;
- empty enabled-module discovery;
- path escape or reparse point;
- symbol candidate/config identity mismatch.

The current best-effort behavior that logs module errors and returns success is not acceptable for release generation.

## Gamedata Candidate Contract

Generation occurs in a build-owned directory below `RUNNER_TEMP`, never directly in the Git worktree:

```text
RUNNER_TEMP/
  gamedata-candidates/<BUILD_ID>/
    gamedata/<GAMEVER>/...
    session.json
```

Add a small candidate helper or extend existing candidate infrastructure with these operations:

- `build`: create an empty version root, generate all declared outputs, validate the tree, and write a canonical
  inventory/session;
- `guard`: verify every file byte, path, size, hash, generator contract digest, symbol candidate hash, and analysis
  config hash remains unchanged;
- `publish`: atomically replace workspace `gamedata/<GAMEVER>` with the guarded candidate and verify the published
  inventory.

The session records at least:

```json
{
  "gamever": "14168",
  "build_id": "123456789-1",
  "candidate_sha256": "<symbol-candidate-sha256>",
  "analysis_config_sha256": "<sha256>",
  "generator_contract_sha256": "<sha256>",
  "gamedata_manifest_sha256": "<sha256>",
  "files": [
    {"path": "gamedata/14168/...", "size": 123, "sha256": "<sha256>"}
  ]
}
```

The generator contract digest prevents generator/output declarations from changing between generation and publish.

## End-To-End Release Flow

```text
dispatch exact GAMEVER + SOURCE_SHA
        -> checkout exact SOURCE_SHA
        -> restore/invalidate/analyze bin
        -> build immutable symbol candidate
        -> generate versioned gamedata candidate in RUNNER_TEMP
        -> guard gamedata and mark candidate gamedata validation
        -> run C++ tests and mark candidate C++ validation
        -> publish symbol snapshot and gamedata/<GAMEVER>
        -> stage tracked snapshot + versioned gamedata in Git index
        -> stage private bin + manifests + READY
        -> generated-output PR
        -> PR merge
        -> verify accepted snapshot, versioned gamedata, manifest, and staged bin
        -> archive accepted gamedata/<GAMEVER> directly
        -> promote bin, apply tag rules, upload and download-verify assets
        -> write completion record
        -> remove heavy completed private stage
```

## Build Workflow Design

After building the immutable symbol candidate, `build-on-self-runner.yml` performs:

1. Build versioned gamedata in the isolated candidate root using strict generation.
2. Guard the symbol candidate and gamedata candidate.
3. Mark the existing candidate `gamedata` validation step.
4. Run C++ validation against the unchanged symbol candidate.
5. Mark `cpp_tests` and require the symbol candidate state to be fully validated.
6. Publish the symbol candidate to `gamesymbols/<GAMEVER>.yaml`.
7. Publish the gamedata candidate to `gamedata/<GAMEVER>/`.
8. Stage exactly:

   ```text
   gamesymbols/<GAMEVER>.yaml
   gamedata/<GAMEVER>/**
   ```

9. Build the tracked/private release manifests and stage private bin.
10. Add `release-manifests/<GAMEVER>.json`, commit the immutable output branch, and create the PR.

Before staging, require that no path outside the exact version root changed. Historical republish updates its own
directory and has no latest-version special case.

The build's always-cleanup removes only temporary symbol/gamedata candidate roots and incomplete, non-READY private
staging. A READY stage remains until PR close, promotion, abandon, or completed cleanup.

## Manifest Contract

The tracked release-manifest schema must be bumped. Add at least:

```json
{
  "gamedata_path": "gamedata/14168",
  "gamedata_manifest_sha256": "<sha256>",
  "generator_contract_sha256": "<sha256>"
}
```

Requirements:

- `gamedata_path` must exactly equal `gamedata/<GAMEVER>`;
- `gamedata_manifest_sha256` is the canonical digest of the exact tracked version-directory inventory;
- `generator_contract_sha256` identifies the trusted output declaration set used by the build;
- `tracked_output_manifest_sha256` covers `gamesymbols/<GAMEVER>.yaml` and `gamedata/<GAMEVER>/**`;
- `candidate_sha256` continues matching the published symbol snapshot;
- no private manifest field claims that gamedata bytes are present in private staging.

The private manifest continues storing the tracked file inventory for verification and additionally stores only the
private staged-bin inventory. `READY` binds the private manifest, tracked fields, PR head identity, and bin files.

Release provenance copies `gamedata_path`, `gamedata_manifest_sha256`, and `generator_contract_sha256`, in addition to
the existing source, output merge, tag, candidate, bin, and asset hashes.

## Generated-Output PR Contract

The generated-output PR may change only:

```text
gamesymbols/<GAMEVER>.yaml
gamedata/<GAMEVER>/**
release-manifests/<GAMEVER>.json
```

`verify-output-pr` must reject:

- any legacy `dist/` change;
- another `gamedata/<OTHER_GAMEVER>/` directory;
- generator source or config changes in the generated-output PR;
- undeclared, missing, forbidden-extension, transient, linked, or non-regular gamedata files;
- tracked/private manifest inventory disagreement;
- mismatched generator contract or gamedata digest;
- a stale source/base SHA as today.

Trusted validation tooling loads the generator contract from the PR base/source checkout, not from generated output.
The output PR therefore cannot authorize a new path by modifying generator metadata in the same generated-output
commit.

## Promotion And Archive Design

Promotion verifies:

- merge parents, PR index, private/tracked manifests, branch, and repository identity;
- accepted symbol snapshot and candidate hash;
- accepted `gamedata/<GAMEVER>/` inventory and `gamedata_manifest_sha256`;
- generator contract digest from trusted source tooling;
- staged bin inventory/hash;
- allowed merge paths and tracked-output inventory.

Promotion must not call `update_gamedata.py`, access live upstream gamedata, or reconstruct gamedata from private
staging.

The gamedata archive directly includes:

```text
configs/<GAMEVER>.yaml
bin/<GAMEVER>/...
gamesymbols/<GAMEVER>.yaml
gamedata/<GAMEVER>/...
hl2sdk_cs2/...
```

No `dist/` path is created in the checkout, temporary archive root, or archive. The 7-Zip command must name only the
exact versioned gamedata directory so another version can never enter the asset.

The config is still extracted from immutable `source_sha` and checked against `analysis_config_sha256`. Archive and
provenance asset hashes are generated after all accepted inputs are verified.

Promotion ordering remains:

```text
verify merge + tracked outputs + staged bin
        -> create archives from accepted gamedata/<GAMEVER>
        -> promote accepted bin transactionally
        -> apply immutable tag rules
        -> write provenance/checksums
        -> upload and download-verify all Release assets
        -> finalize promotion and write durable completion record
        -> attempt completed-stage cleanup
```

## Private Staging Layout

Private staging no longer stores gamedata:

```text
PERSISTED_WORKSPACE/
  release-staging/
    <GAMEVER>/
      <BUILD_ID>/
        bin/<GAMEVER>/...
        manifest.json
        READY
        PROMOTION_STARTED
        PROMOTED.json
        PROMOTION_COMPLETE
    pr-index/
      <PR_NUMBER>.json
    completed/
      <GAMEVER>/
        <BUILD_ID>.json
    cleanup-trash/
      <GAMEVER>/
        <BUILD_ID>/...
    locks/
      <GAMEVER>.lock
```

This stage is still required because accepted persisted bin remains private and transactionally promoted only after
the output PR merges. Removing gamedata from staging reduces disk use and removes a second copy/verification path.

## Completed Staging Cleanup

### Durable Completion Record

After all Release assets have been uploaded, downloaded, and hash-verified, `finalize-promotion` writes a complete
identity such as:

```json
{
  "schema_version": 1,
  "gamever": "14168",
  "build_id": "123456789-1",
  "pr_number": 42,
  "pr_head_sha": "<sha>",
  "output_merge_sha": "<sha>",
  "candidate_sha256": "<sha256>",
  "gamedata_manifest_sha256": "<sha256>",
  "bin_manifest_sha256": "<sha256>",
  "release_provenance_sha256": "<sha256>"
}
```

Finalization performs this crash-safe sequence:

1. Reverify accepted bin and completed publication identity.
2. Write `stage/PROMOTION_COMPLETE` atomically.
3. Remove the accepted-bin backup and require matching incoming/backup paths to be absent.
4. Write the matching canonical record to `completed/<GAMEVER>/<BUILD_ID>.json` atomically.
5. Remove the matching PR index.

Interruption before step 5 leaves the original indexed promotion retryable. Interruption after step 5 leaves a durable
record that authorizes cleanup without reusing the PR index.

### `cleanup-completed` Command

Add an idempotent command taking explicit `staging_root`, `persisted_root`, `gamever`, and `build_id`.

Every cleanup attempt requires:

- a canonical completion record matching the requested identity;
- no matching PR index;
- no matching accepted-bin incoming or backup recovery path;
- path containment and reparse-point checks for every resolved path.

Before the initial deletion transition, it additionally requires:

- `stage/PROMOTION_COMPLETE` canonically matching the durable record;
- `manifest.json` and `PROMOTED.json` agreeing with the durable completed-build identity;
- the normal stage path to exist and the exact cleanup-trash path to be absent.

Cleanup deliberately does not require the current accepted bin to retain the completed build's inventory. That
inventory was reverified before the durable completion record was written, and a later successful same-version
republish may legitimately replace accepted bin before a delayed sweeper removes the older completed stage.

Cleanup atomically renames:

```text
release-staging/<GAMEVER>/<BUILD_ID>
```

to the same-volume path:

```text
release-staging/cleanup-trash/<GAMEVER>/<BUILD_ID>
```

while holding the per-version lock, then recursively removes the trash directory. The compact completion record is
preserved.

Recovery cases:

- normal stage exists, trash absent: validate and atomically rename, then delete trash;
- normal stage absent, exact trash exists: resume deletion from the completion-record-bound trash path;
- both exist: fail closed;
- neither exists and completion record is valid: return success.

The command never removes accepted bin, Release assets, an active READY stage, or an arbitrary age-selected directory.

### Immediate Cleanup And Scheduled Fallback

Promotion calls `cleanup-completed` immediately after successful finalization. Cleanup failure does not roll back an
already verified public Release; it emits a warning with the exact `GAMEVER` and `BUILD_ID` for scheduled retry.

Add `.github/workflows/cleanup-completed-release-staging.yml` with guarded `schedule` and `workflow_dispatch` triggers,
the protected `win64` environment, Windows self-hosted runner, and the same per-version lock as promotion.

The sweeper enumerates only canonical records below `release-staging/completed/` and invokes the same
`cleanup-completed` implementation. It reports removed, resumed, already-absent, skipped, and failed entries.

This provides immediate cleanup in the normal path and eventual cleanup after runner termination or transient file
locking. Eventual cleanup assumes the protected runner and persisted storage become available again.

## Failure And Retry Semantics

- Symbol or gamedata generation failure: no candidate mark, no output PR, and no accepted-state change.
- Gamedata candidate tampering: guard fails before publication and staging.
- C++ validation failure: generated candidates remain temporary and no output PR is created.
- PR closed without merge: indexed cleanup removes private bin staging only.
- Promotion failure before asset verification: preserve READY staging, index, and recovery state for identical retry.
- Archive failure: accepted tracked gamedata remains unchanged; preserve private bin staging.
- Asset verification failure: do not write `PROMOTION_COMPLETE`.
- Finalization failure before PR-index removal: rerun normal promotion.
- Immediate cleanup failure after finalization: preserve completion record and retry through the scheduled sweeper.
- Cleanup interruption after trash rename: resume exact trash deletion without requiring already removed stage files.
- A historical republish changes only its own snapshot, gamedata directory, and release manifest.

## Required Repository Changes

- Move generator modules and overlays from `dist/<MODULE>/` to `gamedata-generators/<MODULE>/`.
- Remove the tracked global `dist/` output model and all release authority assigned to it.
- Refactor `update_gamedata.py` into separate module and output roots with strict release behavior.
- Add versioned gamedata candidate build/guard/publish support.
- Update `.github/workflows/build-on-self-runner.yml` to publish and stage `gamedata/<GAMEVER>/`.
- Update `.github/workflows/pr-self-runner.yml` to use isolated versioned gamedata candidates for validation.
- Update `.github/workflows/validate-generated-output-pr.yml` for the new path contract.
- Update `.github/workflows/promote-release-after-output-merge.yml` to archive `gamedata/<GAMEVER>/` directly.
- Add `.github/workflows/cleanup-completed-release-staging.yml`.
- Update `release_workflow_lib/manifests.py`, `hashing.py`, `staging.py`, `promotion.py`, and `cli.py` for the new schema,
  inventories, path checks, completion records, and cleanup command.
- Update downstream generator tests, workflow contract tests, README paths, skills, current plans, and Serena memories.

## Test Plan

### Generator And Candidate

- Discover generators only from `gamedata-generators/`.
- Require exact, unique, contained `OUTPUT_PATHS`.
- Generate from an empty version root.
- Fail strict generation on download/module/missing/extra/path/reparse errors.
- Reject Python, YAML, caches, metadata, and transient files from version output.
- Preserve JSONC formatting behavior where applicable.
- Guard candidate bytes, generator contract digest, symbol candidate hash, and config hash.
- Atomically publish only `gamedata/<GAMEVER>`.

### Build And PR Contract

- `14168` build writes only `gamedata/14168/**`.
- `14168b` republish cannot modify `gamedata/14168/**` or a newer directory.
- Output PR rejects every `dist/` path.
- Output PR rejects generator changes and undeclared versioned files.
- Tracked/private inventory and `gamedata_manifest_sha256` disagreement fails.
- Candidate gamedata validation remains before C++ validation and publication.

### Promotion And Archive

- Promotion performs no gamedata generation or network download.
- Archive contains `gamedata/<GAMEVER>/...` and contains no `dist/` entry.
- Archive excludes every other game version.
- Accepted gamedata tampering fails before archive creation.
- Provenance binds generator contract, gamedata inventory, output merge, and asset hashes.
- Same accepted merge and staged bin produce byte-identical logical archive contents.

### Private Staging And Cleanup

- Stage-build stores bin and transaction metadata but no gamedata directory.
- Unmerged cleanup and abandon remove only matching private bin staging.
- Successful finalization writes matching stage and durable completion records.
- Cleanup atomically renames stage to exact cleanup-trash before recursive deletion.
- Interrupted trash deletion resumes idempotently.
- Cleanup refuses index/recovery/path/reparse/completion-identity mismatch.
- Cleanup still succeeds for an older completed build after a newer same-version promotion replaces accepted bin.
- READY without `PROMOTION_COMPLETE` is never removed.
- Scheduled enumeration processes only durable completion records.

### Repository Gates

Run targeted gamedata/release/workflow tests, formatter checks, Ruff, workflow YAML parsing, actionlint, and the full
unittest suite. Add a non-publishing smoke that generates a versioned gamedata candidate, validates an output PR fixture,
constructs an archive with the new root layout, and completes/cleans private bin staging without creating a remote
branch, tag, or Release.

## Migration And Rollout

The path and manifest migration is intentionally breaking and must be atomic.

Before cutover:

1. Confirm no release build is queued or running.
2. Confirm no generated-output PR remains open.
3. Confirm no READY staging transaction still requires the old promotion code.
4. Move generator code/config into `gamedata-generators/` and update all imports/tests.
5. Regenerate the currently accepted release version through the new strict versioned-output path.
6. Include its reviewed `gamedata/<GAMEVER>/` tree in the same migration PR.
7. Remove tracked `dist/` in that same PR, together with the updated workflows, manifests, helpers, and tests.

Do not blindly copy legacy `dist/` bytes into an arbitrary version directory. The migration must prove which accepted
`GAMEVER`, symbol snapshot, analysis config, and generator contract produced the seeded output. If that identity cannot
be proven, regenerate it.

Historical versions are created on demand by future rebuild/republish operations; full backfill is not required.

Existing completed private stages use the old completion schema. The scheduled sweeper must not infer them as safe.
Handle them through an explicit one-time migration/cleanup command that validates their completion marker, promoted
state, and missing index/recovery paths. It must additionally prove completion from the current accepted-bin inventory
when that build is still current, or from matching immutable published provenance when a newer same-version promotion
has superseded accepted bin, before writing a new compact completion record and deleting the heavy stage.

Rollout verification must include:

- one current-version build whose PR creates/updates only its versioned gamedata tree;
- one historical republish whose PR changes only the requested historical tree;
- Release archive inspection proving the direct `gamedata/<GAMEVER>/` root and absence of `dist/`;
- successful immediate completed-stage deletion;
- scheduled recovery of a prepared interrupted cleanup-trash fixture.

## Documentation Updates After Implementation

- Rewrite the current-output portions of `docs/plans/new-release-workflow.md`.
- Update README supported-gamedata paths from `dist/...` to `gamedata/<GAMEVER>/...`.
- Update `.serena/memories/build-on-self-runner.md`.
- Update `.serena/memories/promote-release-after-output-merge.md`.
- Update `.serena/memories/update_gamedata.md` and `project_overview.md`.
- Update skills and completion guidance that stage or inspect changed `dist/` files.
- Keep historical documents unchanged when they clearly describe superseded behavior.

## Acceptance Criteria

- No release workflow reads, writes, stages, verifies, or archives tracked global `dist/` output.
- `gamedata-generators/` contains generator source/config and no versioned release authority.
- `gamedata/<GAMEVER>/` contains only exact declared final payloads and no YAML/Python/internal metadata.
- Every release build commits and reviews the exact gamedata bytes used by its Release archive.
- Historical and current versions coexist without latest-version branching logic.
- Promotion archives `gamedata/<GAMEVER>/` directly and never creates a `dist/` layout.
- Private staging contains no gamedata and remains limited to bin and recovery identity.
- Manifests and provenance bind the versioned gamedata inventory and generator contract.
- Candidate gamedata and C++ validation remain mandatory before output PR creation.
- Successful publication writes a durable completion record and normally removes the heavy private stage immediately.
- Scheduled cleanup safely completes interrupted deletion without touching active READY state or accepted bin.
- Existing tag, Release, output-merge, and transactional accepted-bin guarantees remain unchanged.
