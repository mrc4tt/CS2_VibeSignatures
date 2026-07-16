# Regression: release builds silently disable `oldgamever` reuse

## Summary

Release build `14168b` logged:

```text
Config file: D:\workspace\CS2_VibeSignatures\CS2_VibeSignatures\configs\14168b.yaml
Binary directory: bin
Game version: 14168b
Old game version: (disabled)
Platforms: windows, linux
Modules filter: *
Agent: ***
Debug mode: enabled
Parsing config...
Found 13 modules
```

Actions run:

<https://github.com/HLND2T/CS2_VibeSignatures/actions/runs/29493334656>

`14168b` is not a major update. The workflow correctly omitted the explicit
`-oldgamever none` argument, but it staged only `bin/14168b` in the build workspace.
The analyzer's automatic old-version resolver requires an eligible directory such
as `bin/14168` to already exist. Because no previous-version directory was staged,
resolution returned `None`, the analyzer printed `(disabled)`, and cross-version
signature reuse was skipped.

This is a release-workflow regression, not an incorrect major-update classification
inside `ida_analyze_bin.py`.

## Version Classification

`download.yaml` marks `14168` as a major update:

```yaml
- tag: "14168"
  name: 1.41.6.8
  manifests:
    "2347771": "1966178532936074640"
    "2347773": "8099352397812357222"
  major_update: true
```

The following `14168b` entry has no `major_update` flag:

```yaml
- tag: "14168b"
  name: 1.41.6.8
  manifests:
    "2347771": "2853479544375896262"
    "2347773": "2410782554857596728"
```

Major-update lookup uses an exact tag match. The `major_update: true` setting on
`14168` is not inherited by `14168b`. Therefore, treating `14168b` as a normal
non-major update is correct.

Relevant code:

- `download.yaml:155-165`
- `.github/workflows/build-on-self-runner.yml:196-209`
- `ida_analyze_bin.py:1154-1195`

## Control Flow

### 1. The workflow does not explicitly disable reuse

The analysis step reads the exact `GAMEVER` entry from `download.yaml` and adds
`-oldgamever none` only when that entry sets `major_update: true`:

```powershell
$args = @('-gamever', $env:GAMEVER, '-configyaml', $env:ANALYSIS_CONFIG)
if ($major -eq 'true') { $args += @('-oldgamever', 'none') }
$args += '-debug'
uv run ida_analyze_bin.py @args
```

For `14168b`, the effective invocation omitted `-oldgamever`:

```text
ida_analyze_bin.py -gamever 14168b -configyaml configs/14168b.yaml -debug
```

This part of the workflow behaves as intended.

Relevant code: `.github/workflows/build-on-self-runner.yml:193-212`.

### 2. The analyzer attempts automatic resolution

The `-oldgamever` CLI default is `None`. When the argument is omitted and the exact
target version is not a major update, argument parsing calls:

```python
args.oldgamever = resolve_oldgamever(args.gamever, args.bindir)
```

Relevant code: `ida_analyze_bin.py:1397-1402` and
`ida_analyze_bin.py:1430-1440`.

For a suffixed version such as `14168b`, `resolve_oldgamever()` checks candidates in
this order:

```text
14168a
14168
14167z ... 14167a
14167
```

It returns the first candidate whose directory exists under the configured binary
root. With the default `-bindir bin`, the expected baseline for this run would have
been `bin/14168` if that directory were present.

Relevant code: `ida_analyze_bin.py:1128-1151`.

### 3. The workflow stages only the current version

The workflow creates a real workspace `bin` directory, creates
`bin/$GAMEVER`, and copies only the same-version persisted directory:

```powershell
$workspaceGamever = Join-Path $workspaceBin $env:GAMEVER
New-Item -ItemType Directory -Path $workspaceGamever -Force | Out-Null
$persistedGamever = Join-Path $env:PERSISTED_WORKSPACE "bin\$env:GAMEVER"
if (Test-Path -LiteralPath $persistedGamever -PathType Container) {
  robocopy $persistedGamever $workspaceGamever /E /COPY:DAT /DCOPY:DAT /R:2 /W:5
}
```

For the new `14168b` build, this made `bin/14168b` available but did not make
`bin/14168` available. Depot download and copy steps also target only the requested
`GAMEVER`.

Relevant code:

- `.github/workflows/build-on-self-runner.yml:125-138`
- `.github/workflows/build-on-self-runner.yml:172-191`
- `copy_depot_bin.py:188-195`

### 4. Resolution fails closed to disabled reuse

With none of the candidate directories present, `resolve_oldgamever()` returns
`None`. Configuration output renders a falsey value as:

```python
print(f"Old game version: {args.oldgamever or '(disabled)'}")
```

Downstream old-binary lookup immediately returns `None` when `args.oldgamever` is
unset, so old-version YAML/signature reuse does not occur.

Relevant code:

- `ida_analyze_bin.py:3655-3659`
- `ida_analyze_bin.py:3689-3698`

## Root Cause

Automatic old-version selection is filesystem-driven, but the release workflow no
longer exposes the persisted old-version directories to the analyzer.

Earlier workflow behavior linked the workspace `bin` to the full persisted `bin`
tree, which incidentally made prior versions visible to `resolve_oldgamever()`.
Commit `1e3246190f6bd50b06c7bf3700ef8261a66baa5e`
(`feat(gamesymbols): track deterministic symbol snapshots`) changed the workspace
to use a real `bin` directory and copy only the current version. That isolation is
desirable for deterministic candidate handling, but no explicit old-version
baseline restoration replaced the visibility provided by the old link.

Commit `07d420be91ece88978279d9fcc98170da746ba39`
(`feat(release): gate publication on generated output merge`) retained the
current-version-only workspace setup while continuing to rely on analyzer
auto-resolution for non-major builds.

The resulting mismatch is:

```text
Workflow policy: omit -oldgamever none for non-major updates
Analyzer policy: select an old version only when bin/<candidate> exists
Workspace policy: stage only bin/<current GAMEVER>
Result: non-major release builds silently run with oldgamever disabled
```

## Impact

- Non-major release builds can lose cross-version signature reuse without failing.
- The log says `(disabled)`, but does not explain that the expected baseline was
  unavailable.
- Producers that depend on old binary/YAML state may do more work or lose a useful
  recovery path.
- Build behavior diverges from the release design, which says normal builds should
  retain existing signature-reuse behavior.
- A successful build can conceal the regression because disabled reuse is currently
  treated as valid analyzer behavior.

This does not mean the `14168b` output is automatically invalid. It means the build
did not use the previous-version reuse baseline expected for a non-major update.

## Design Mismatch

The release workflow plan states that the analyzer should run with its normal
signature-reuse behavior:

- `docs/plans/new-release-workflow.md:141-146`
- `docs/plans/new-release-workflow.md:159-172`

The candidate snapshot design is more explicit for new-version builds:

```text
Prepare real workspace bin/<GAMEVER>.
Restore reuse baseline from a trusted old-version snapshot, or disable reuse for a
major update according to policy.
```

Relevant documentation:
`docs/plans/candidate-snapshot-as-symbol-store.md:1093-1104`.

The current workflow performs the first step but not the second.

## Test Coverage Gap

`tests/test_build_self_runner_workflow.py:38-40` verifies that the workflow adds
`-oldgamever none` only for major updates. It does not verify that a non-major build
stages a usable old-version baseline.

As a result, the tests cover the explicit-disable branch but not the successful
automatic-reuse branch.

## Suggested Fix Direction

The implementation should preserve the real workspace `bin` isolation while
explicitly restoring a trusted previous-version baseline for non-major builds.
Possible approaches should be evaluated against persisted-state trust and snapshot
provenance requirements rather than simply restoring the old whole-directory link.

At minimum, the corrected flow should:

1. Determine whether the exact target `GAMEVER` is a major update.
2. For a major update, continue to pass `-oldgamever none` explicitly.
3. For a non-major update, deterministically select the expected previous version.
4. Restore or copy that version's trusted binary/YAML baseline into
   `bin/<OLDGAMEVER>` before invoking `ida_analyze_bin.py`.
5. Pass `-oldgamever <OLDGAMEVER>` explicitly, or verify that analyzer
   auto-resolution selects the staged version.
6. Fail with a clear safety error if reuse is expected but no trusted baseline can
   be provided, unless an explicit policy permits proceeding without reuse.
7. Keep candidate output and current-version persisted writes isolated from the
   read-only old-version baseline.

Using a tracked `gamesymbols/<OLDGAMEVER>.yaml` snapshot may satisfy YAML reuse but
must be evaluated against any consumers that require old binary or IDA database
files. The fix should identify exactly which old-version artifacts
`process_binary()` and its preprocessors require before choosing the restoration
source.

## Acceptance Criteria

- A non-major build for `14168b` selects `14168` when the trusted `14168` baseline
  is available.
- Analyzer startup logs `Old game version: 14168`, not `(disabled)`.
- A version marked `major_update: true` still logs `(disabled)` and receives no old
  baseline.
- Missing required baseline state produces an intentional, explanatory result
  rather than silently disabling reuse.
- Workflow tests verify both major-update disabling and non-major baseline staging.
- Republish behavior remains source-aware and does not disable reuse merely because
  `mode=republish`.
- The old baseline is read-only input and cannot be accidentally published as the
  current version's candidate state.

## Open Questions

- What is the authoritative trusted source for an old-version baseline: persisted
  runner state, a tracked `gamesymbols/<GAMEVER>.yaml` snapshot, release assets, or
  a combination?
- Does signature reuse require only YAML metadata, or do any producers require the
  old binary/IDB directory to be present?
- Should a missing baseline fail every non-major release build, or should there be
  a separately explicit and audited no-reuse mode?
- Should old-version selection remain duplicated between workflow logic and
  `ida_analyze_bin.py`, or should one shared resolver define the version and required
  artifacts?
- How should a suffixed predecessor such as `14168a` be handled when it exists in
  persisted state but has no accepted tracked snapshot?
