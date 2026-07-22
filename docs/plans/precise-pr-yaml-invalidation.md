# Precise PR YAML Invalidation

## Status

Implemented on 2026-07-22 as a follow-up to `docs/plans/track-gamesymbols-snapshot.md`.

Implementation results:

- Git changes now preserve A/M/D/R/C status and rename sides through `ChangedPath`.
- Base and HEAD preprocessor sources are loaded immutably from Git archives; reference ownership is extracted from
  declarative `reference_yaml_paths` entries.
- Producer fingerprints no longer include `skill_index` and use platform-specific resolved semantics.
- Active config changes no longer independently seed every producer.
- Active orphan references fail with `orphan_active_reference`; orphan deletions warn without broad invalidation.
- The two residual `CBaseEntity_PhysicsTouch` reference YAML files were removed while formal outputs and snapshot entries
  were retained.
- Final PR #605 replay reported 8 changed logical config producers, 30 invalidated paths, and 0 SDL3 paths.
- Validation passed: 21 focused invalidation tests, 875 unit tests, 85 repository-contract tests, 1,023 full-suite tests,
  and 1,023 legacy-discovery tests.

This plan narrows PR invalidation without weakening the deterministic base, snapshot trust boundary, or dependency-closure
guarantees already implemented by the snapshot workflow. The motivating case is PR #605, where a localized server Touch
change invalidated SDL3 and almost the entire formal YAML set.

Measured against PR #605 base `b54a3c451cac8437613c42d824a140ef36d72f94` and head
`20b8e80d17e8ffc2627789f47eff4ed76bb093cd`:

- Snapshot delta: 14 paths.
- Current config delta: 772 producer nodes.
- Current final invalidation: 2,944 paths.
- Unrelated SDL3 invalidation: 18 paths.
- Removing the two observed broad-rebuild triggers reduces the plan to 754 paths and zero SDL3 paths, even before
  stabilizing config fingerprints.
- Comparing config nodes by semantic content instead of `skill_index` reduces the directly changed logical nodes from 772
  producer nodes to 8 platform-specific logical nodes.

## Relationship To Existing Design

`track-gamesymbols-snapshot.md` already requires:

- config skill changes to invalidate the corresponding producer outputs;
- reference changes to invalidate their consumers;
- dependency closure to invalidate downstream artifact consumers;
- unknown core analysis changes to use fail-safe broad rebuilds.

The current implementation is more conservative than those requirements in three places:

1. Any change to `configs/<GAMEVER>.yaml` is also treated as a source change affecting every producer, even though a
   producer-level config delta is already calculated.
2. A producer fingerprint contains the positional `skill_index`, so inserting one skill changes every later fingerprint in
   the same module.
3. Reference consumer mapping only scans the HEAD workspace and receives path-only Git diffs, so deletions and renames can
   appear unmapped and trigger a broad rebuild.

This plan corrects those mismatches. It does not replace snapshot delta handling, formal output ownership, or dependency
closure.

## Goals

- A localized config, preprocessor, or reference change invalidates only its producers and their real downstream closure.
- Changes in the server Touch chain do not invalidate SDL3 unless a declared cross-module dependency actually reaches SDL3.
- Inserting, deleting, or moving a config skill does not change unrelated producer fingerprints merely because list indexes
  moved.
- Reference additions, modifications, deletions, and renames are mapped against the correct Git revision.
- An active reference with no declarative consumer produces an actionable validation error instead of an expensive broad
  rebuild.
- Deleting an already orphaned reference is a safe cleanup operation.
- Truly unknown core analysis changes retain the existing fail-safe broad rebuild behavior.
- Invalidation reasons remain deterministic and explain which revision, path, producer, or policy caused each seed.

## Non-Goals

- Do not weaken snapshot contract, config digest, schema, or analysis output contract version checks.
- Do not remove dependency closure or prevent legitimate cross-module invalidation.
- Do not silently accept references that are expected to participate in analysis but are not declared by a consumer.
- Do not change the contents or schema of generated game-symbol YAML.
- Do not remove `skill_index` from runtime scheduling solely for this work. It may remain in an ephemeral node identifier if
  required for uniqueness; it must not define semantic producer identity.
- Do not treat every unknown source file as safe. Core analyzer changes that cannot be mapped reliably remain broad.

## Terminology

### Formal Output

A generated YAML under `bin/<GAMEVER>/<module>/...` and the corresponding key in `gamesymbols/<GAMEVER>.yaml`.

Example:

```text
bin/14172/server/CBaseEntity_PhysicsTouch.windows.yaml
gamesymbols/14172.yaml -> server/CBaseEntity_PhysicsTouch.windows.yaml
```

### Reference YAML

A checked-in analysis input under `ida_preprocessor_scripts/references/<module>/...`. It contains disassembly or
decompilation evidence supplied to `LLM_DECOMPILE`.

Example:

```text
ida_preprocessor_scripts/references/server/CPhysicsGameSystem_ProcessContactEvents.windows.yaml
```

Reference YAML and formal output YAML may share a basename, but they are different artifacts with different ownership.

### Reference Consumer

A `find-*.py` preprocessor that declaratively names a reference in an `LLM_DECOMPILE[*].reference_yaml_paths` entry.

### Producer Logical Identity

The stable identity used to match the same producer between base and HEAD. It must be independent of list position. The
current logical identity is based on module, skill name, and platform, with stage/disambiguation handled where necessary.

## Problem Analysis

### Broad Config Source Trigger

`build_invalidation_plan()` already calls `_config_changed_nodes(base_contract, head_contract)`. However,
`_source_changed_nodes()` separately treats the active versioned config path as a core source change and adds every HEAD
node:

```python
if path == f"configs/{head_contract.game_version}.yaml":
    nodes.update(head_contract.nodes)
```

This makes the producer-level config comparison ineffective whenever the config file appears in the Git diff.

### Positional Fingerprint Amplification

The current fingerprint includes:

```python
"skill_index": skill_index
```

Adding one skill in the middle of a module shifts all later indexes. In PR #605, only eight base/HEAD logical nodes have
different semantic producer definitions, but the positional fingerprints report 772 changed producer nodes across server
Windows and Linux.

### HEAD-Only Reference Mapping

The changed-file collector uses `git diff --name-only`, losing whether a path was added, modified, deleted, copied, or
renamed. `_reference_consumers()` then scans only the current HEAD workspace.

This is insufficient for changes such as:

```text
base: old reference -> old consumer
head: old reference deleted and consumer renamed or removed
```

The old reference has no HEAD consumer, so it is classified as unmapped even though its base consumer is known.

### Current Orphaned PhysicsTouch Reference

Before PR #605, `CBaseEntity_PhysicsNotifyOtherOfEndTouch.{platform}.yaml` was consumed by the old combined StartTouch and
EndTouch finder. PR #605 changes EndTouch to use `CBaseEntity_VPhysicsEndTouch.{platform}.yaml` but also renames the old
reference to `CBaseEntity_PhysicsTouch.{platform}.yaml`.

The resulting `CBaseEntity_PhysicsTouch` reference has no current `reference_yaml_paths` consumer. The similarly named
formal output remains valid and is produced from the
`CPhysicsGameSystem_ProcessContactEvents.{platform}.yaml` reference. Only the unused checked-in reference is residual.

## Design Decisions

### 1. Config Changes Use Only Semantic Config Delta

Remove the special case that maps a change to `configs/<GAMEVER>.yaml` to all HEAD nodes.

Config invalidation must be seeded only by:

1. base/HEAD producer semantic comparison;
2. base/HEAD snapshot delta ownership;
3. analysis output contract version changes;
4. mapped source/reference changes;
5. downstream dependency closure.

The active config path may still appear in diagnostic output, but it must not independently add producers after the
semantic config comparison has completed.

Changing another game version's config continues to have no effect on the active PR validation version.

### 2. Separate Ephemeral Node Position From Semantic Fingerprint

Remove `skill_index` from producer fingerprint data.

The semantic fingerprint should include only fields that can affect producer behavior or outputs:

- stage identity;
- module name and platform-specific binary path;
- skill name or explicit stable skill identifier;
- platform;
- required and optional outputs;
- required and optional inputs;
- prerequisites;
- other supported analysis skill fields that affect execution.

`skill_index` may remain in `node_id` while the scheduler requires a unique positional identifier, provided base/HEAD
matching and config comparison do not treat a moved index as a semantic change.

If duplicate skill names can occur within the same module, platform, and stage, introduce an explicit stable config `id` or
another deterministic discriminator. Do not reintroduce list position into the fingerprint as an implicit discriminator.

Expected PR #605 result at the config seed level:

```text
current positional comparison: 772 changed producer nodes
semantic comparison:             8 changed logical nodes
```

Dependency closure may legitimately add more nodes after those initial seeds.

### 3. Preserve Git Change Type And Rename Sides

Replace the path-only changed-file model with a typed model, for example:

```python
@dataclass(frozen=True)
class ChangedPath:
    status: str
    old_path: str | None
    new_path: str | None
```

Collect changes with a rename-aware, NUL-delimited Git command equivalent to:

```text
git diff --name-status -M -z <base> <head> --
```

The parser must support at least:

- `A`: added;
- `M`: modified;
- `D`: deleted;
- `R`: renamed, retaining old and new paths;
- `C`: copied, if Git reports it.

Paths must be normalized once after parsing. The implementation must not infer deletion or rename state from filesystem
existence alone.

### 4. Resolve Reference Consumers At Base And HEAD

Reference mapping must be revision-aware:

| Git change | Consumer lookup | Seed behavior |
| --- | --- | --- |
| Added | HEAD new path | Seed HEAD consumers |
| Modified | Union of base and HEAD consumers | Seed both sides, then map into HEAD closure |
| Deleted | Base old path | Seed base consumers and remove their affected base outputs |
| Renamed | Base old path plus HEAD new path | Seed both sides without treating either side as unknown |
| Copied | HEAD destination, optionally base source for diagnostics | Seed destination consumers |

Base consumers must map to base contract nodes. HEAD consumers must map to HEAD contract nodes. Existing logical-key
translation then carries affected base producers into the applicable HEAD producer set before dependency closure.

Revision reads must not mutate the checkout. Acceptable implementations include reading tracked files through Git object
commands or constructing an immutable revision source map for `ida_preprocessor_scripts/find-*.py`.

### 5. Make Declarative Reference Ownership Enforceable

`reference_yaml_paths` is the source of truth for active reference ownership. A changed or newly introduced checked-in
reference under `ida_preprocessor_scripts/references/` must either:

- have at least one declarative consumer in the relevant revision; or
- be stored outside the active reference tree as documentation, a fixture, or an archive.

Unchanged legacy references are outside the initial migration scope and may be audited separately. Once touched, they must
follow this ownership rule.

Policy for references with no consumer:

| Situation | Required behavior |
| --- | --- |
| Added active reference with no HEAD consumer | Fail validation with `orphan_active_reference` |
| Modified active reference with no base or HEAD consumer | Fail validation with `orphan_active_reference` |
| Deleted reference with no base consumer | Ignore for invalidation and emit a deterministic warning |
| Renamed destination with no HEAD consumer | Fail validation for the destination |
| Renamed source with no base consumer | Treat the source as orphan cleanup and warn |

An orphan active reference must not silently trigger a broad rebuild. A validation error is safer because it forces the
author to either declare the real consumer or remove/relocate the unused artifact.

Do not add a fake consumer solely to satisfy validation. Adding a reference to `reference_yaml_paths` changes LLM input and
must reflect a real analysis dependency.

### 6. Remove The Residual PhysicsTouch Reference

Delete the unused active references:

```text
ida_preprocessor_scripts/references/server/CBaseEntity_PhysicsTouch.windows.yaml
ida_preprocessor_scripts/references/server/CBaseEntity_PhysicsTouch.linux.yaml
```

Retain the formal outputs and snapshot entries:

```text
server/CBaseEntity_PhysicsTouch.windows.yaml
server/CBaseEntity_PhysicsTouch.linux.yaml
```

This cleanup must land with revision-aware deletion handling. Under the current HEAD-only implementation, deletion itself
still appears as an unmapped changed reference and triggers a broad rebuild.

### 7. Keep Broad Rebuilds For Explicit Core Boundaries

Broad rebuild remains correct for a small, explicit set of changes whose producer impact cannot be mapped safely, such as:

- analysis output contract version changes;
- core agent prompts that affect every fallback producer;
- shared analyzer output writers or execution semantics when no narrower contract exists;
- unknown preprocessor source changes that may be imported dynamically and cannot be resolved by the importer graph.

Versioned config files and declaratively owned reference YAML are not unknown core boundaries and must not use this path.

The broad-rebuild reason must name the policy boundary and changed file. Avoid a generic fallback that hides whether the
problem was an orphan reference, an unsupported Git status, or a core analyzer change.

## Target Invalidation Algorithm

```text
load base contract and snapshot
load HEAD contract and snapshot
collect typed Git changes with rename sides

seed snapshot-delta owners from base and HEAD
seed semantic config-delta producers
seed all HEAD nodes only when analysis output contract version changed

for each typed source change:
    config path:
        already handled by semantic config delta; add no source seed
    reference path:
        resolve consumers in the revision selected by A/M/D/R policy
        orphan active reference -> validation error
        orphan deletion -> warning, no seed
    preprocessor path:
        resolve direct and transitive importers in the applicable revision(s)
    explicitly broad core path:
        seed all HEAD nodes

map affected base logical producers into HEAD
compute HEAD artifact dependency closure
invalidate:
    snapshot delta paths
    all outputs of affected base producers
    all outputs of affected HEAD producers and closure
```

## Observability

Invalidation output should distinguish seed classes and revision sides. Example:

```text
snapshot delta: 14 path(s)
config delta: 8 logical producer(s)
reference rename: base old/path.yaml -> HEAD new/path.yaml
reference consumers: base=old-skill, HEAD=new-skill
dependency closure: 6 additional producer(s)
invalidated paths: 23
```

For orphan cleanup:

```text
warning: deleted orphan reference had no base consumer: old/path.yaml
```

For invalid active references:

```text
error[orphan_active_reference]: new/path.yaml has no HEAD consumer
```

The CLI must continue to print every invalidated path deterministically after the summarized reasons.

## Implementation Phases

### Phase 1: Pin The Regression

- Add a PR #605-shaped fixture with server Touch config, snapshot, source, and reference changes.
- Assert the current implementation demonstrates the known broad-rebuild behavior before production changes.
- Add focused tests for config insertion, reference deletion, reference rename, and orphan reference policy.

Gate:

- New tests fail for the intended reasons against current production behavior.
- Existing snapshot and PR invalidation tests remain unchanged and passing until their behavior is intentionally replaced.

### Phase 2: Introduce Typed Git Changes And Revision Sources

- Add the `ChangedPath` model.
- Parse `git diff --name-status -M -z` safely.
- Add immutable base/HEAD source readers for preprocessor consumer mapping.
- Implement A/M/D/R reference resolution and diagnostics.

Gate:

- Deleted references map base consumers.
- Renames map old base and new HEAD consumers.
- No checkout mutation is required.
- Paths containing spaces and rename status scores are parsed correctly.

### Phase 3: Stabilize Producer Fingerprints

- Remove `skill_index` from semantic fingerprint data.
- Add an explicit stable discriminator if duplicate logical producers require it.
- Keep scheduler identity changes separate from semantic fingerprint changes.

Gate:

- Inserting a skill does not change fingerprints of later unchanged skills.
- Changing a skill's outputs, inputs, prerequisites, platform conditions, module path, or stage still changes its fingerprint.
- PR #605 reports eight directly changed logical config nodes before dependency closure.

### Phase 4: Remove Broad Config Mapping And Enforce Reference Ownership

- Remove `configs/<GAMEVER>.yaml -> all nodes` from source mapping.
- Make orphan active references validation errors.
- Make orphan reference deletion a warning or no-op for invalidation.
- Delete the residual `CBaseEntity_PhysicsTouch` reference YAML files.

Gate:

- Config changes are represented exactly once through semantic config delta.
- Reference cleanup does not trigger broad rebuild.
- No fake reference consumer is introduced.

### Phase 5: Integration Replay

- Recompute the invalidation plan using the PR #605 base/head fixture.
- Run targeted unit tests, repository contract tests, and the full required Python validation suites.
- If workflow source changes are needed, run the semantic workflow contract tests.

Gate:

- No SDL3 path is invalidated by the PR #605 fixture.
- Invalidated server paths are explainable by snapshot delta, changed producer semantics, mapped source/reference changes, or
  dependency closure.
- Explicit core-analysis broad-rebuild tests continue to invalidate all formal outputs.

## Test Matrix

### Config Tests

- Modify one skill output and invalidate that producer plus downstream consumers.
- Insert a skill before unrelated skills and keep later fingerprints stable.
- Delete a skill and remove its base outputs without invalidating unrelated modules.
- Rename a skill and invalidate old outputs plus the new producer closure.
- Change module binary path or stage and invalidate affected producers.
- Change `configs/<other-gamever>.yaml` and invalidate nothing for the active game version.

### Reference Tests

- Modify a consumed reference and invalidate all declared consumers.
- Delete a consumed reference while deleting or renaming its consumer; resolve the consumer from base.
- Rename a reference and resolve old base plus new HEAD consumers.
- Add an unconsumed active reference and return `orphan_active_reference`.
- Modify an orphan active reference and return `orphan_active_reference`.
- Delete a reference with no base consumer and emit a warning without broad rebuild.
- Ensure a reference basename in another module does not cross-contaminate consumers.
- Ensure multiple `reference_yaml_paths` entries map every declared reference to the same producer correctly.

### Broad-Rebuild Tests

- Analysis output contract version change invalidates every HEAD producer.
- Explicit core prompt or analyzer boundary change invalidates every HEAD producer.
- Unknown dynamically imported analysis source retains fail-safe broad behavior.
- Config and declarative reference changes never reach broad behavior solely because their path changed.

### PR #605 Regression Test

The fixture must assert at minimum:

```python
self.assertFalse(any(path.startswith("SDL3/") for path in plan.paths))
```

It should additionally assert:

- semantic config delta contains only the expected old/new Touch producers for Windows and Linux;
- old reference outputs are removed;
- new StartTouch, Touch, EndTouch, and their real downstream consumers are invalidated;
- unrelated server producers after the inserted config position remain reusable;
- no `unmapped analysis reference (broad rebuild)` reason is present;
- no `active analysis config change` broad reason is present.

## Expected Files To Change During Implementation

- `gamesymbol_snapshot_lib/pr_cli.py`
  - typed, rename-aware Git change collection.
- `gamesymbol_snapshot_lib/pr_validation.py`
  - semantic config-only behavior, revision-aware reference/source mapping, orphan policy, diagnostics.
- `gamesymbol_snapshot_lib/config.py`
  - stable semantic fingerprint.
- `gamesymbol_snapshot_lib/model.py`
  - typed changed-path or revision-source models if they belong in the shared model layer.
- `tests/test_gamesymbol_pr_validation.py`
  - focused invalidation behavior.
- Additional Git-backed tests if revision parsing and base/HEAD source loading require repository fixtures.
- `ida_preprocessor_scripts/references/server/CBaseEntity_PhysicsTouch.windows.yaml`
  - delete as unused active reference.
- `ida_preprocessor_scripts/references/server/CBaseEntity_PhysicsTouch.linux.yaml`
  - delete as unused active reference.

Workflow changes are optional. The existing workflow can continue invoking `gamesymbol_pr_validation.py invalidate` if the CLI
contract remains compatible.

## Acceptance Criteria

- PR #605-shaped replay invalidates zero SDL3 outputs.
- A localized server config edit does not seed every module.
- A config skill insertion does not change later unrelated producer fingerprints.
- Reference deletion and rename use base and HEAD consumers according to the typed Git status.
- Active orphan references fail with a specific validation error instead of causing broad rebuild.
- Orphan reference deletion does not cause broad rebuild.
- The unused `CBaseEntity_PhysicsTouch` reference files are removed while the formal outputs remain tracked in the snapshot.
- Snapshot delta ownership and downstream dependency closure remain complete.
- Explicit core-analysis broad rebuild behavior remains covered and unchanged.
- Targeted invalidation tests, repository contract tests, and the full required Python validation gate pass.
- CI output provides deterministic reasons sufficient to explain every invalidation seed class.

## Safety And Rollback

The implementation must be delivered in phases with tests before removing conservative behavior. If revision-aware mapping
cannot classify a changed active reference safely, validation must stop with an explicit error rather than silently reuse
base outputs.

Rollback may restore broad config/reference behavior temporarily, but must not retain stable-fingerprint tests while
claiming precise invalidation is active. Snapshot trust, deterministic restore, and output contract version broad invalidation
must remain intact throughout all phases.
