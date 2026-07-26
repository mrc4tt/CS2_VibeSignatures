# Fix `update_gamedata` Warning Noise

## Status

Implemented and accepted for game version `14172`; the immutable symbol and gamedata candidate
passed the repository validation gate and the same candidate was published locally.

This plan addresses the misleading and duplicated `Warning: YAML not found` output emitted by
`update_gamedata.py` while building an isolated versioned gamedata candidate. The motivating
example is GitHub Actions run `30147486342`, job `89651999092`, where warnings for unrelated
modules such as `SDL3/SDL_PreInitMouse.linux.yaml` appeared below the `Updating CS2Fixes...`
header.

The implementation is split into four phases:

1. Introduce structured diagnostics, globally deduplicate them, and print only overlay deltas
   below each generator header.
2. Add explicit platform metadata to active single-platform symbols, including the complete SDL3 set, and validate
   skill/symbol platform consistency.
3. Define `category: struct` as metadata-only and add symbol config validation.
4. Introduce `source_alias` and migrate the known vfunc artifact-name mismatches.

Each phase has its own behavioral gate. Diagnostic cleanup must not be coupled to a risky
loader optimization or a broad config migration.

## Background

`generate_gamedata()` loads the base analysis config once, then `_module_data()` merges and
reloads the complete config for every generator that has its own `config.yaml`.

For the observed candidate:

| Section | Warning observations |
| --- | ---: |
| Base load | 128 |
| CS2Fixes | 130 |
| CS2KZ | 128 |
| CS2Surf | 128 |
| ModSharp | 128 |
| SwiftlyS2 | 128 |
| Total | 770 |

Five generators have an overlay config and therefore repeat the base load. CounterStrikeSharp
and Plugify do not have an overlay config and reuse the already loaded base data.

The CS2Fixes section contains only two overlay-specific missing artifacts:

```text
server/CTakeDamageInfo_ctor.windows.yaml
server/CTakeDamageInfo_ctor.linux.yaml
```

The other 128 observations are inherited from the base config. Across the complete run, 640
observations are duplicate reports of an already observed issue.

The base warnings also mix several different causes:

- platform-restricted skills whose symbols default to both platforms;
- metadata-only struct declarations treated as loadable artifacts;
- canonical symbol names that differ from the artifact filenames produced by skills;
- genuinely missing or malformed artifacts.

Because the loader prints immediately, all these causes are presented as equivalent missing
YAML warnings and are visually attributed to whichever generator header was printed most
recently.

## Decision Summary

The target behavior is:

```text
load base config
    -> collect structured diagnostics

for each generator:
    load merged config when required
    -> collect structured diagnostics without printing
    -> compare merged diagnostics with base diagnostics
    -> print only overlay-added diagnostics below the generator header

after all generators:
    globally aggregate diagnostics
    -> print one deterministic summary
```

The first phase intentionally keeps the current full merged-config reload. It changes
observability, not symbol resolution or generator inputs. Incremental loading may be considered
later after equivalence tests exist, but it is not required to clean the logs.

The configuration contract is also clarified:

- `platform` on a symbol controls the artifact platforms requested by the gamedata loader.
- skill `platform` controls where an analyzer producer runs.
- `category: struct` declares a struct namespace used by `structmember`; it is not an artifact.
- `alias` maps downstream/generator names to the canonical symbol name.
- `source_alias` lists alternate snapshot artifact basenames for the same canonical symbol.

## Goals

- Print each unique artifact problem once in the final summary.
- Prevent inherited base diagnostics from appearing as generator-specific warnings.
- Preserve generator-specific overlay diagnostics and make their ownership explicit.
- Make diagnostic output deterministic and machine-testable.
- Stop requesting Linux SDL3 artifacts that no configured skill produces.
- Validate invalid or inconsistent symbol configuration before artifact loading starts.
- Stop direct artifact lookup for metadata-only `struct` declarations.
- Preserve the existing `structmember` per-member lookup and legacy struct fallback behavior.
- Resolve known vfunc artifacts whose producer filename differs from the canonical symbol name.
- Keep `alias` and source artifact lookup as separate, unambiguous concepts.

## Non-Goals

- Do not change the candidate snapshot schema.
- Do not change analyzer output filenames except through explicit future migrations.
- Do not derive every symbol field implicitly from skills at runtime.
- Do not remove the legacy struct fallback in this change.
- Do not make all missing YAML fatal in the diagnostic-cleanup phase.
- Do not optimize `_module_data()` into incremental loading before behavioral equivalence is
  covered by tests.
- Do not repurpose existing `alias` values as universal artifact filename fallbacks.
- Do not suppress real overlay-specific missing artifacts.

## Terminology

### Diagnostic Observation

One loader attempt that detects a missing, malformed, or fallback artifact condition while
processing one config context.

The same underlying issue may be observed during the base load and during several merged-config
loads.

### Unique Diagnostic

A diagnostic after aggregation by semantic identity. Its identity must not include the current
generator context, so inherited observations collapse into one issue.

### Base Diagnostic

A unique diagnostic produced while loading the versioned analysis config without a generator
overlay.

### Overlay Delta

A unique diagnostic present in a generator's merged config but absent from the base diagnostic
set. Only this set is printed below that generator's `Updating ...` header.

### Artifact-Bearing Symbol

A symbol category that may resolve platform YAML from the Symbol Store. This includes `func`,
`gv`, `vfunc`, `vtable`, `patch`, and `structmember`.

### Metadata-Only Struct

A `category: struct` symbol used to declare a struct namespace for member definitions. It does
not require `<Struct>.<platform>.yaml` during normal loading.

## Core Invariants

1. Phase 1 must not change `yaml_data`, function-library maps, alias maps, generated gamedata,
   updated counts, or skipped counts.
2. Diagnostic collection is always enabled; `debug` controls rendering detail, not whether
   issues can be deduplicated.
3. A generator header contains only diagnostics introduced by that generator's overlay.
4. A repeated base issue is represented once globally, with all observation contexts attached.
5. Diagnostic ordering is deterministic across local and CI runs.
6. A symbol with `platform: windows` never requests a Linux artifact.
7. A `struct` declaration never performs direct Symbol Store lookup.
8. A `structmember` still prefers its canonical per-member artifact and falls back to the
   legacy `<Struct>.<platform>.yaml` artifact only when required.
9. `alias` continues to mean downstream name mapping and does not participate in source lookup.
10. `source_alias` participates only in source artifact lookup and does not enter the downstream
    alias map.
11. Source aliases are resolved within module, category, and platform context; document order
    must not resolve ambiguity.
12. Strict mode behavior does not become broader until known noise has been removed and the
    remaining diagnostics have been classified.

## Phase 1: Structured Diagnostics And Global Deduplication

### Diagnostic Model

Replace loader-side warning strings with a structured immutable value equivalent to:

```python
@dataclass(frozen=True)
class GamedataDiagnostic:
    reason: str
    severity: str
    module: str
    symbol: str
    category: str
    platform: str
    canonical_path: str
    attempted_paths: tuple[str, ...] = ()
    detail: str | None = None
```

Observation context is aggregation metadata and should not be part of the immutable diagnostic
identity:

```python
@dataclass
class AggregatedDiagnostic:
    diagnostic: GamedataDiagnostic
    contexts: set[str]
    observation_count: int
```

Initial reason values should preserve the distinctions already present in the loader:

- `missing_yaml`;
- `patch_yaml_missing_or_invalid`;
- `structmember_yaml_missing`;
- `structmember_member_missing`;
- `structmember_config_invalid`.

Successful legacy fallback may be recorded as `legacy_struct_fallback_used` at `info` severity,
but it must not be included in the missing-YAML warning count.

The aggregation key must include at least:

```text
reason
module
symbol
category
platform
canonical_path
attempted_paths
```

It must not use only the symbol name or path. Distinct failure modes for the same symbol must
remain visible.

### Loader API

`load_all_yaml_data()` should return diagnostics independently of `debug`:

```python
yaml_data, diagnostics = load_all_yaml_data(
    config,
    symbol_store,
    platforms,
)
```

The loader and its helpers must not print artifact-resolution warnings. They append diagnostic
objects and leave rendering to `update_gamedata.py`.

Exceptions that represent invalid top-level execution state remain exceptions. This phase does
not convert all errors into diagnostics.

### Base And Overlay Comparison

`generate_gamedata()` maintains:

```text
base_diagnostic_keys
global_aggregates
generator_overlay_deltas
```

For a generator with an overlay config:

```text
added     = merged diagnostics - base diagnostics
inherited = merged diagnostics intersect base diagnostics
resolved  = base diagnostics - merged diagnostics
```

Required rendering behavior:

- print `added` below the generator header;
- suppress `inherited` below the generator header;
- include both in global observation counts;
- expose `resolved` only in debug output because it is not a failure;
- generators without `config.yaml` produce no overlay delta.

The word `contexts` should be used instead of `consumers`: a full config reload observing a
missing symbol does not prove that the generator actually consumes that symbol.

### Target Output

Normal output should resemble:

```text
Updating CS2Fixes...
  Using merged config with 1519 function mappings
  Overlay YAML diagnostics: 2
    - server/CTakeDamageInfo_ctor.windows.yaml
    - server/CTakeDamageInfo_ctor.linux.yaml
  Updated: <count>, Skipped: <count>

YAML diagnostic summary:
  Unique warning diagnostics: 130
  Warning observations: 770
  Duplicate observations suppressed: 640
```

Debug output may additionally group unique diagnostics by reason, module, platform, and context.
The final list must be sorted deterministically by severity, reason, module, symbol, platform,
and canonical path.

### Phase 1 Gate

- The observed run reports 130 unique warnings from 770 observations.
- It reports 640 duplicate observations as suppressed.
- The CS2Fixes section lists only its two overlay-added artifacts.
- SDL3 and other base warnings do not appear below any generator header.
- Each unique base warning appears at most once in the final detailed summary.
- Existing gamedata output is byte-identical before and after Phase 1.
- Existing updated and skipped counts are unchanged.

## Phase 2: SDL3 Platform Metadata And Consistency Validation

### SDL3 Migration

Add `platform: windows` to all SDL3 symbols whose configured producers are Windows-only,
including `SDL_PreInitMouse` and the complete mouse-warp analysis chain.

The migration must cover the whole SDL3 symbol set produced exclusively by the six
Windows-only SDL3 skills. It must not update only the first symbol that happened to appear in
the warning log.

The active-config audit found additional single-platform producers outside SDL3. Those active symbols are migrated
in the same phase when the configured producer platform is unambiguous and the opposite-platform artifact is absent
from the candidate. Historical configs remain out of scope.

After migration, the gamedata loader must not request any of these paths:

```text
SDL3/<SDL3-windows-only-symbol>.linux.yaml
```

### Platform Consistency Validator

Add a gamedata symbol config validator rather than placing additional schema logic directly in
`_target_platforms()`.

The validator should build a producer index from the existing skill output declarations,
including required and optional outputs, after platform-specific path expansion. Existing
artifact expansion helpers should be reused instead of reimplementing `{platform}` handling.

Validation rules:

- a symbol `platform` value must be `windows` or `linux`;
- an explicit symbol platform must be compatible with at least one declared producer for its
  canonical artifact or `source_alias` candidates;
- when every known producer for an artifact runs on only one platform, an unrestricted symbol
  is a platform-consistency finding;
- a symbol produced on both platforms may omit `platform`;
- a symbol with no discoverable producer is reported separately and is not assigned an inferred
  platform silently;
- metadata-only `struct` symbols are excluded from producer-platform matching;
- manually supplied or legacy artifacts need an explicit validator escape only if a real case
  exists; do not add a broad default exemption.

Invalid platform tokens and explicit contradictions are errors. Initially discovered implicit
platform findings may be reported as deterministic validation findings while legacy configs are
migrated. The hard gate must be enabled once the active config has no unexplained findings.

Runtime loading continues to use the explicit symbol config. The validator checks drift; it
does not silently rewrite or infer the config during generation.

### Phase 2 Gate

- Every Windows-only SDL3 symbol declares `platform: windows`.
- `SDL3/SDL_PreInitMouse.linux.yaml` and the related false Linux paths are absent from
  diagnostics and Symbol Store lookups.
- An invalid platform token fails validation with module and symbol context.
- An explicit symbol/producer platform contradiction fails validation.
- A fixture with a Windows-only producer and unrestricted symbol produces the expected
  consistency finding.
- A fixture with Windows and Linux producers permits an unrestricted symbol.
- Gamedata output remains byte-identical except for removal of impossible-platform diagnostic
  observations.

## Phase 3: Metadata-Only Structs And Symbol Config Validation

### Struct Semantics

Define `category: struct` as a declaration used by `structmember` entries. It is not an
artifact-bearing category and must not cause direct lookup of:

```text
<module>/<Struct>.windows.yaml
<module>/<Struct>.linux.yaml
```

`load_all_yaml_data()` should skip direct loading for `struct` entries. The preferred behavior
is to omit metadata-only structs from `yaml_data`; structmember resolution already reads its
`struct` field directly from config.

This change must not alter `_load_legacy_struct()` behavior. For a `structmember`:

```text
try <CanonicalMember>.<platform>.yaml
    -> if it contains the requested member, use it
    -> otherwise try legacy <Struct>.<platform>.yaml
    -> if the legacy artifact contains the member, use it
    -> otherwise emit one structured diagnostic
```

The direct `struct` lookup and the structmember legacy fallback use similar filenames but have
different contracts. The implementation and tests must keep them separate.

### Symbol Config Validator

Introduce a focused gamedata symbol validator, preferably in a separate module so
`gamedata_symbol_data.py` remains below the repository file-size limit.

The validator should enforce at least:

- `modules` is a list of mappings;
- every relevant module has a non-empty string name;
- `symbols` is a list of mappings;
- every symbol has a non-empty string `name`;
- every symbol has a supported category;
- symbol names are unique within a module;
- `structmember` has non-empty `struct` and `member` fields;
- a `structmember.struct` references a declared `category: struct` in the same module, unless a
  documented cross-module case requires an explicit exception;
- `struct` does not declare artifact-only fields such as `source_alias`;
- `alias` and `source_alias` accept only a string or a list of non-empty strings;
- duplicate values within either alias list are rejected or normalized deterministically;
- platform validation follows Phase 2 rules.

Validation must run for both the base config and every merged generator config before symbol
loading. A generator overlay validation error follows the existing strict/fallback policy:

- strict mode: fail with generator directory and validation context;
- non-strict mode: report the validation error and fall back to base config;
- never partially apply an invalid overlay.

### Phase 3 Gate

- No `category: struct` entry generates a missing-YAML diagnostic.
- No direct Symbol Store request is made for a metadata-only struct.
- Per-member artifacts continue to take precedence over legacy struct artifacts.
- The existing legacy structmember fallback remains functional.
- Missing `struct` or `member` fields are rejected by validation before loading.
- Unknown categories and malformed aliases are rejected deterministically.
- Base and merged config validation errors contain module, symbol, and field context.
- Generated gamedata is byte-identical before and after the metadata-only struct migration.

## Phase 4: `source_alias` And Vfunc Artifact Migration

### Field Semantics

Add a new symbol field:

```yaml
- name: CNetworkMessages_GetNetworkGroupCount
  category: vfunc
  source_alias:
    - INetworkMessages_GetNetworkGroupCount
  alias:
    - CNetworkMessages::GetNetworkGroupCount
```

The fields have different responsibilities:

| Field | Purpose | Used by source loader | Used by generator name mapping |
| --- | --- | ---: | ---: |
| `name` | Canonical repository symbol identity | Yes | Yes |
| `source_alias` | Alternate snapshot artifact basename | Yes | No |
| `alias` | Downstream/gamedata name mapping | No | Yes |

`source_alias` should accept a string or list in input and normalize to an ordered tuple. The
canonical name is always tried first, followed by source aliases in declared order.

For a vfunc example, resolution becomes:

```text
networksystem/CNetworkMessages_GetNetworkGroupCount.windows.yaml
networksystem/INetworkMessages_GetNetworkGroupCount.windows.yaml
```

The loaded result remains stored in `yaml_data` under the canonical `name`.

### Supported Categories

The source lookup mechanism should be defined consistently for artifact-bearing categories:

- `func`;
- `gv`;
- `vfunc`;
- `vtable`;
- `patch`;
- `structmember` primary per-member artifact.

`struct` must reject `source_alias` because it is metadata-only.

The existing patch compatibility aliases may remain as a temporary compatibility source, but
they should be normalized into the same candidate-building path. Existing downstream `alias`
values must not automatically become source aliases.

### Collision Validation

Source alias resolution must be unambiguous within its lookup namespace. Reject cases where the
same source basename can resolve to different canonical symbols for the same:

```text
module + category + platform
```

Do not use YAML document order or last-write-wins behavior to resolve source alias conflicts.
Existing downstream alias conflicts are a separate issue and must not be imported into source
resolution.

### Known Vfunc Migration

Audit the known vfunc warnings where skills produce interface-prefixed filenames while symbols
use class-prefixed canonical names. Add explicit `source_alias` entries for the complete evidence-backed set.

The implementation audit corrected the original estimate: `28` was the number of missing Windows/Linux paths for
14 canonical names, not the number of resolvable basename mismatches. Nine names only had artifacts in another
module and are intentionally excluded. Five same-module basename candidates remained; one of those,
`CBasePlayerController_Respawn`, is explicitly documented in the active config as removed since game version 14168
and conflicts with the distinct canonical `CCSPlayerController_Respawn`. It is removed as obsolete rather than
assigned an ambiguous source alias. The resulting reviewed migration contains four `source_alias` entries.

For each migrated symbol, verify:

- the declared producer output exists in the candidate snapshot;
- the source alias basename exactly matches the producer output;
- the loaded payload is stored under the canonical symbol name;
- the existing downstream alias mapping is unchanged;
- both Windows and Linux are covered when both artifacts exist;
- no source alias crosses module boundaries.

The migration should be data-driven. Do not add a generic `CNetworkMessages -> INetworkMessages`
string rewrite or another naming heuristic.

### Phase 4 Gate

- All four evidence-backed, non-conflicting vfunc filename mismatches have explicit reviewed `source_alias` entries.
- The obsolete `CBasePlayerController_Respawn` declaration is removed instead of reusing the distinct
  `CCSPlayerController_Respawn` artifact.
- Their existing artifacts load successfully through the new field.
- Their previous false missing-YAML diagnostics disappear.
- A source alias collision fails config validation.
- A missing canonical artifact with a valid source alias succeeds.
- A missing canonical artifact with missing source aliases produces one diagnostic containing all
  attempted paths.
- `alias` behavior in all generators is unchanged.
- Any generated gamedata changes are limited to symbols that were previously omitted solely due
  to the known filename mismatch and are reviewed as expected output changes.

## Test Matrix

### Structured Diagnostic Tests

- One base missing artifact observed by five merged configs produces one unique diagnostic and
  six observations.
- Five inherited observations are suppressed below generator headers.
- A generator overlay adding two missing symbols prints exactly two overlay delta diagnostics.
- An overlay overriding a base symbol and changing its diagnostic identity is reported as a
  delta.
- An overlay resolving a base diagnostic does not print a warning and is visible in debug output.
- Diagnostic ordering is stable regardless of set or dictionary insertion order.
- Debug and non-debug modes use the same diagnostic identity and counts.

### Config Merge Regression Tests

- An overlay that changes only `alias` retains all base symbol fields.
- An overlay that changes only `platform` loads only the merged target platform.
- An overlay appends a new symbol without mutating shared base data.
- One generator's merged data cannot leak into another generator.
- Same-named symbols in different modules preserve the existing merged-config resolution order.
- A generator without `config.yaml` reuses base data and introduces no overlay diagnostics.

### Platform Tests

- An unrestricted symbol with Windows and Linux artifacts loads both.
- A Windows-only symbol never requests Linux.
- Invalid platform values fail validation.
- Explicit platform/producer contradictions fail validation.
- Deterministic one-platform producer drift is reported by the validator.

### Struct Tests

- A metadata-only struct causes zero store reads.
- A structmember uses its per-member artifact when present.
- A structmember falls back to the legacy struct artifact when the primary artifact is missing.
- A primary artifact with the wrong member still permits legacy fallback.
- Primary and legacy artifacts that both lack the member produce one classified diagnostic.
- Multiple members of the same struct/platform reuse the legacy cache.
- Invalid structmember configuration fails before store access.

### Source Alias Tests

- A canonical vfunc filename loads without consulting source aliases.
- A missing canonical vfunc loads from its first existing source alias.
- Multiple missing candidates produce one diagnostic with every attempted path.
- Source aliases do not enter `build_alias_to_name_map()`.
- Downstream aliases do not enter source candidate lookup.
- Source alias collisions within module/category/platform fail validation.
- Identical basenames in different modules remain independent.
- Patch compatibility aliases continue to resolve through the unified source-candidate path.

### Integration Tests

- Replay the motivating candidate and assert 130 unique warnings, 770 observations, and 640
  suppressed duplicate observations before root-cause config migrations.
- After the SDL3, struct, and vfunc migrations, assert the corresponding warning classes are
  absent.
- Assert CS2Fixes reports only the two `CTakeDamageInfo_ctor` overlay delta diagnostics.
- Compare generated output bytes after Phases 1 through 3 with the pre-change candidate.
- Review the Phase 4 output delta and prove every changed symbol was newly resolved through an
  explicit `source_alias`.

## Expected Files To Change During Implementation

- `update_gamedata.py`
  - aggregate diagnostics, compare base and overlay sets, and render summaries.
- `gamedata_symbol_data.py`
  - return structured diagnostics, skip metadata-only structs, and resolve `source_alias`.
- New focused diagnostics module, for example `gamedata_diagnostics.py`
  - diagnostic model, identity, aggregation, sorting, and rendering helpers.
- New focused validator module, for example `gamedata_config_validation.py`
  - symbol schema, platform consistency, struct references, and source alias collision checks.
- New focused symbol-config helper, `gamedata_symbol_config.py`
  - shared category/platform constants plus the intentionally separate downstream-alias and source-candidate rules.
- `configs/14172.yaml`
  - SDL3 symbol platform declarations and known vfunc `source_alias` entries.
- Relevant historical or future version configs
  - only when they are active build targets and contain the same inconsistent declarations;
    do not bulk-edit unrelated historical configs without validation evidence.
- `tests/test_update_gamedata.py`
  - focused loader, diagnostic, struct, platform, and source alias tests.
- New validator-focused test file if needed to keep test ownership clear.
- Candidate/gamedata integration tests
  - motivating-run replay and output equivalence/delta assertions.

## Rollout And Validation

Implementation should land in the same four logical phases even if delivered in one PR. Each
phase must be reviewable independently through commits or clearly separated diffs.

Validation order:

1. Run focused unit tests for diagnostics and the symbol loader.
2. Run config validator tests and validate the active version config.
3. Build an immutable candidate for the target game version.
4. Generate isolated versioned gamedata from that exact candidate.
5. Compare output bytes and diagnostic summaries against the recorded baseline.
6. Run the repository-required post-change validation gate for the same candidate and version.
7. Publish only the exact candidate that passed validation, following the repository candidate
   publication workflow.

Phase 1 through Phase 3 should produce no gamedata byte changes. Phase 4 may recover previously
omitted values; those changes must be enumerated and tied to reviewed `source_alias` entries.

## Acceptance Criteria

The complete plan is accepted when all of the following are true:

1. Base missing-YAML diagnostics are never printed below generator-specific headers.
2. Duplicate observations are globally deduplicated and reported with deterministic counts.
3. CS2Fixes displays only diagnostics introduced by its overlay.
4. Windows-only SDL3 symbols do not request Linux artifacts.
5. Symbol and producer platform inconsistencies are detected before artifact loading.
6. `category: struct` performs no direct artifact lookup.
7. Structmember per-member and legacy fallback behavior remains covered and functional.
8. Invalid symbol configuration fails with actionable module, symbol, and field context.
9. `source_alias` is distinct from downstream `alias` in schema, loading, validation, and tests.
10. All known vfunc filename mismatches are resolved through explicit source aliases, without
    heuristic renaming.
11. Remaining warnings represent real missing, malformed, or unresolved artifacts rather than
    duplicated observations or known configuration mismatches.
12. Required repository validation passes for the immutable candidate used to generate the
    reviewed gamedata output.
