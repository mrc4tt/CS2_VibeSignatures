# New Release Workflow

## Status

Implemented on `dev` with unit, workflow, formatting, lint, and non-publishing smoke coverage. This document
supersedes the previous release timing in
`.github/workflows/build-on-self-runner.yml` and the tag-first portion of
`.github/workflows/tag-bump-after-merge.yml`.

## Background

The current new-version flow creates the game-version tag, runs analysis, persists `bin/<GAMEVER>`, creates a
follow-up snapshot/gamedata PR, and immediately publishes the Release. This allows the shared cache and public
Release to become official before `gamesymbols/<GAMEVER>.yaml` and `dist/` have been merged into the default branch.

The new design separates four identities that were previously represented by one tag:

- `GAMEVER`: the CS2 game version selected from `download.yaml`.
- `SOURCE_SHA`: the immutable repository commit containing the generator code, `config.yaml`, preprocessors,
  Agent SKILLs, references, and tests used by this build.
- `OUTPUT_MERGE_SHA`: the merge commit that accepts the generated snapshot, gamedata, and release manifest.
- `RELEASE_TAG`: the Git tag and GitHub Release destination. It normally equals `GAMEVER`.

Git tags no longer trigger analysis. A dispatch event triggers analysis from an explicit `SOURCE_SHA`; PR merge is
the promotion gate for tag creation, persisted-bin promotion, and Release publication.

## Goals

- Never create a new game-version tag before the generated-output PR is merged.
- Never publish or replace Release assets before the generated-output PR is merged.
- Never promote staged `bin/<GAMEVER>` into the accepted persisted namespace before the PR is merged.
- Support rebuilding an existing `GAMEVER` from a newer `SOURCE_SHA` without moving its existing tag.
- Preserve the analyzer's current execution and reuse rules; do not unconditionally execute every preprocessor.
- Make manual rebuilds user-friendly through a project-level SKILL that resolves the SHA and dispatches the workflow.
- Make every phase idempotent, traceable, and recoverable after partial failure.

## Non-Goals

- Do not make Release assets the canonical symbol source; the tracked snapshot remains canonical.
- Do not force-move or recreate existing release tags during a same-version rebuild.
- Do not make ordinary PR validation publish snapshots or write accepted persisted state.
- Do not require users to type `gh workflow run` or manually copy a commit SHA.
- Do not redefine the analyzer's producer scheduling, skip behavior, or old-signature reuse semantics.

### PR Self-Runner Boundary

Ordinary PR validation does not build the newest version introduced by head `download.yaml`. It selects a trusted
snapshot from `pull_request.base.sha` and uses that snapshot's version as `VALIDATION_GAMEVER` for bin copy, restore,
invalidation, analysis, candidate comparison, gamedata, and C++ tests. The head `config.yaml`, preprocessors, Agent
skills, references, and tests are therefore checked against the last accepted symbol baseline. Building and publishing
the new `PR_GAMEVER` remains the responsibility of `build-on-self-runner.yml` after the source change is accepted.

## Authority Model

The lifecycle has three states:

```text
validated build output
        -> pending staged state
        -> merged/accepted state
        -> published Release state
```

- Candidate validation proves technical correctness.
- The generated-output PR is the review and repository-acceptance boundary.
- `PERSISTED_WORKSPACE/release-staging` is pending, non-authoritative state.
- `PERSISTED_WORKSPACE/bin/<GAMEVER>` is accepted cache state.
- `gamesymbols/<GAMEVER>.yaml` and `dist/` on the default branch are the canonical tracked outputs.
- GitHub Release is a distribution surface created only from accepted tracked output and the matching staged bin.

## End-to-End Flows

### New Game Version

```text
bump-download PR merged
        -> repository_dispatch(gamever, source_sha, mode=new)
        -> build and full candidate validation
        -> stage bin + manifest
        -> generated-output PR
        -> PR merged
        -> archive from OUTPUT_MERGE_SHA + staged bin
        -> promote persisted bin
        -> create GAMEVER tag at OUTPUT_MERGE_SHA
        -> create GitHub Release
```

The bump PR post-merge workflow must dispatch the build but must not create the tag.

### Rebuild Existing Game Version

```text
config/preprocessor/Agent changes merged to main
        -> project SKILL resolves origin/main to SOURCE_SHA
        -> workflow_dispatch(gamever, source_sha, mode=republish)
        -> affected-output invalidation + normal analyzer execution
        -> full candidate/gamedata/C++ validation
        -> generated-output PR
        -> PR merged
        -> archive and promote
        -> replace assets on existing GAMEVER Release
        -> existing GAMEVER tag remains unchanged
```

The Release is intentionally mutable in `republish` mode, but provenance is not: every accepted rebuild records the
new generator source and output merge commit.

## Build Trigger Contract

`build-on-self-runner.yml` supports two dispatch sources and no longer listens to `push.tags`.

### Automatic Dispatch

`repository_dispatch` keeps event type `build-on-self-runner` and uses this payload:

```json
{
  "gamever": "14170",
  "source_sha": "<40-hex bump PR merge SHA>",
  "mode": "new",
  "source_pull_request": 123
}
```

### Manual Dispatch

`workflow_dispatch` exposes only machine-oriented inputs used by the project SKILL:

- `gamever`: required version present in `download.yaml` at `source_sha`.
- `source_sha`: required full commit SHA; branches and symbolic refs are rejected by the workflow.
- `mode`: `new` or `republish`; manual use normally selects `republish`.

`analysis_policy=normal`, `invalidation_policy=affected`, and `validation_policy=full` are workflow invariants rather
than user-selectable switches. Reducing validation or forcing unrelated producers is not a release UI decision.

The workflow must validate the repository allowlist, `GAMEVER` syntax, full SHA syntax, commit reachability from the
default branch, `download.yaml` membership, and tag presence rules before using the self-hosted runner extensively.

## Build Workflow Design

1. Resolve `GAMEVER`, `SOURCE_SHA`, `MODE`, and `BUILD_ID=<run_id>-<run_attempt>` from the event.
2. Checkout exactly `SOURCE_SHA`; never checkout `GAMEVER` or `RELEASE_TAG` as the build source.
3. Copy persisted binaries/IDBs into a real workspace `bin`; keep only `cs2_depot` as a persisted link.
4. Prepare deterministic base state and apply the invalidation policy described below.
5. Run the existing analyzer with its normal producer selection, skip, and signature-reuse behavior.
6. Build one immutable candidate and run gamedata plus C++ validation against that candidate.
7. Publish the validated candidate into the working tree and generate tracked `dist/` output.
8. Write `release-manifests/<GAMEVER>.json` into the output commit.
9. Stage the validated bin and private manifest under `PERSISTED_WORKSPACE/release-staging`.
10. Create an immutable generated-output branch and PR, then write the PR-number index.
11. Stop. Do not archive, promote accepted bin, create a tag, or publish a Release in this workflow.

The branch name is `gamesymbols/build/<GAMEVER>/<BUILD_ID>`. It is never force-pushed after review begins. A new build
uses a new branch and staging directory. By default, another open generated-output PR for the same `GAMEVER` blocks a
new dispatch instead of silently superseding reviewed output.

## Invalidation Semantics

`republish` does not mean "execute every preprocessor" and does not automatically add `-oldgamever none`.

The rebuild flow restores the currently accepted snapshot, compares the previous accepted generator provenance with
the new `SOURCE_SHA`, and reuses the source-aware invalidation rules already designed for PR validation:

- Add, remove, or modify config producers and invalidate all outputs owned by affected producers.
- Map changed preprocessors, Agent SKILLs, references, and shared helpers to their affected producers.
- Compute transitive invalidation through expected-input/output and prerequisite relationships.
- Remove deleted outputs even when their producer no longer exists in the new config.
- Expand conservatively to affected modules or all modules only when a changed core analysis file cannot be mapped.
- Run `ida_analyze_bin.py` normally after invalidation; its existing logic decides what executes or skips.

`-oldgamever none` remains limited to `major_update: true` or another explicit semantic reason to prohibit old-signature
reuse. It is not implied by same-version republishing.

## Release Manifest And Pending State

### Tracked Manifest

Every output PR contains `release-manifests/<GAMEVER>.json`. This guarantees a reviewable PR even when regenerated
snapshot and gamedata bytes are unchanged, and preserves accepted provenance after staging cleanup.

Required fields:

```json
{
  "schema_version": 1,
  "gamever": "14170",
  "release_tag": "14170",
  "mode": "new",
  "build_id": "123456789-1",
  "source_sha": "<40-hex SHA>",
  "candidate_sha256": "<hex>",
  "bin_manifest_sha256": "<hex>",
  "tracked_output_manifest_sha256": "<hex>",
  "workflow_run_url": "https://github.com/.../actions/runs/..."
}
```

The tracked manifest must not contain local paths, secrets, timestamps used as identity, or `OUTPUT_MERGE_SHA`, which
does not exist until the PR is merged.

### Pending Layout

```text
PERSISTED_WORKSPACE/
  release-staging/
    <GAMEVER>/
      <BUILD_ID>/
        bin/<GAMEVER>/...
        manifest.json
        READY
    pr-index/
      <PR_NUMBER>.json
```

The private manifest includes the tracked fields plus repository identity, output branch, PR head SHA, file inventory,
sizes, and hashes. `READY` is written only after all staged files and manifests have been verified. The PR index is
written only after PR creation and binds PR number, head SHA, `GAMEVER`, and `BUILD_ID`.

## Generated-Output PR Contract

The PR may change only:

- `gamesymbols/<GAMEVER>.yaml`
- tracked files below `dist/`
- `release-manifests/<GAMEVER>.json`

The PR author, head repository, branch prefix, base branch, tracked manifest, pending PR index, and event head SHA must
all agree. Title text is informational and is never sufficient authorization.

The output PR must also be current with the exact build source. The default branch head immediately before merge must
equal `SOURCE_SHA`; otherwise the PR is stale and must be rebuilt from the new default-branch SHA. This intentionally
blocks merge even when intervening commits appear unrelated: the tag must not contain generator code that was not used
to produce its snapshot. Branch protection should require the generated-output branch to be up to date, and promotion
must independently verify the base-parent/source relationship before accepting the merge.

The existing `pr-self-runner.yml` may continue skipping these Bot PRs because the build already performed full
candidate validation. A lightweight required check should verify changed paths and tracked-manifest hashes without
rerunning every analyzer producer.

## Promotion Workflow

Add a dedicated workflow, for example `.github/workflows/promote-release-after-output-merge.yml`, triggered by
`pull_request.closed`. It runs only when all of these are true:

- `pull_request.merged == true`
- repository is allowlisted and head repository equals the base repository
- PR author is `github-actions[bot]`
- branch matches `gamesymbols/build/<GAMEVER>/<BUILD_ID>`
- base branch is the default branch
- PR index and private manifest exist and match the event head SHA
- merge diff contains only allowed generated-output paths

Promotion performs these steps:

1. Checkout exactly `pull_request.merge_commit_sha` with submodules.
2. Load the tracked manifest and matching private pending manifest.
3. Verify the merge base parent matches `SOURCE_SHA`, then verify snapshot, `dist/`, staged-bin inventory, candidate
   hash, and tracked-output hash.
4. Reconstruct the release workspace from the merge commit plus staged `bin/<GAMEVER>`.
5. Create archives and checksum/provenance files.
6. Promote staged bin transactionally into `PERSISTED_WORKSPACE/bin/<GAMEVER>`.
7. In `new` mode, create the lightweight `GAMEVER` tag at `OUTPUT_MERGE_SHA`; if it already exists elsewhere, stop.
8. In `republish` mode, require the tag and Release to exist and never move the tag.
9. Create the new Release or upload replacement assets with clobber semantics; Release publication is the final public
   commit point.
10. Mark promotion complete and clean or retain pending state according to the retention policy.

If the PR closes without merge, a cleanup job removes or expires only its pending staging state. It must not modify the
accepted bin, tag, or Release.

## Persisted Bin Promotion

Promotion must not merge files directly into a live directory with no rollback boundary. Build a verified sibling
directory first, then swap it into the accepted location while retaining the previous accepted directory as a recovery
backup until Release publication succeeds.

Path containment, repository/game-version identity, reparse-point rejection, exclusive per-version locking, and file
manifest verification are mandatory. If a target file is locked or the swap cannot complete, stop before publishing the
Release and preserve pending state for retry.

## Tag And Release Semantics

### `mode=new`

- `RELEASE_TAG == GAMEVER` must not exist before promotion.
- Create the tag at `OUTPUT_MERGE_SHA`, so the tag contains the accepted snapshot, gamedata, and tracked manifest.
- Create a new Release and upload `gamedata-<GAMEVER>.7z`, `gamebin-<GAMEVER>.7z`, checksums, and provenance.

### `mode=republish`

- The existing `GAMEVER` tag must exist and is never deleted, recreated, or force-moved.
- The generated-output PR updates the default branch and tracked manifest.
- Replace the existing Release assets idempotently and record `tag_sha`, `source_sha`, and `output_merge_sha` in the
  published provenance file and Release notes.

Remove the existing reusable retagging project SKILL when this workflow is enabled. Moving an
existing game-version tag contradicts the new release invariant, and keeping an explicit retagging entry point would
leave an obsolete and unsafe rebuild path available. Exceptional tag repair must be handled as a separately reviewed
repository-maintenance operation, not as a reusable project SKILL.

## Project-Level Trigger SKILL

Add `.claude/skills/trigger-release-build/` with:

```text
trigger-release-build/
  SKILL.md
  agents/openai.yaml
  scripts/trigger_release_build.py
```

The skill is a low-freedom remote-operation wrapper. It is explicitly invoked for requests such as:

- `重新发布 14170`
- `使用当前 main 重建 14170 的 release`
- `触发最新游戏版本的 release build`

The user supplies a game version or says "latest"; the user never supplies a SHA or types a `gh` command. The skill's
script must:

1. Locate the repository root and require the expected `origin` repository.
2. Verify `gh auth status` and permission to dispatch Actions.
3. Fetch `origin/main` and resolve it to an immutable full `SOURCE_SHA`.
4. Resolve `latest` from `download.yaml` at that SHA, or verify the requested `GAMEVER` exists there.
5. Require an existing tag/Release for the default `republish` operation.
6. Detect an open output PR or queued/in-progress build for the same `GAMEVER` and stop with its URL.
7. Execute the fixed command with resolved values:

```text
gh workflow run build-on-self-runner.yml --ref main \
  -f gamever=<GAMEVER> -f source_sha=<SOURCE_SHA> -f mode=republish
```

8. Discover and report the created Actions run URL, selected version, full source SHA, and commit subject.

The script must not move tags, edit releases, cancel runs, merge PRs, infer a different repository, accept a reduced
validation mode, or dispatch an unmerged/non-main source. A requested change must first be merged into `origin/main`.

Because dispatch changes remote state, the skill follows the repository convention of explicit invocation
(`disable-model-invocation: true` and `allow_implicit_invocation: false`). Reusable command construction and validation
belong in the script; `SKILL.md` remains a concise operator procedure.

## Concurrency And Idempotency

- Build concurrency key: repository plus `GAMEVER`, with `cancel-in-progress: false`.
- Promotion concurrency key: repository plus `GAMEVER`, also non-cancelling.
- An open output PR or ready pending build blocks another build for the same version by default.
- `BUILD_ID`, manifests, hashes, and PR head SHA make retries identify the same pending transaction.
- New-tag creation accepts an existing tag only when it already points to the expected `OUTPUT_MERGE_SHA`.
- Release replacement verifies all uploaded asset hashes; a partial upload remains retryable and does not mark promotion
  complete.
- Pending cleanup never runs before a successful promotion marker or an explicit unmerged-PR cleanup decision.

## Failure Recovery

- Build/validation failure: no PR, accepted bin, tag, or Release changes; retain diagnostics and expire incomplete staging.
- PR rejected or closed: delete/expire its pending state; accepted state remains unchanged.
- Archive failure: retain ready staging and retry promotion.
- Bin promotion failure: keep the previous accepted directory and do not publish Release assets.
- Tag creation failure: retain promoted/pending recovery state and retry after resolving permissions or conflicts.
- Release upload failure: keep staging, verify any partial assets, and rerun idempotently.
- Runner loss: recover exclusively from the tracked manifest, PR index, and persisted staging; never depend on the old
  GitHub Actions checkout directory surviving.

## Required File Changes

- Modify `.github/workflows/build-on-self-runner.yml` for dispatch-only checkout, invalidation, staging, manifest, and PR.
- Replace the tag-first behavior in `.github/workflows/tag-bump-after-merge.yml` with build dispatch after bump merge.
- Add `.github/workflows/promote-release-after-output-merge.yml`.
- Add release manifest/staging helper code with unit-testable path and hash validation.
- Add `release-manifests/<GAMEVER>.json` through generated-output PRs, not manual commits.
- Add `.claude/skills/trigger-release-build/` and its deterministic dispatch script.
- Remove the legacy reusable retagging SKILL, including its model metadata, and remove all repository references to it.
- Update workflow and skill tests to encode ordering, permissions, filters, and failure behavior.

## Test Plan

- Parse all workflow YAML and validate event/input contracts.
- Assert build checkout uses `SOURCE_SHA`, not a tag, and has no pre-merge archive/release/accepted-bin step.
- Test new-version and republish tag-presence guards.
- Test affected-output invalidation without unconditional preprocessor execution.
- Test manifest canonicalization, hash verification, path containment, and reparse-point rejection.
- Test PR changed-path allowlist and event/head/index identity mismatch failures.
- Test promotion ordering: verify, archive, bin promotion, tag handling, Release publication.
- Test unmerged PR cleanup cannot touch accepted state.
- Test retry after archive, promotion, tag, and partial Release-upload failures.
- Test the trigger script with mocked `git`/`gh`: latest resolution, requested version, auth failure, wrong repository,
  missing tag/Release, duplicate active build, dispatch arguments, and run URL reporting.
- Run repository unit tests, workflow-focused tests, formatter check, and a non-publishing smoke test before rollout.

## Rollout Plan

1. Add schemas, helper code, manifests, and tests without changing production release timing.
2. Add pending staging and generated-output PR identity while retaining the existing release path behind a temporary flag.
3. Add and dry-run the promotion workflow without tag/Release writes.
4. Add the project SKILL and validate it against a non-publishing dispatch mode or test repository.
5. Seed tracked provenance for existing releasable game versions, or mark the first republish as a one-time conservative
   baseline migration when no prior manifest exists.
6. Switch bump post-merge from tag creation to dispatch and remove tag-push triggering from the build workflow.
7. Enable promotion writes for one new game version and verify tag, archive, bin, manifest, and Release provenance.
8. Enable same-version republish, remove the obsolete reusable retagging SKILL, and verify no repository references to it
   remain.
9. Remove the temporary legacy release path after successful end-to-end verification.

## Acceptance Criteria

- A new game-version tag is absent until its generated-output PR is merged.
- A rejected/unmerged output PR cannot modify accepted persisted bin or Release state.
- A new tag points to the output PR merge commit containing snapshot, gamedata, and tracked release manifest.
- Promotion rejects an output PR when the default branch advanced beyond the exact `SOURCE_SHA` used by its build.
- Same-version republish uses a newer immutable `SOURCE_SHA`, updates tracked output through PR, replaces Release assets,
  and leaves the existing tag unchanged.
- Rebuild invalidation executes only affected producers under existing analyzer semantics; full downstream validation still
  runs against one immutable candidate.
- Build and promotion can recover without relying on a prior Actions checkout directory.
- Every published archive has verifiable game version, source SHA, output merge SHA, candidate hash, and bin manifest hash.
- Users can request a rebuild in natural language through the project SKILL without typing a command or SHA.
- The SKILL refuses wrong repositories, missing authentication, unknown versions, duplicate active work, and unsafe tag
  states before dispatching the workflow.
- The repository no longer contains a reusable SKILL or workflow that moves an existing game-version tag as a rebuild
  mechanism.
