# Versioned Analysis Config Migration

> Superseded note: `snapshot_version.md` 仅对普通 PR baseline replay 放宽 historical fallback digest/schema/
> contract mismatch，改为 warning + clean bootstrap。显式 restore、HEAD/candidate comparison、release promotion
> 与 republish 仍按本文 fail closed。

## Status

Proposed atomic migration.

This plan moves the repository's analysis configuration from the mutable root-level
`config.yaml` to versioned files under `configs/<GAMEVER>.yaml`. The migration must be
implemented as one atomic repository change: every runtime consumer, workflow, historical
lookup, release guard, test, and current developer procedure switches together, and the
root `config.yaml` is removed in the same change.

The migration also changes the new-version lifecycle. Whenever the `bump-download` workflow
adds a new `download.yaml` entry, the same bump commit must create the corresponding
`configs/<NEW_GAMEVER>.yaml`. A new `GAMEVER` must never be merged or dispatched without its
analysis config.

## Background

`config.yaml` is currently a shared mutable input to binary discovery, IDA analysis,
candidate packing, snapshot validation, gamedata generation, C++ layout validation, PR
invalidation, scheduler workers, and release republishing. Most entry points either default
directly to `config.yaml` or contain an internal hardcoded lookup of that file.

That model conflicts with the repository's versioned artifacts:

```text
bin/<GAMEVER>/
gamesymbols/<GAMEVER>.yaml
release-manifests/<GAMEVER>.json
```

The repository already demonstrates that the analysis config is version-specific:

- `configs/14167.yaml` has the normalized contract digest recorded by
  `gamesymbols/14167.yaml`.
- The current root `config.yaml` has the normalized contract digest recorded by
  `gamesymbols/14168.yaml`.
- Opening a historical snapshot with the current root config can therefore fail contract
  validation or, for config fields not covered by the normalized digest, silently apply the
  wrong symbol or C++ test definitions.

The current split is incomplete. No production resolver selects `configs/<GAMEVER>.yaml`,
and several paths continue to rediscover root `config.yaml` even when a caller explicitly
passes another config.

## Decision Summary

The canonical analysis-config identity becomes:

```text
GAMEVER + SOURCE_SHA + configs/<GAMEVER>.yaml
```

The target repository layout is:

```text
configs/
  14167.yaml
  14168.yaml
  14168b.yaml
  14169.yaml
  14170.yaml
  <future GAMEVER>.yaml
gamesymbols/
  14167.yaml
  14168.yaml
bin/
  <GAMEVER>/...
```

The runtime resolution rule is strict:

1. An explicit analysis-config argument wins.
2. Otherwise, the command resolves `configs/<GAMEVER>.yaml` from the repository root.
3. If the selected file does not exist, the command fails.
4. Current-worktree runtime commands never fall back to root `config.yaml`, another
   `GAMEVER`, or the nearest existing config.
5. Historical Git lookup may fall back to `config.yaml` only when reading a commit that
   predates this migration, and the selected historical config must still validate against
   the relevant snapshot or release provenance.

The root `config.yaml` is removed. There is no long-lived duplicate, symlink, generated
forwarder, or compatibility copy at the repository root.

## Goals

- Make every analysis, snapshot, downstream, and release operation select its config from
  the same `GAMEVER`.
- Preserve explicit scratch-config workflows such as `-configyaml _scratch.yaml`.
- Fail closed when a version config is missing instead of silently using a different
  version's contract.
- Preserve exact historical config selection for snapshot restore, PR base validation, and
  republish invalidation.
- Ensure the `bump-download` PR creates `configs/<NEW_GAMEVER>.yaml` in the same commit as
  the new `download.yaml` entry.
- Keep the existing PR boundary: an ordinary bump PR validates against the accepted
  `VALIDATION_GAMEVER`; the new version is built only after the bump PR is merged.
- Preserve current analyzer scheduling, old-version signature reuse, candidate immutability,
  and generated-output PR boundaries.
- Make release provenance identify both the normalized analysis contract and the exact full
  config file bytes.
- Preserve existing repository-root-relative C++ paths after moving the YAML file into
  `configs/`.

## Non-Goals

- Do not merge `download.yaml` and analysis configs into one schema.
- Do not rename downstream overlay files such as `dist/*/config.yaml`.
- Do not reinterpret `download_depot.py -config download.yaml`; that option remains the
  download-manifest path.
- Do not automatically infer semantic config changes from a CS2 update. A newly copied
  config is an initial baseline reviewed in the bump PR, not a claim that no changes are
  needed.
- Do not synthesize purportedly historical configs for every old `download.yaml` entry when
  the exact historical file cannot be recovered.
- Do not add `configs/<GAMEVER>.yaml` to the generated-output PR. It is generator source and
  belongs to the bump/source commit.
- Do not change the snapshot's existing normalized `config_sha256` semantics as part of this
  migration. Exact full-file identity is recorded separately in release provenance.

## Terminology

### Analysis Config

The top-level config containing `modules`, skills, symbols, and `cpp_tests`. Its canonical
current-worktree path is `configs/<GAMEVER>.yaml`.

### Download Config

`download.yaml`, containing game tags and depot manifests. This is not an analysis config.

### Overlay Config

The downstream project-specific files under `dist/*/config.yaml`. They remain local to each
downstream generator and are not version-selected by the new resolver.

### Runtime Resolution

Selecting a config from the checked-out working tree for a command that already knows its
`GAMEVER`.

### Historical Resolution

Selecting config bytes from a specific Git revision, usually a previous accepted
`SOURCE_SHA` or the commit that published a base snapshot.

### Config Seed

The exact byte-for-byte copy used to initialize `configs/<NEW_GAMEVER>.yaml` from the
immediately preceding default-branch game version during an automated bump.

## Core Invariants

The implementation must maintain all of the following invariants:

1. Every command that consumes the analysis config also has an unambiguous `GAMEVER` before
   resolving its default config.
2. One analysis transaction uses one resolved absolute config path from binary copy through
   analysis, candidate build, gamedata, and C++ validation.
3. `configs/<GAMEVER>.yaml`, `gamesymbols/<GAMEVER>.yaml`, and `bin/<GAMEVER>` always refer to
   the same game version.
4. A missing current-worktree version config is a hard error.
5. An explicit config path is never silently replaced by the versioned default.
6. Explicit relative config paths remain relative to the caller's current working directory,
   preserving `_scratch.yaml` and temporary-test behavior.
7. Implicit versioned config paths are anchored to the repository root, not the process
   current working directory.
8. Internal helpers do not rediscover a config independently after the entry point resolves
   it.
9. Config-relative movement does not change the meaning of repository source paths in
   `cpp_tests`.
10. A bump commit that adds a new download tag also adds exactly one matching version config.
11. The automated bump never overwrites a pre-existing target version config.
12. Recovery dispatch for an already accepted download entry never creates or modifies its
    config; it requires the config to exist before dispatch.
13. Historical root-config fallback is read-only, revision-scoped, and validated. It is not
    available to current runtime commands.
14. Release archives contain the exact config bytes from the recorded `SOURCE_SHA`, not an
    unrelated later version of the same path from `OUTPUT_MERGE_SHA`.

## Shared Config Resolver

Add a small shared module, for example `analysis_config.py`, that owns path construction,
validation, and full-file hashing.

The public runtime API should be equivalent to:

```python
from pathlib import Path


class AnalysisConfigError(RuntimeError):
    pass


def analysis_config_repo_path(gamever: str) -> str:
    """Return configs/<GAMEVER>.yaml using validated repository-relative syntax."""


def default_analysis_config_path(gamever: str, *, repo_root: Path | None = None) -> Path:
    """Return the repository-root-anchored default path."""


def resolve_analysis_config(
    gamever: str,
    explicit_path: str | Path | None = None,
    *,
    repo_root: Path | None = None,
) -> Path:
    """Resolve and require one current-worktree analysis config."""


def analysis_config_sha256(path: str | Path) -> str:
    """Return the SHA-256 of the exact file bytes."""
```

Resolution behavior:

```text
explicit_path supplied
    -> expand user syntax
    -> if relative, anchor to Path.cwd()
    -> resolve absolute path
    -> require a plain existing file

explicit_path omitted
    -> validate GAMEVER
    -> <repo_root>/configs/<GAMEVER>.yaml
    -> resolve absolute path
    -> require a plain existing file
```

The resolver must reject invalid `GAMEVER` values using the repository's existing
`^[0-9]{4,10}[a-z]?$` rule. It must not accept path separators, `..`, symlink-based escape,
or a directory in place of the config file.

The resolver does not load `.env`. Entry points remain responsible for obtaining `GAMEVER`
from a CLI argument, an existing environment convention, an active binary path, or a queue
request. This keeps environment policy out of reusable libraries.

### CLI Defaults

Analysis-config CLI options change from a literal default to `None`:

```python
parser.add_argument(
    "-configyaml",
    default=None,
    help="Analysis config path; defaults to configs/<GAMEVER>.yaml",
)
```

After parsing `GAMEVER`:

```python
args.configyaml = str(
    resolve_analysis_config(args.gamever, args.configyaml)
)
```

The resolved absolute path must be printed in normal command diagnostics and propagated to
process-reporter metadata.

### Historical Git Resolver

Historical lookup is a separate API and must not be implemented as a fallback inside
`resolve_analysis_config`:

```python
def read_analysis_config_at_revision(
    revision: str,
    gamever: str,
    *,
    allow_legacy_root: bool,
) -> HistoricalConfig:
    ...
```

Lookup order:

1. `git show <revision>:configs/<GAMEVER>.yaml`
2. If the versioned path is absent and `allow_legacy_root` is true,
   `git show <revision>:config.yaml`
3. Otherwise fail.

The returned object records:

```text
revision
repository path selected
exact bytes
raw SHA-256
whether legacy fallback was used
```

Callers must validate those bytes against the snapshot's normalized contract digest or the
release manifest's recorded raw hash before treating them as authoritative.

## Path Semantics After The Move

Moving the YAML file must not implicitly redefine paths stored inside it.

| Config field | Resolution base after migration |
| --- | --- |
| `path_windows`, `path_linux` | Logical Steam depot paths; independent of config location |
| skill `expected_input` | `bin/<GAMEVER>/<module>/` with current containment checks |
| skill `expected_output` | `bin/<GAMEVER>/<module>/` |
| skill `optional_output` | `bin/<GAMEVER>/<module>/` |
| skill `skip_if_exists` | `bin/<GAMEVER>/<module>/` |
| `cpp_tests[].cpp` | Repository root |
| `cpp_tests[].headers` | Repository root |
| `cpp_tests[].include_directories` | Repository root |
| absolute source paths | Unchanged absolute path |
| `dist/*/config.yaml` | Existing downstream module directory |

`run_cpp_tests.py` currently derives its source path base from `config_path.parent`. That
would turn `cpp_tests/foo.cpp` into `configs/cpp_tests/foo.cpp`. The migration must replace
that behavior with an explicit repository/source root, normally
`Path(__file__).resolve().parent`, while continuing to accept absolute paths in tests and
specialized callers.

The versioned YAML files should retain existing values such as:

```yaml
cpp: cpp_tests/centityinstance.cpp
include_directories:
  - cpp_tests/stubs
  - hl2sdk_cs2/public
```

They must not be rewritten with `../cpp_tests` or `../hl2sdk_cs2` prefixes.

## Atomic Repository Migration

The migration lands in one PR and one logical change set. There is no supported intermediate
state where some consumers use root `config.yaml` and others use versioned configs.

### Config Data Migration

The migration change performs these data operations:

1. Preserve the existing `configs/14167.yaml` and verify it against
   `gamesymbols/14167.yaml`.
2. Move root `config.yaml` to `configs/14168.yaml` without parsing and redumping it.
3. Verify `configs/14168.yaml` against `gamesymbols/14168.yaml`.
4. Seed `configs/14168b.yaml`, `configs/14169.yaml`, and `configs/14170.yaml` as exact copies
   of `configs/14168.yaml`.
5. Remove root `config.yaml` in the same commit.

The three seed files are required because those default-branch download entries were added
before the bump workflow could create a version config. Under the pre-migration model, builds
for those entries would use the active root `config.yaml`; copying those exact bytes preserves
that existing behavior while establishing the new invariant for the current forward build
frontier. Reviewers may adjust a seeded file before using that version for a build.

The migration does not bulk-copy the current config into every older historical tag. For an
older version without an exact recoverable config, direct current-worktree resolution fails.
If support is later required, the exact historical file must be recovered and added under the
matching version rather than cloning an unrelated current config.

### Code And Workflow Cutover

The same migration change must update all runtime defaults, hidden config readers, workflows,
release logic, tests, README files, current SKILL instructions, and current Serena memories.
Only after all consumers use the shared resolver may root `config.yaml` be deleted.

### No Transitional Root Copy

The migration must not retain:

```text
config.yaml
configs/14168.yaml
```

as two editable copies. A temporary compatibility copy would make it unclear which file a
tool used and would eventually drift. Historical compatibility is handled by Git-revision
lookup, not by preserving a root file in new commits.

## Bump-Download Config Creation

Creating a version config is part of the `bump-download` workflow contract.

The mutation must be implemented inside `bump_download.py`, not as a PowerShell copy step
after the script exits. The script currently creates the local commit itself; copying a file
after that commit would leave the config outside the pushed commit and break atomicity.

### New CLI Input

Add an analysis-config directory option:

```text
-configs-dir configs
```

The workflow invokes both preview and mutation with the explicit directory:

```powershell
uv run bump_download.py `
  -config download.yaml `
  -configs-dir configs `
  ...
```

`-config` continues to mean `download.yaml`; it is not renamed to avoid conflating the two
config namespaces.

### Seed Source Selection

For a newly planned default-branch download entry:

1. Inspect the ordered `downloads` sequence before appending the new entry.
2. Select the immediately preceding entry that has no `branch` field.
3. Use that entry's exact `tag` as `SOURCE_GAMEVER`.
4. Require `configs/<SOURCE_GAMEVER>.yaml` to exist.
5. Set the target to `configs/<NEW_GAMEVER>.yaml`.

Selection uses `download.yaml` order, not lexical or numeric sorting. This correctly handles
suffix variants:

```text
14168 -> 14168b -> 14169
```

The implementation must not scan backward past a missing predecessor config to find the
nearest existing file. A missing immediate predecessor indicates a broken repository
invariant and causes the bump to fail.

The first-ever download entry is outside the automated bootstrap contract. If there is no
preceding default-branch entry, the script fails and requires an explicitly prepared seed.

### Exact Copy Semantics

The new config starts as a byte-for-byte copy:

```text
configs/<SOURCE_GAMEVER>.yaml
    -> configs/<NEW_GAMEVER>.yaml
```

Do not parse and redump YAML during this copy. Exact copying preserves comments, formatting,
ordering, aliases, and the source config's normalized contract digest.

The copied file is a reviewable starting point. If a major update or known binary change
requires config edits, those edits are made in the same bump PR before merge. The workflow
does not attempt to infer them.

### Conflict Rules

When `plan_download_entry()` says a new entry must be appended:

- The source config must exist and be a plain file.
- The target config must not already exist.
- If the target exists, fail instead of overwriting or accepting it implicitly.
- The source and target paths must remain within `configs/`.
- The worktree must be clean before either file is changed.

When the download entry already exists and `plan_missing_release_build()` enters
`dispatch_build=True` recovery mode:

- Do not create, copy, edit, or commit any config.
- Require `configs/<GAMEVER>.yaml` to exist on accepted `main`.
- If it is missing, fail and refuse to dispatch the build.

This distinction prevents a recovery run from inventing source state after the bump PR has
already been accepted.

### Atomic Mutation And Commit

For a new entry, `bump_download.py` performs one transaction:

```text
validate clean worktree
validate source config
validate absent target config
prepare new download.yaml bytes
prepare exact target config bytes
write both files
git add download.yaml configs/<NEW_GAMEVER>.yaml
git commit -m "chore(download): 更新 <PatchVersion> 下载清单"
emit workflow outputs
```

No workflow branch is pushed until the commit succeeds. If file preparation, write, staging,
or commit fails, the script returns failure and the workflow does not push or create a PR.
The implementation should restore the original `download.yaml` and remove an untracked target
config when a failure occurs after local mutation, so local manual runs also remain clean.

`create_commit()` therefore changes from accepting one config path to accepting the complete
path set, or receives both paths explicitly. Tests must assert that both files are staged in
the same commit.

### Dry-Run Behavior

`-dry-run` remains non-mutating but performs all config-plan validation that does not require
writing:

- Determine `NEW_GAMEVER`.
- Determine `SOURCE_GAMEVER`.
- Require the source config.
- Require the target config to be absent for a new entry.
- For recovery dispatch, require the accepted target config.
- Report the planned source and target.

Suggested GitHub outputs are:

```text
updated=true
tag=14171
analysis_config_source_gamever=14170
analysis_config_path=configs/14171.yaml
dispatch_build=false
```

For recovery dispatch:

```text
updated=true
tag=14171
analysis_config_path=configs/14171.yaml
dispatch_build=true
```

The duplicate-PR check continues to run after preview. If an open PR already owns the bump,
the workflow does not recreate or overwrite its config.

### Bump PR Contract

The automated bump PR must contain both:

```text
download.yaml
configs/<NEW_GAMEVER>.yaml
```

The PR body should state:

- The new `GAMEVER`.
- The source config game version used for the seed.
- The target config path.
- That the config is an exact initial copy and may require review changes before merge.
- That post-merge build dispatch uses the merge SHA as immutable `SOURCE_SHA`.

The PR may also include intentional edits to the newly created version config. It must not
modify the source version config merely to prepare the new version.

### Post-Merge And Recovery Guards

Before `.github/workflows/tag-bump-after-merge.yml` dispatches a `mode=new` build, it should
verify that `configs/<GAMEVER>.yaml` exists at the bump merge `SOURCE_SHA`. The build workflow
performs the same check authoritatively in `validate_build_input()`.

The existing `bump-download.yml` recovery path for an accepted download entry without a
release tag must verify `configs/<GAMEVER>.yaml` at `origin/main` before sending
`repository_dispatch`. Missing config is a hard failure, not a reason to copy the latest
config during recovery.

## Runtime Consumer Migration

All analysis-config consumers change in the same migration.

| Component | Required change |
| --- | --- |
| `ida_analyze_bin.py` | Resolve after `args.gamever`; pass absolute path through all processing |
| `ida_analyze_util.py` | Remove root hardcode; accept selected config or prebuilt alias map |
| `generate_reference_yaml.py` | Add `-configyaml`; resolve after final gamever inference |
| `copy_depot_bin.py` | Resolve analysis config from `-gamever`; retain `-config` as compatibility spelling |
| `download_depot.py` | Resolve module config from `-tag`; keep `-config download.yaml` unchanged |
| `gamesymbol_candidate.py` | Resolve build/compare config from `-gamever` |
| `gamesymbol_snapshot_lib/snapshot_cli.py` | Resolve pack/restore/verify config from `-gamever` |
| `gamesymbol_snapshot_lib/operations.py` | Change library defaults from `"config.yaml"` to `None` |
| `gamesymbol_store.py` | Resolve from `expected_game_version` when no explicit config is supplied |
| `update_gamedata.py` | Resolve once and use the same path for store validation and symbol loading |
| `run_cpp_tests.py` | Resolve once; use repository root for source paths |
| `gamesymbol_snapshot_lib/pr_cli.py` | Require/resolve head version config; retain explicit base config |
| `prune_pr_expected_output_bin.py` | Separate local head config resolution from historical Git path lookup |
| `process_scheduler_cli.py` | Make `--config` an optional override, not a fixed default |
| `process_scheduler_redis.py` | Resolve per queued request's `gamever`; pass absolute path to child |
| `init_gamebin.py` | Resolve once and pass the same config to copy/download/snapshot commands |
| release workflow libraries | Use strict source config and historical base lookup |

### Analyzer Context Propagation

`ida_analyze_bin.py` must resolve the config before parsing it and propagate that identity to
all helpers. A small immutable context is sufficient:

```python
@dataclass(frozen=True)
class AnalysisContext:
    gamever: str
    config_path: Path
    repo_root: Path
```

At minimum, the selected config must reach:

- main module and skill parsing;
- expected-input category validation;
- alias lookup used by LLM-decompile fallback;
- process reporter metadata;
- any generated subprocess or preprocessor context that requires symbol aliases.

No helper may default back to a repository-root config after this point.

`ida_analyze_util._load_symbol_lookup_candidates()` currently reads root `config.yaml`.
Change it to accept either the selected `config_path` or an alias lookup structure built once
from the parsed config. Building the alias map once is preferred because it avoids repeated
YAML reads and guarantees one transaction-wide view.

### Reference YAML Generation

`generate_reference_yaml.py` can infer `GAMEVER` from `CS2VIBE_GAMEVER` or the active binary
path. Config resolution occurs only after that final game version is known.

`load_symbol_aliases()` changes from taking `repo_root` and opening `repo_root/config.yaml` to
taking the resolved config path directly. Explicit `-configyaml` remains available for
scratch/reference work.

### Scheduler

The Redis worker currently stores one static `config_path` and passes it to every request.
That is incompatible with a queue containing multiple game versions.

New behavior:

```text
worker --config omitted
    -> resolve configs/<request.gamever>.yaml per request

worker --config supplied
    -> use that explicit override for every request
```

The resolved path is absolute before it is added to the child command. This removes any
dependency on scheduler `--workdir` and ensures process metadata records the actual file.

### Snapshot And Candidate Libraries

Programmatic defaults such as:

```python
config_path="config.yaml"
```

change to `config_path=None`. The library resolves from the already required game version.
Callers that have already resolved a config should continue passing it explicitly so a
multi-step transaction cannot re-resolve a different path.

The existing snapshot `config_sha256` remains the normalized analysis-contract digest. The
migration must not rewrite historical snapshots merely because the file moved.

### Downstream Consumers

`update_gamedata.py` and `run_cpp_tests.py` must use the same resolved config that was used to
build and validate the candidate snapshot.

The build workflow should compute and export:

```text
ANALYSIS_CONFIG=<absolute path>
ANALYSIS_CONFIG_SHA256=<raw file SHA-256>
```

before analysis. The file hash is rechecked before candidate build, gamedata, and C++ tests.
Any change during the transaction is a hard failure.

## Build Workflow

`.github/workflows/build-on-self-runner.yml` resolves one config immediately after checking
out the immutable `SOURCE_SHA`:

```powershell
$config = Join-Path $env:GITHUB_WORKSPACE "configs\$env:GAMEVER.yaml"
if (-not (Test-Path -LiteralPath $config -PathType Leaf)) {
  throw "Missing analysis config for GAMEVER $env:GAMEVER`: $config"
}
"ANALYSIS_CONFIG=$config" | Out-File $env:GITHUB_ENV -Encoding utf8 -Append
```

The path is then passed explicitly to every relevant command:

```text
copy_depot_bin.py       -config/-configyaml $ANALYSIS_CONFIG
download_depot.py       -configyaml $ANALYSIS_CONFIG
ida_analyze_bin.py      -configyaml $ANALYSIS_CONFIG
gamesymbol_candidate.py -configyaml $ANALYSIS_CONFIG
update_gamedata.py      -configyaml $ANALYSIS_CONFIG
run_cpp_tests.py        -configyaml $ANALYSIS_CONFIG
```

This explicit workflow wiring is retained even though each command has the same computed
default. It makes the transaction auditable and prevents one missed default from selecting a
different file.

`release_workflow_lib.validation.validate_build_input()` must validate at `SOURCE_SHA` that:

- `download.yaml` contains `GAMEVER`;
- `configs/<GAMEVER>.yaml` exists;
- the YAML is readable and contains a valid top-level `modules` list;
- the config path is exactly the expected versioned path;
- mode/tag rules still pass.

For new builds after this migration, root-config fallback is not accepted at `SOURCE_SHA`.

## PR Self-Runner

Ordinary PR validation continues to distinguish:

- `PR_GAMEVER`: newest version declared by head `download.yaml`.
- `VALIDATION_GAMEVER`: trusted accepted snapshot version selected from the PR base.

A bump PR that adds `configs/<PR_GAMEVER>.yaml` does not build that new game version before
merge. It validates shared code against `VALIDATION_GAMEVER`, then the post-merge workflow
dispatches the new-version build from the accepted merge SHA.

### Base Config

For the selected base snapshot:

1. Determine `BASE_GAMEVER` from `gamesymbols/<BASE_GAMEVER>.yaml`.
2. Determine the commit that published that snapshot.
3. Extract `configs/<BASE_GAMEVER>.yaml` from that commit.
4. If absent, allow historical fallback to that commit's `config.yaml`.
5. Validate the extracted config against the base snapshot before restore.

The fallback is not taken from current `HEAD` and is not copied from another version.

### Head Config

The head config is always:

```text
configs/<VALIDATION_GAMEVER>.yaml
```

from the PR working tree. It is passed explicitly to invalidation, analysis, candidate build,
candidate comparison, gamedata, and C++ tests.

If the PR changes only `configs/<PR_GAMEVER>.yaml` for a future version while
`PR_GAMEVER != VALIDATION_GAMEVER`, that file is not treated as a change to the active head
contract for the accepted-version replay. The bump workflow and build-input guards validate
its structural presence separately.

If the PR changes `configs/<VALIDATION_GAMEVER>.yaml`, normal producer diff and transitive
invalidation apply.

### Changed-Path Mapping

Invalidation logic must stop treating only literal `config.yaml` as the config source. It
receives the selected base/head config identities and treats changes to the active head path
as config changes. Other `configs/*.yaml` files are unrelated to that replay unless shared
code explicitly references them.

Tests must cover a bump PR where:

```text
PR_GAMEVER=14171
VALIDATION_GAMEVER=14168
changed files include configs/14171.yaml
```

and confirm that the new-version config is present but does not replace the 14168 validation
contract.

## Republish And Historical Invalidation

`release_workflow_lib.validation.invalidate_republish()` currently reads both base and head
from root `config.yaml`. It changes to:

```text
base config
    -> previous accepted manifest SOURCE_SHA
    -> configs/<GAMEVER>.yaml
    -> legacy config.yaml only for pre-migration SOURCE_SHA

head config
    -> current requested SOURCE_SHA
    -> configs/<GAMEVER>.yaml
    -> no legacy fallback for post-migration builds
```

The base config must validate against the accepted snapshot and, for a new manifest schema,
its raw hash must match release provenance. The head config is loaded from the immutable
requested `SOURCE_SHA`, not merely from whichever worktree happens to invoke the command.

Config-path changes themselves participate in source-aware invalidation. A changed
`configs/<GAMEVER>.yaml` is compared as the head contract for that same version; adding or
changing another version's config does not invalidate this republish.

## Release Provenance And Archives

The snapshot's normalized contract digest does not include every config field, notably all
downstream symbol mapping and C++ test semantics. Releases therefore need the exact config
file identity in addition to the existing snapshot contract digest.

### Manifest Schema

New release manifests should use a schema revision that adds:

```json
{
  "analysis_config_path": "configs/14171.yaml",
  "analysis_config_sha256": "<sha256 of exact file bytes>",
  "analysis_config_contract_sha256": "sha256:<normalized contract digest>"
}
```

The loader may continue accepting schema-1 manifests for historical releases. Schema-1
republish uses revision-scoped historical lookup plus snapshot contract validation. All new
builds write the new schema.

The generated-output PR still changes only:

```text
gamesymbols/<GAMEVER>.yaml
release-manifests/<GAMEVER>.json
dist/**
```

`configs/<GAMEVER>.yaml` remains source input and is not added to the generated-output path
allowlist.

### Archive Contents

`gamedata-<GAMEVER>.7z` must include:

```text
configs/<GAMEVER>.yaml
gamesymbols/<GAMEVER>.yaml
bin/<GAMEVER>/**/*.yaml
dist/**
hl2sdk_cs2/**
```

`gamebin-<GAMEVER>.7z` remains binary-only.

The archived config bytes must be extracted from the manifest's recorded `SOURCE_SHA` and
verified against `analysis_config_sha256`. The promotion workflow must not blindly archive
the path from `OUTPUT_MERGE_SHA`, because main may have changed while the generated-output PR
was open.

Archive staging should place the verified source bytes at the canonical relative path
`configs/<GAMEVER>.yaml` before invoking 7-Zip. The existing blanket exclusion of
`config.yaml` can remain for downstream overlays only if it does not exclude the explicitly
staged versioned file.

## Init-Gamebin And Local Workflows

`init_gamebin.py prepare <GAMEVER>` resolves one version config and passes it explicitly to:

- `download_depot.py`;
- `copy_depot_bin.py`;
- snapshot restore;
- snapshot verification;
- optional rename analysis.

If a tracked snapshot exists but the matching current-worktree version config does not,
initialization fails with a message naming both required files. It does not use the latest
config.

Local defaults become:

```powershell
uv run ida_analyze_bin.py -gamever 14168
# uses configs/14168.yaml

uv run gamesymbol_candidate.py build -gamever 14168 ...
# uses configs/14168.yaml

uv run run_cpp_tests.py -gamever 14168 -snapshot <candidate>
# uses configs/14168.yaml
```

Explicit scratch behavior remains:

```powershell
uv run ida_analyze_bin.py `
  -gamever 14168 `
  -configyaml _scratch.yaml
```

## Failure Behavior

The migration intentionally converts ambiguous situations into hard failures.

| Situation | Required behavior |
| --- | --- |
| Current `configs/<GAMEVER>.yaml` missing | Fail and print expected path |
| Explicit config missing | Fail; do not try the default |
| Explicit config uses invalid file type | Fail |
| Config changes during build transaction | Fail before next stage |
| Bump predecessor config missing | Fail; do not append `download.yaml` |
| Bump target config already exists | Fail; do not overwrite |
| Recovery dispatch target config missing | Fail; do not dispatch |
| Historical versioned config absent, legacy root exists | Use only for historical lookup |
| Historical fallback digest mismatches snapshot | Fail |
| Source SHA lacks version config | Reject build input |
| Release manifest raw config hash mismatches source bytes | Refuse promotion |
| C++ relative path resolves outside allowed source root | Fail |

No warning-only fallback is permitted for these cases.

## Tests

### Resolver Tests

- Implicit `GAMEVER=14168` resolves repository-root `configs/14168.yaml`.
- Explicit absolute path wins.
- Explicit relative path remains CWD-relative.
- Missing implicit file fails without root fallback.
- Missing explicit file fails without default fallback.
- Invalid game-version syntax and traversal attempts fail.
- Resolution is stable when process CWD is outside the repository.
- Raw SHA-256 is based on exact bytes.

### Bump Script Tests

- A new base tag copies the immediately preceding default-branch config.
- A suffix tag copies the preceding suffix/base version according to download order.
- Beta/branch entries are ignored when selecting the default-branch predecessor.
- Copying is byte-for-byte and does not parse/redump YAML.
- Missing predecessor config fails before mutation.
- Existing target config fails and is not overwritten.
- Dry-run reports source and target without writing.
- New entry stages `download.yaml` and `configs/<NEW_GAMEVER>.yaml` in one commit.
- Commit failure restores the original download file and removes the new untracked config.
- Recovery dispatch requires the existing target config and performs no write/commit.
- Workflow output contains tag, config source, target path, and dispatch mode.

### Analyzer And Consumer Tests

- Analyzer parsing, expected-input category lookup, and alias fallback use the same config.
- `generate_reference_yaml.py` resolves aliases from the selected version config.
- Candidate pack, compare, restore, and verify default to the requested version config.
- Gamedata and C++ consumers reject a candidate/config mismatch.
- C++ `cpp`, `headers`, and include paths remain repository-root-relative.
- Scheduler requests for two game versions produce two different absolute config arguments.
- Scheduler explicit override remains supported.

### Workflow Tests

- `bump-download.yml` passes `-configs-dir configs` in preview and mutation calls.
- The bump PR contract includes both download and version-config paths.
- Recovery dispatch checks the accepted target config before dispatch.
- Post-merge dispatch validates config presence at merge `SOURCE_SHA`.
- Build workflow computes one config and passes it to every stage.
- Build input validation rejects a source SHA missing the version config.
- PR workflow extracts versioned base config and supports validated legacy fallback.
- PR head uses `configs/<VALIDATION_GAMEVER>.yaml`.
- A future-version config added by a bump PR does not replace the accepted replay config.
- Republish uses base and head configs from their respective source SHAs.
- Promotion archives and verifies the source config bytes.

### Migration Fixture Tests

- `configs/14167.yaml` validates `gamesymbols/14167.yaml`.
- `configs/14168.yaml` validates `gamesymbols/14168.yaml`.
- Seeded `14168b`, `14169`, and `14170` configs are byte-identical to the migrated 14168
  config at migration time.
- No tracked root `config.yaml` remains.
- A repository-wide behavioral search finds no production default or hardcoded analysis read
  of root `config.yaml`.

Documentation-only historical plans may still mention the old path when describing past
behavior. Current executable docs, skills, README files, and memories must not.

## Documentation And Skill Updates

Update current guidance that authors or consumes the analysis config, including:

- `README.md`
- `README_CN.md`
- `.claude/skills/post-change-update/SKILL.md`
- `.claude/skills/post-change-validation/SKILL.md`
- `.claude/skills/fix-cppheaders/SKILL.md`
- `.claude/skills/create-preprocessor-scripts/SKILL.md`
- `.claude/skills/create-cpp-tests/SKILL.md`
- `.claude/skills/rename-preprocessor-scripts/SKILL.md`
- `.claude/skills/run-validation-until-no-failure/SKILL.md`
- `.claude/skills/init-gamebin/SKILL.md`
- relevant Serena memories for config, analyzer, PR, snapshot, gamedata, and C++ tests

Authoring instructions must resolve the active edit target from `CS2VIBE_GAMEVER` or an
explicit requested `GAMEVER`:

```text
configs/<GAMEVER>.yaml
```

They must not say "edit config.yaml" without a version.

Historical implementation plans and superseded specifications do not need bulk rewriting.
Where confusion is likely, add a short note pointing to this plan rather than altering their
historical record.

## Implementation Sequence

Although the work can be developed in internal commits, the mergeable result is atomic. The
recommended implementation order is:

1. Add shared runtime and historical config-resolution helpers with tests.
2. Migrate snapshot/candidate libraries and CLI defaults to `None` plus version resolution.
3. Migrate analyzer parsing and remove all hidden root-config lookups.
4. Migrate reference generation, binary copy/download, downstream consumers, scheduler, and
   init-gamebin.
5. Fix repository-root-relative C++ path semantics.
6. Extend `bump_download.py` to seed and commit a version config atomically.
7. Update `bump-download.yml` preview, mutation, PR body, duplicate, and recovery guards.
8. Update post-merge dispatch and build-input validation.
9. Update build and PR workflows to pass one explicit resolved config through every stage.
10. Update republish historical lookup, release manifest provenance, and archive staging.
11. Move `config.yaml` to `configs/14168.yaml`, create the migration seed files, and remove the
    root path.
12. Update tests, current docs, skills, and memories.
13. Run the repository's required regression, workflow-contract, snapshot, gamedata, and C++
    validation gates before merge.

Steps 1-10 must not be merged separately while root defaults remain partly active. If staged
development requires temporary compatibility, it remains on the development branch and is
removed before review.

## Acceptance Criteria

The migration is complete only when all of the following are true:

- Root `config.yaml` no longer exists in the post-migration tree.
- `configs/14168.yaml` contains the former root config bytes and validates the 14168 snapshot.
- Current forward download entries needed for new-build recovery have matching version
  configs.
- Every production analysis-config consumer uses the shared resolver or an explicitly passed
  resolved path.
- No analyzer helper or reference generator hardcodes root `config.yaml`.
- Missing current version configs fail closed.
- Historical Git consumers can read a versioned config and can validate a pre-migration root
  config fallback.
- C++ test source paths still resolve from the repository root.
- Scheduler config selection is per request unless explicitly overridden.
- Build and PR workflows pass one selected config through their complete transaction.
- A new bump PR contains both `download.yaml` and `configs/<NEW_GAMEVER>.yaml` in the same
  commit.
- Bump recovery refuses to dispatch when the accepted version config is missing.
- Release provenance records the exact source config path and raw SHA-256.
- The gamedata release archive contains the verified config bytes from `SOURCE_SHA`.
- Generated-output PR path rules remain unchanged and do not admit source configs.
- Existing 14167 and 14168 snapshots continue to validate without being rewritten.

## Final Architecture

The resulting new-version flow is:

```text
bump_download.py discovers NEW_GAMEVER
        |
        +--> append download.yaml
        |
        +--> exact-copy predecessor config
                to configs/<NEW_GAMEVER>.yaml
        |
        v
single bump commit and PR
        |
        v
review/adjust new version config
        |
        v
merge commit becomes SOURCE_SHA
        |
        v
build validates configs/<NEW_GAMEVER>.yaml at SOURCE_SHA
        |
        v
copy/download/analyze/candidate/gamedata/C++
all use the same resolved config
        |
        v
generated-output PR
        |
        v
release manifest binds exact config bytes
        |
        v
release archive includes configs/<NEW_GAMEVER>.yaml
```

The key authority rule is:

```text
download.yaml declares that GAMEVER exists.
configs/<GAMEVER>.yaml declares how that GAMEVER is analyzed.
gamesymbols/<GAMEVER>.yaml records the resulting immutable symbols.
SOURCE_SHA binds the exact generator and config bytes used for the release.
```
