# Generated-Output Branch Protocol Migration

## Status

Proposed atomic migration.

This plan changes the generated-output branch protocol from:

```text
gamesymbols/<GAMEVER>/build-<BUILD_ID>
```

to:

```text
gamesymbols/build/<GAMEVER>/<BUILD_ID>
```

For example:

```text
gamesymbols/14168/build-29683665467-1
    -> gamesymbols/build/14168/29683665467-1
```

The migration must be merged as one repository change. Every branch producer, duplicate-work
guard, event filter, parser, validation path, promotion path, test, and current operational
document switches together. There is no production window in which new builds may choose
between the two formats.

## Background

The current protocol places the version directly below `gamesymbols/` and then treats that
version ref as a parent namespace:

```text
refs/heads/gamesymbols/14168/build-29683665467-1
```

Historical generated-output PRs used leaf branches such as `gamesymbols/14168`. A persistent
self-hosted runner can retain that local ref after the remote branch is deleted. Git cannot
store both of these refs at the same time:

```text
refs/heads/gamesymbols/14168
refs/heads/gamesymbols/14168/build-29683665467-1
```

The leaf ref occupies the filesystem path that the newer nested ref needs as a directory.
Release build run `29683665467` demonstrated this failure while republishing `14168`:

```text
fatal: cannot lock ref 'refs/heads/gamesymbols/14168/build-29683665467-1':
'refs/heads/gamesymbols/14168' exists; cannot create
'refs/heads/gamesymbols/14168/build-29683665467-1'
```

The target protocol reserves `gamesymbols/build/` for generated-output branches and moves
`GAMEVER` below that stable namespace:

```text
refs/heads/gamesymbols/build/14168/29683665467-1
```

Legacy branches such as `refs/heads/gamesymbols/14168` are siblings of the reserved `build`
namespace and therefore no longer block branch creation.

## Decision Summary

The canonical generated-output branch identity becomes:

```text
gamesymbols/build/<GAMEVER>/<BUILD_ID>
```

with the following component contracts:

- `GAMEVER` continues matching `[0-9]{4,10}[a-z]?`.
- `BUILD_ID` continues matching `[0-9]+-[0-9]+` and remains
  `<github.run_id>-<github.run_attempt>`.
- The literal `build-` prefix is removed from the `BUILD_ID` path component because `build`
  is now the dedicated namespace component.
- The canonical regular expression becomes:

  ```regex
  ^gamesymbols/build/(?P<gamever>[0-9]{4,10}[a-z]?)/(?P<build_id>[0-9]+-[0-9]+)$
  ```

- New producers emit only the new protocol.
- Promotion and release-workflow validation accept only the new protocol after cutover.
- Duplicate-work guards recognize both protocols as blockers during and after cutover so an
  unexpected surviving legacy PR cannot permit a concurrent build.
- Historical merged or closed branches may remain on GitHub; they are not rewritten or
  deleted as part of this migration.
- Tracked snapshot paths remain `gamesymbols/<GAMEVER>.yaml`. This migration changes Git
  branch refs only, not repository file paths.

## Goals

- Eliminate parent/child ref collisions with historical `gamesymbols/<GAMEVER>` branches.
- Define a stable reserved namespace for all generated-output branches.
- Preserve the existing immutable build identity, PR review boundary, pending staging model,
  and promotion security checks.
- Keep same-version duplicate detection fail closed across the migration boundary.
- Make event routing specific enough that ordinary or historical `gamesymbols/*` branches are
  not mistaken for generated-output branches.
- Keep `parse_output_branch()` as the authoritative Python parser for staging and promotion.
- Make the cutover operationally atomic: no old-format build or PR remains active when the
  migrated workflow becomes authoritative.

## Non-Goals

- Do not rename `gamesymbols/<GAMEVER>.yaml` snapshot files.
- Do not change `release-manifests/<GAMEVER>.json`, `configs/<GAMEVER>.yaml`, or
  `bin/<GAMEVER>` paths.
- Do not change `GAMEVER`, `BUILD_ID`, `SOURCE_SHA`, mode, tag, or Release semantics.
- Do not add force-push, branch reuse, or mutable generated-output branches.
- Do not automatically delete historical remote branches merely because they use the old
  protocol.
- Do not make branch titles or PR titles an authorization source.
- Do not introduce a permanent dual-protocol parser in staging or promotion.
- Do not use broad runner cleanup as a substitute for the namespace migration.

## Core Invariants

The implementation must preserve all of the following invariants:

1. One release build has exactly one canonical output branch derived from its validated
   `GAMEVER` and `BUILD_ID`.
2. The output branch is created once and is never force-pushed after review begins.
3. The branch, tracked release manifest, pending manifest, PR index, event head SHA, and
   staged directory continue identifying the same build transaction.
4. A generated-output PR for the same `GAMEVER` blocks another dispatch regardless of
   whether the surviving PR uses the old or new branch protocol.
5. Promotion accepts only bot-authored, same-repository PRs whose branch exactly matches the
   post-migration protocol.
6. Invalid, extra-segment, traversal-like, legacy, or partially migrated branch names fail
   closed.
7. The promotion concurrency identity is still derived from the validated `GAMEVER`, not
   from title text or an unvalidated string split.
8. Existing accepted snapshots, releases, tags, persisted bin, and release manifests do not
   change solely because the branch protocol changes.
9. No old-format build remains queued, running, open, or ready in pending staging at the
   cutover boundary.
10. The exact leaf ref `refs/heads/gamesymbols/build` is reserved and must not exist locally
    or remotely when the new protocol is activated.

## Atomic Cutover Policy

### No Dual-Write Period

The migration may be developed through multiple local commits, but the mergeable repository
state changes atomically:

- the producer emits the new format;
- all strict parsers accept the new format and reject the old format;
- workflow filters route only the new namespace;
- duplicate guards still detect an old open PR and stop;
- tests and current documentation describe the new format.

No production flag selects the old format. A partially migrated branch must not be merged to
the default branch.

### Drain Before Cutover

Immediately before merging the migration, verify all of the following against current remote
state:

1. No `build-on-self-runner.yml` run is queued or in progress.
2. No open generated-output PR uses
   `gamesymbols/<GAMEVER>/build-<BUILD_ID>`.
3. No open generated-output PR uses the new namespace from an experimental run.
4. No ready pending staging entry is waiting for an old-format PR to merge.
5. No exact local or remote branch named `gamesymbols/build` occupies the new parent
   namespace.

If an old-format PR is open, either complete its promotion before cutover or close it and run
the existing indexed unmerged cleanup. Do not merge the protocol migration while an old PR
still depends on the old promotion parser.

The drain check must be repeated after required checks pass and immediately before merge to
close the race with a newly dispatched release build. If release dispatch cannot be
temporarily frozen, the migration PR must not merge until the active-run and open-PR queries
remain clean at the final check.

### Legacy Pending State

The tracked release manifest does not record `output_branch`, but the private pending
manifest and PR index do. Because cutover requires no old ready transaction, their schema
does not need a compatibility version bump for this migration.

Any orphaned, incomplete staging directory without a valid indexed PR must be handled using
the existing release-workflow cleanup/recovery rules. It must not be silently reinterpreted
as a new-format transaction.

## Required Repository Changes

### Canonical Python Branch Contract

Update `release_workflow_lib/manifests.py`:

- Replace `BRANCH_RE` with the new strict regular expression.
- Add a small `format_output_branch(gamever, build_id)` helper so Python tests and future
  Python producers do not reconstruct the protocol ad hoc.
- Validate `GAMEVER` and `BUILD_ID` before formatting.
- Keep `parse_output_branch(branch) -> tuple[str, str]` unchanged as an API so staging and
  promotion callers continue receiving `(gamever, build_id)`.
- Add positive and negative parser tests, including explicit rejection of the old protocol.

`release_workflow_lib/staging.py` and `release_workflow_lib/promotion.py` should continue
calling `parse_output_branch()`. They should not parse path segments independently. Their
behavior changes through the canonical parser without changing staging or promotion data
models.

### Build Workflow Producer

Update `.github/workflows/build-on-self-runner.yml`:

- Generate:

  ```powershell
  OUTPUT_BRANCH=gamesymbols/build/$env:GAMEVER/$env:BUILD_ID
  ```

- Change the canonical same-version open-PR prefix to:

  ```text
  gamesymbols/build/<GAMEVER>/
  ```

- Retain a legacy-prefix query for
  `gamesymbols/<GAMEVER>/build-` as a safety blocker. If found, fail with an explicit message
  that the legacy output PR must be resolved before dispatch.
- Keep branch creation, commit, push, PR creation, stage finalization, and PR-index ordering
  unchanged.
- Keep the no-force-push invariant.

The build workflow does not need to delete `gamesymbols/<GAMEVER>` local branches after this
migration because those refs no longer conflict with the target namespace. During cutover,
the exact reserved parent `gamesymbols/build` must be checked separately.

### Manual Trigger Duplicate Guard

Update
`.claude/skills/trigger-release-build/scripts/trigger_release_build.py`:

- Detect canonical open output PRs with
  `gamesymbols/build/<GAMEVER>/`.
- Continue detecting old open output PRs with
  `gamesymbols/<GAMEVER>/build-` and reject dispatch with a migration-specific safety error.
- Keep active Actions-run detection unchanged.
- Keep mode derivation, immutable `origin/main` SHA selection, tag/Release checks, and legacy
  bootstrap authorization unchanged.

The trigger script must not accept a user-supplied branch name and must not delete any branch.

### Workflow Event Routing

Tighten generated-output event filters from:

```text
startsWith(github.event.pull_request.head.ref, 'gamesymbols/')
```

to:

```text
startsWith(github.event.pull_request.head.ref, 'gamesymbols/build/')
```

in these workflows:

- `.github/workflows/validate-generated-output-pr.yml`
- `.github/workflows/promote-release-after-output-merge.yml`
- both generated-output skip filters in `.github/workflows/pr-self-runner.yml`

This prevents a legacy branch such as `gamesymbols/14168` from being routed as a modern
generated-output PR merely because it shares the broad top-level prefix.

### Promotion Identity Resolution

Update the strict PowerShell regular expression in
`.github/workflows/promote-release-after-output-merge.yml` to:

```regex
^gamesymbols/build/(?<gamever>[0-9]{4,10}[a-z]?)/(?<build_id>[0-9]+-[0-9]+)$
```

The workflow currently needs to resolve `GAMEVER` before the self-hosted promotion job so it
can construct the per-version concurrency group. That early workflow boundary cannot simply
reuse an in-process Python function without first checking out trusted tooling. Retain the
small workflow regex, but add contract tests that exercise the same accepted and rejected
branch corpus as `parse_output_branch()`.

The later `verify-output-pr` and `verify-promotion` commands continue performing the
authoritative Python validation from trusted base tooling. The early regex is routing and
concurrency identity validation, not a replacement for those checks.

### Pending State And Promotion

No tracked release-manifest schema change is required because the tracked manifest does not
contain the branch name. The private pending manifest continues recording `output_branch`,
now using the new canonical value.

Verify through tests that:

- `stage-build` rejects an old-format output branch;
- the branch still matches the supplied `GAMEVER` and `BUILD_ID`;
- `verify-output-pr` derives the correct version and build from the new format;
- `verify-promotion` matches the PR event branch to the indexed pending transaction;
- unmerged cleanup remains keyed by PR number and event head SHA, not by loose branch-prefix
  deletion.

### Tests

Update at least these test surfaces:

- `tests/test_release_workflow.py`
- `tests/test_release_workflow_guards.py`
- `tests/test_build_self_runner_workflow.py`
- `tests/test_trigger_release_build.py`
- `tests/test_pr_self_runner_workflow.py`

Add a shared branch-protocol fixture corpus where practical. It must include:

Accepted examples:

```text
gamesymbols/build/14168/29683665467-1
gamesymbols/build/14168b/1-2
```

Rejected examples:

```text
gamesymbols/14168/build-29683665467-1
gamesymbols/14168
gamesymbols/build
gamesymbols/build/14168
gamesymbols/build/14168/build-29683665467-1
gamesymbols/build/14168/29683665467
gamesymbols/build/not-a-version/29683665467-1
gamesymbols/build/14168/29683665467-1/extra
```

Required behavioral tests include:

- the build workflow emits only the new branch format;
- current workflow files contain no executable old-format producer;
- promotion extracts `14168` and `29683665467-1` from the new format;
- promotion rejects the old format;
- generated-output event filters use `gamesymbols/build/`;
- PR self-runner skips only canonical generated-output bot PRs;
- a new-format open PR blocks duplicate dispatch;
- an old-format open PR also blocks dispatch with a migration-specific error;
- an unrelated `gamesymbols/<GAMEVER>` branch does not count as an active output PR;
- staging and promotion identity mismatch guards still fail closed.

### Documentation And Memory

Update current architecture and operational guidance after implementation:

- `docs/plans/new-release-workflow.md`
- `.serena/memories/build-on-self-runner.md`
- any current skill or README text found by the final repository-wide protocol search

Historical incident records and superseded plans may retain the old format when clearly
describing historical behavior. Current executable guidance must use the new format.

### External Repository Settings

Before rollout, inspect GitHub settings that are not represented by repository files:

- branch protection rules or repository rulesets matching the old branch pattern;
- required-check rules scoped by generated-output branch name;
- external bots or integrations filtering on `gamesymbols/<GAMEVER>/build-*`;
- branch cleanup automation.

Any rule that currently targets the old protocol must switch to an equivalent pattern for:

```text
gamesymbols/build/*/*
```

Repository rules must be updated in the same cutover window. If the platform cannot update
the rule atomically with the merge, update the rule first only when doing so does not weaken
protection for existing branches, then merge immediately after the final drain check.

## Ref Namespace Safety

The new hierarchy intentionally avoids all historical per-version leaf refs:

```text
refs/heads/gamesymbols/14168
refs/heads/gamesymbols/14169
refs/heads/gamesymbols/build/14168/29683665467-1
```

These refs can coexist because `14168`, `14169`, and `build` are siblings below
`refs/heads/gamesymbols/`.

The remaining namespace hazard is an exact leaf ref named:

```text
refs/heads/gamesymbols/build
```

The cutover check must query both remote and the persistent runner checkout for this exact
ref. If a remote ref exists, stop and resolve it explicitly. If only a stale local ref exists,
record its SHA and remove it only after confirming it is not checked out by any worktree and
has no remote counterpart. Do not perform broad deletion below `refs/heads/gamesymbols`.

## Implementation Sequence

Although development may use intermediate commits, the reviewable and mergeable result is
atomic. The recommended implementation order is:

1. Add new-format parser/formatter tests and negative tests for the old format.
2. Change the canonical Python regex and add `format_output_branch()`.
3. Update release-workflow fixtures and staging/promotion guard tests.
4. Update the build workflow output branch producer and dual-format duplicate blocker.
5. Update the manual trigger script duplicate blocker and tests.
6. Tighten generated-output event filters to `gamesymbols/build/`.
7. Update promotion identity extraction and workflow contract tests.
8. Update current release documentation and Serena memory references.
9. Run a repository-wide search for executable old-protocol assumptions and remove all
   remaining producers, parsers, and filters.
10. Run targeted and full validation.
11. Inspect external GitHub branch rules and prepare the cutover update.
12. Drain active old-protocol work, repeat the final remote-state checks, update external
    rules if required, and merge the migration as one cutover.

Steps 1-9 must not be merged independently. If temporary dual-format code is useful during
development, remove it before review except for the deliberate old-format duplicate blocker.

## Validation Plan

### Static Protocol Search

Search executable code, workflows, skills, tests, and current documentation for the old
protocol. Remaining old-format strings must be limited to:

- explicit rejection tests;
- duplicate safety detection;
- historical explanation in this migration plan or superseded documentation.

Search separately for broad event filters using `gamesymbols/` and verify each remaining use
is intentional. Generated-output routing must use `gamesymbols/build/`.

### Targeted Tests

Run the workflow and release-focused tests covering:

- canonical branch parsing and formatting;
- stage-build branch binding;
- output PR verification;
- promotion verification;
- build workflow generation and ordering;
- trigger-script duplicate detection;
- PR self-runner routing exclusions.

### Repository Gates

Run at minimum:

```powershell
uv run ruff check release_workflow_lib/manifests.py release_workflow_lib/staging.py `
  release_workflow_lib/promotion.py `
  .claude/skills/trigger-release-build/scripts/trigger_release_build.py `
  tests/test_release_workflow.py tests/test_release_workflow_guards.py `
  tests/test_build_self_runner_workflow.py tests/test_trigger_release_build.py `
  tests/test_pr_self_runner_workflow.py

uv run python format_repo_files.py --check

uv run python -m unittest discover -s tests -b
```

Also validate representative ref names locally:

```powershell
git check-ref-format --branch "gamesymbols/build/14168/29683665467-1"
git check-ref-format --branch "gamesymbols/build/14168b/1-2"
```

No publishing smoke test may bypass the normal trigger skill or promotion gate.

## Rollout Plan

1. Complete the implementation and repository validation on a development branch.
2. Confirm the exact target namespace `gamesymbols/build` is free locally and remotely.
3. Confirm there are no queued or running release builds.
4. Confirm there are no open old-format or experimental new-format generated-output PRs.
5. Confirm no old ready pending transaction requires future promotion.
6. Update external GitHub rulesets or branch protection patterns if required.
7. Repeat steps 2-5 immediately before merge.
8. Merge the complete protocol migration into the default branch.
9. Trigger the next authorized release build only through the project release skill.
10. Verify the run reports an output branch matching
    `gamesymbols/build/<GAMEVER>/<BUILD_ID>`.
11. Verify the generated-output PR receives the lightweight validation check and is excluded
    from duplicate self-runner validation as intended.
12. Merge the output PR only after validation, then verify promotion resolves the correct
    `GAMEVER`, consumes the matching pending state, and completes publication.

The first post-cutover build is the end-to-end rollout verification. Failure before PR
creation leaves no accepted-state change. Failure after PR creation must follow the rollback
rules below.

## Rollback And Failure Recovery

### Before Any New-Format PR Exists

If the migrated workflow fails before staging or PR creation, fix forward when practical. A
repository revert is safe only if no new-format pending transaction or PR exists and external
branch rules are restored consistently.

### After A New-Format PR Exists

Do not revert the protocol while a new-format PR or ready pending transaction exists. The old
promotion parser would not recognize that branch. Choose one of these paths:

1. Keep the migration deployed, fix forward, and complete validation/promotion.
2. Close the new-format PR, run indexed unmerged cleanup, verify its pending state is gone,
   then revert the migration and external rules together.

Never rename or force-push an existing generated-output branch to cross protocols. Rebuild
from a fresh immutable `SOURCE_SHA` and `BUILD_ID` instead.

### Unexpected Legacy PR After Cutover

If an old-format PR is discovered after cutover:

- duplicate guards must block new dispatches for that `GAMEVER`;
- promotion must not accept the old branch under the new parser;
- close and clean it, or temporarily halt release work and complete an explicitly reviewed
  recovery using tooling from its original trusted base;
- do not weaken the canonical parser to accept both formats permanently.

## Acceptance Criteria

The migration is complete only when all of the following are true:

- Every newly generated output branch matches
  `gamesymbols/build/<GAMEVER>/<BUILD_ID>`.
- No production producer emits `gamesymbols/<GAMEVER>/build-<BUILD_ID>`.
- `parse_output_branch()` accepts the new protocol and rejects the old protocol.
- Staging and promotion derive the same `GAMEVER` and `BUILD_ID` from the new branch.
- Promotion workflow identity resolution uses the new strict regex.
- Generated-output workflow filters use the reserved `gamesymbols/build/` prefix.
- A canonical open output PR blocks another build for the same `GAMEVER`.
- A surviving old-format open output PR also blocks dispatch and produces an explicit safety
  error.
- A historical leaf branch such as `gamesymbols/14168` no longer prevents creation of a new
  output branch for `14168`.
- The exact parent ref `gamesymbols/build` is absent locally and remotely.
- No old-format run, open PR, or ready pending transaction remains at cutover.
- Existing snapshot paths, release manifests, tags, Releases, and accepted persisted bin are
  unchanged by the migration.
- Workflow contract tests, release-workflow tests, formatter checks, lint, and the full unit
  test suite pass.
- Current release documentation and Serena memory describe only the new canonical protocol.
- The first authorized post-cutover build creates, validates, promotes, and publishes through
  the new branch protocol without manual branch cleanup.
