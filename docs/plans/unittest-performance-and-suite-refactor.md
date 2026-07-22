# Python Unittest Performance And Suite Refactor

## Status

Implemented on 2026-07-22 across four independently validated commits.

The phases are intentionally ordered. Each phase must preserve the existing regression guarantees and pass its own
acceptance gate before the next phase starts:

1. Isolate sockets, HTTP server shutdown, and real repository configuration from unit tests.
2. Introduce a `CSafeLoader` fallback and cache repeated reference/config parsing.
3. Split repository-contract, Redis, and Git release-transaction tests out of the fast unit suite.
4. Remove one-time migration guards and replace workflow string tests with semantic contract tests.

## Background

The current completion gate runs:

```powershell
uv run python -m unittest discover -s tests -b
```

A measured baseline on 2026-07-22 produced:

- 1,030 passing tests.
- 57.014 seconds reported by `unittest`.
- 58.324 seconds of wall-clock time.
- 13 tests taking at least one second and accounting for 31.339 seconds, or 55.0% of total test time.
- The five slowest tests accounting for 22.678 seconds, or 39.8% of total test time.

The runtime is therefore concentrated rather than uniformly distributed. The main causes are:

- unit tests crossing an unmocked local socket boundary and waiting for one-second connection timeouts;
- a per-test `HTTPServer` shutdown using the default 0.5-second polling interval;
- unit tests reading and parsing the real 420-KB repository configuration despite mocking the primary config parser;
- repeated pure-Python YAML parsing of large configs, snapshots, and reference artifacts;
- repository-wide consistency checks, Redis integration tests, and Git transaction tests running in the same fast-feedback
  suite as isolated unit tests;
- one-time migration assertions and workflow source-text assertions remaining as permanent unit tests.

This plan improves both execution time and test signal. It does not weaken the full validation gate.

## Goals

- Make the default fast unit suite deterministic, isolated, and suitable for local edit-test loops.
- Remove real socket timeouts and avoidable server-shutdown waits from unit tests.
- Ensure mocked `main()` tests do not read the real repository configuration.
- Parse trusted repository YAML through a compatible C-backed safe loader when available.
- Parse each unchanged config or reference artifact at most once per test process or operation.
- Preserve repository-contract, Redis, and release-transaction coverage in explicit suites.
- Replace one-time migration guards with durable generic validators where the invariant remains important.
- Test GitHub Actions workflow semantics without binding tests to comments, formatting, or unrelated command spelling.
- Keep one command that executes every test assigned to every suite.

## Non-Goals

- Do not delete coverage merely because a test is slow.
- Do not mock away Redis behavior in the Redis integration suite.
- Do not replace Git-backed release transaction coverage with unit-only mocks.
- Do not change canonical snapshot bytes or config-digest semantics while introducing the C-backed YAML loader.
- Do not add `pytest` solely to obtain markers; the suite split should remain compatible with the standard-library
  `unittest` runner unless a separate dependency decision is approved.
- Do not make wall-clock thresholds hard CI failures across heterogeneous machines. Performance budgets are measured on a
  stable reference machine and used as regression signals.

## Execution Principles

1. Preserve behavior before reorganizing suites.
2. Record `--durations 0` output before and after every phase.
3. Keep targeted tests green before running the full suite.
4. Assign every discovered test to exactly one primary suite in Phase 3.
5. Keep an aggregate `all` command that proves no test was lost during classification.
6. Avoid combining a suite move with an unrelated behavioral rewrite.
7. Use three consecutive runs and compare the median when evaluating performance.

## Phase 1: Isolate Unit-Test Runtime Boundaries

### Objective

Remove avoidable socket, server-shutdown, and repository-config I/O from tests that are intended to be isolated units.
This phase must not change production behavior.

### 1.1 Mock Local Socket Probes

The following test paths indirectly call `is_port_in_use()` or `wait_for_port_release()` without controlling the socket
boundary:

- MCP recovery-budget tests.
- `start_idalib_mcp` process-construction tests.
- opened-binary mismatch tests covering skill, agent fallback, vcall export, and post-processing aborts.

On Windows, `socket.create_connection(..., timeout=1)` can consume approximately one second per test. The affected tests
currently account for roughly 6.1 seconds.

Implementation:

- Patch `ida_analyze_bin.is_port_in_use` in every test whose subject is not port probing.
- Patch `ida_analyze_bin.wait_for_port_release` where the test only verifies abort or cleanup control flow.
- Continue testing `is_port_in_use` and `wait_for_port_release` themselves separately with controlled socket/time inputs.
- Add a shared test helper only if it reduces duplication without hiding which boundary is mocked.
- Assert that the expected socket helper was or was not called when that interaction is part of the behavior.

Acceptance criteria:

- No ordinary `ida_analyze_bin` unit test opens or probes a real TCP connection.
- Dedicated socket-helper tests remain present.
- The affected test group no longer contains approximately one-second cases.
- All existing result, call-count, and abort-order assertions remain intact.

### 1.2 Shorten `HTTPServer` Shutdown Polling

`TestCallLlmTextCodexHttp` creates and shuts down an `HTTPServer` for each test. `serve_forever()` uses a 0.5-second
polling interval by default, so seven otherwise-small tests account for approximately 3.6 seconds.

Implementation:

- Start the server with an explicit small polling interval, such as `0.01` seconds.
- Prefer a named server-thread target helper instead of an anonymous lambda so failures remain diagnosable.
- Evaluate class-level server reuse only if mutable handler state can be reset reliably between tests.
- Keep per-test request bodies, response events, headers, and captured-message state isolated.
- Keep at least one real localhost HTTP/SSE boundary test; do not replace this whole class with method mocks.

Acceptance criteria:

- The class still exercises actual HTTP request encoding and SSE response parsing.
- No test depends on execution order or state left by a previous test.
- The class runtime is no longer dominated by server shutdown polling.

### 1.3 Isolate Real Repository Configuration Reads

Several `ida_analyze_bin.main()` tests mock `parse_config` but still read `configs/14168.yaml` through
`_load_artifact_symbol_category_map()` and `_load_symbol_alias_map()`. This couples isolated orchestration tests to a
large historical repository fixture and contributes approximately 2.3 seconds.

Implementation:

- For tests focused on `main()` orchestration, either:
  - patch both config-derived map loaders with minimal deterministic maps; or
  - point `args.configyaml` to a minimal temporary config used by the test.
- Prefer a temporary minimal config when the test needs to prove coordination between the three config consumers.
- Prefer direct loader mocks when the test is only about exit status, call ordering, reporter finalization, or option
  forwarding.
- Ensure repository-config tests remain responsible for exercising real tracked config files.

Acceptance criteria:

- Mocked `main()` tests do not open `configs/14168.yaml` or another tracked large config unless that read is their stated
  subject.
- Tests that validate actual repository configuration remain unchanged until Phases 2 and 3.
- The `main()` orchestration tests retain their existing behavior and interaction assertions.

### Phase 1 Validation

Run targeted tests first:

```powershell
uv run python -m unittest tests/test_ida_analyze_bin.py -b --durations 0
uv run python -m unittest tests/test_ida_llm_utils.py -b --durations 0
```

Then run the unchanged full gate:

```powershell
uv run python -m unittest discover -s tests -b --durations 0
```

Expected result on the reference machine: approximately 10 seconds or more removed without moving or deleting tests.

## Phase 2: Accelerate And Cache Trusted YAML Parsing

### Objective

Reduce repeated CPU-bound parsing while preserving the exact loaded data, validation behavior, digest values, and
canonical snapshot bytes.

Measured parsing benchmarks on the reference machine were:

- Three loads of `configs/14172.yaml`: `safe_load` 0.876 seconds; `CSafeLoader` 0.112 seconds.
- 419 reference YAML files: `safe_load` 1.798 seconds; `CSafeLoader` 0.065 seconds.
- Two approximately 1.16-MB snapshots: `safe_load` 2.062 seconds; `CSafeLoader` 0.319 seconds.

### 2.1 Introduce A Safe Loader Fallback

Define the loader using the C implementation when installed and the existing Python implementation otherwise:

```python
SAFE_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
```

Use it only for trusted repository and generated YAML currently loaded through `yaml.safe_load`. Do not switch canonical
dumping without separately proving byte-for-byte output stability.

Implementation requirements:

- Centralize the fallback in the narrowest shared module that avoids duplicated loader selection.
- Compare `SafeLoader` and the selected loader on representative configs, snapshots, reference YAML, empty documents,
  Unicode input, anchors, and malformed input.
- Preserve the current exception translation at public boundaries.
- Preserve UTF-8 and UTF-8-with-BOM handling.
- Keep `SafeLoader` behavior available on environments where LibYAML is unavailable.

Acceptance criteria:

- The loaded Python structures are equal for representative repository fixtures.
- Existing config SHA-256 and snapshot validation tests produce unchanged values.
- Malformed YAML continues to fail through the same public exception types.
- Canonical snapshot bytes do not change.

### 2.2 Parse Config Documents Once

`gamesymbol_snapshot_lib.config.load_contract()` currently loads raw config data for digest normalization and then calls
`ida_analyze_bin.parse_config()`, which opens and parses the same file again. `ida_analyze_bin.main()` also derives
category and alias maps through separate config loads.

Implementation:

- Extract a pure `parse_config_document(config: dict)` transformation behind `parse_config(path)`.
- Let `load_contract()` reuse the already-loaded raw document for module parsing.
- Let `main()` derive modules, artifact categories, and aliases from one loaded document where practical.
- If a process-level cache remains necessary, key it by resolved path plus file identity such as `mtime_ns` and size;
  path-only caching must not return stale values after a config is rewritten in a test or long-running process.
- Keep explicit cache-clear support for tests when process-level caches are introduced.

Acceptance criteria:

- A single `load_contract()` operation parses its config bytes once.
- A single `main()` startup does not parse the same unchanged config independently for modules, categories, and aliases.
- Tests covering rewritten temporary configs prove cache invalidation.

### 2.3 Cache Reference YAML Parsing

`test_all_llm_specs_have_complete_policy_and_config_contract` performs approximately 670 YAML loads while the repository
contains 419 reference YAML files. Some reference paths are therefore parsed repeatedly.

Implementation:

- Cache parsed reference payloads by resolved path and file identity for the lifetime of the repository-contract run.
- Cache `_config_data()` results instead of parsing the same config once per skill under test.
- Keep missing-file assertions outside the cache so diagnostics still identify the exact config, script, platform, and
  reference.
- Return immutable or defensively copied cached values if a caller could mutate them.

Acceptance criteria:

- Each unchanged reference YAML is parsed at most once per process.
- Each unchanged config is parsed at most once per repository-contract operation.
- Subtest diagnostics retain their current artifact context.

### 2.4 Skip Unrequested Canonical Serialization

`load_snapshot_for_contract(..., require_canonical=False)` currently computes canonical snapshot bytes unconditionally
and only gates the comparison. Avoid canonical serialization when the caller explicitly does not require it.

Acceptance criteria:

- `require_canonical=True` retains byte-for-byte canonical enforcement.
- `require_canonical=False` still parses and validates the complete snapshot contract.
- Tests cover both branches.

### Phase 2 Validation

```powershell
uv run python -m unittest tests/test_analysis_config.py -b --durations 0
uv run python -m unittest tests/test_gamesymbol_snapshot_versioning.py -b --durations 0
uv run python -m unittest tests/test_llm_decompile_dependencies.py -b --durations 0
uv run python -m unittest tests/test_config_scheduling_dependencies.py -b --durations 0
uv run python -m unittest discover -s tests -b --durations 0
```

Record loader compatibility results and before/after timings in the implementing change.

## Phase 3: Split Fast Unit, Repository Contract, Redis, And Release Suites

### Objective

Make the default suite represent isolated fast feedback while retaining explicit execution of every integration and
repository-level test.

### Suite Model

Introduce a standard-library suite runner, for example `tests/run_test_suite.py`, with these stable suite names:

```text
unit
repository-contract
redis-integration
release-integration
all
```

The runner may use explicit module/class registration initially. It must fail if a newly discovered test is unassigned
or assigned to more than one primary suite.

Recommended commands:

```powershell
uv run python tests/run_test_suite.py unit -b --durations 30
uv run python tests/run_test_suite.py repository-contract -b --durations 30
uv run python tests/run_test_suite.py redis-integration -b --durations 30
uv run python tests/run_test_suite.py release-integration -b --durations 30
uv run python tests/run_test_suite.py all -b --durations 30
```

The exact CLI can change during implementation, but the named boundaries and aggregate coverage are required.

### 3.1 Repository-Contract Suite

Move or register tests whose subject is the state of the checked-in repository rather than a function in isolation,
including:

- historical config/snapshot compatibility fixtures;
- repository-wide LLM dependency-policy validation;
- config scheduling/dependency validation;
- architecture/import-boundary scanning;
- tracked config registration checks;
- other tests that glob or recursively scan the repository.

These tests remain required in CI. They should run when configs, snapshots, preprocessors, references, or relevant
validators change, and in the aggregate `all` gate.

### 3.2 Redis Integration Suite

Move the real Redis classes from:

- `test_process_reporter_redis.py`;
- `test_process_scheduler_redis.py`;
- `test_process_status_reader_redis.py`.

Keep pure key-building, configuration, and request-domain tests in the unit suite. Real Redis ping, Lua/script behavior,
TTL expiry, streams, consumer groups, and subprocess scheduling belong to `redis-integration`.

The heartbeat-expiry test may retain a real wait in this suite because Redis TTL expiry is server-clock behavior. Unit
coverage should separately validate heartbeat scheduling and close behavior without waiting for Redis expiry.

### 3.3 Git Release-Transaction Suite

Move or register the Git/filesystem transaction tests from:

- `test_release_workflow.py`;
- `test_release_workflow_guards.py`;
- `test_completed_release_cleanup.py`;
- `test_release_gamedata_smoke.py`.

These tests exercise valuable transaction boundaries and must not be deleted. They currently account for approximately
12.5 seconds and belong in `release-integration` because they build temporary repositories, stage candidates, execute
Git commands, and verify crash-safe filesystem transitions.

Small pure functions extracted from the release workflow may receive unit tests in the fast suite, but the integration
tests remain the authority for complete transactions.

### 3.4 CI And Completion-Gate Ordering

Recommended order:

1. formatting check;
2. fast unit suite;
3. repository-contract suite;
4. Redis integration suite when Redis is provisioned;
5. release integration suite;
6. aggregate `all` suite during migration until suite-assignment auditing is proven reliable.

Independent suites may run in parallel in CI after the classification is stable. Local completion documentation should
name both the fast command and the required full command.

### Phase 3 Acceptance Criteria

- Every discovered test belongs to exactly one primary suite.
- `all` executes the union of all primary suites.
- Test counts are printed per suite and in aggregate.
- Missing Redis causes a clear integration-suite skip/failure policy rather than silently changing unit coverage.
- Git release tests run on every supported platform where their production workflow is supported.
- The median fast-unit runtime target is 20 seconds or less on the reference machine.
- The full aggregate suite remains green.

## Phase 4: Remove Migration Guards And Test Workflow Semantics

### Objective

Reduce permanent maintenance cost after generic validators and explicit suite boundaries are in place.

### 4.1 Remove One-Time Migration Guards

Delete dedicated tests whose only purpose was proving that a completed repository migration happened once, after their
durable invariant is covered generically.

Initial candidates:

- `test_execute_queued_deletion_skills_are_split`.
- `test_all_configs_declare_required_scheduling_inputs` after the dependency requirement is enforced by the config
  validator or schema.
- config-specific registration tests such as `test_config_registers_gamepostinit_skill_and_symbol` when the same
  relationship is covered by generic producer/dependency validation.
- absence checks for retired names that are already impossible under the current schema or producer registry.

Before deletion, classify each assertion as one of:

- generic invariant: move it into a validator and keep validator tests;
- historical compatibility: replace it with a minimal checked-in regression fixture;
- one-time migration evidence: delete it;
- current repository content policy: retain it in `repository-contract` with a current, non-historical source of truth.

The fixed-commit historical config digest test should not depend on `git show <commit>:<path>`. Preserve the regression
with a minimal checked-in fixture containing only the fields necessary to reproduce the digest behavior.

### 4.2 Replace Workflow Source-Text Assertions

The workflow tests currently contain dozens of exact substring and `.index()` assertions. These bind tests to step
names, comments, formatting, and embedded PowerShell spelling even when workflow semantics are unchanged.

Implementation:

- Load workflow YAML with a loader that preserves GitHub Actions keys such as `on` correctly.
- Address jobs and steps by stable job names and explicit step `id` values.
- Assert semantic fields: triggers, permissions, `if` conditions, environments, `uses`, inputs, outputs, and required
  ordering dependencies.
- Extract complex embedded PowerShell into versioned `.ps1` or Python helpers where it has independently testable logic.
- Unit-test extracted script/helper behavior with structured inputs and outputs.
- Retain a small number of source-text assertions only for security-sensitive negative guarantees that cannot be
  represented structurally, and document why each remains text-based.
- Prefer one contract test per workflow responsibility instead of one test per historical incident.

Important workflow invariants to retain include:

- unit tests run before analysis;
- candidate build/compare occurs before gamedata and C++ validation;
- publication cannot occur before validation;
- PR validation never publishes accepted state;
- release promotion remains bound to the accepted merge and staged identity;
- cleanup commands retain their path and reparse-point safety gates.

### 4.3 Architecture Checks

Replace substring-based architecture tests with semantic checks:

- use AST import/call analysis for forbidden production dependencies;
- use a lint rule or tracked-file inventory for repository-wide import boundaries;
- avoid failing because a forbidden token appears in a comment, error message, or unrelated identifier;
- retain actionable diagnostics with file and line number.

### Phase 4 Acceptance Criteria

- Formatting-only workflow changes do not break semantic tests.
- Removing a required job, permission, gate, command, or ordering dependency does break the appropriate test.
- No test invokes a fixed historical Git commit solely to reconstruct a large regression fixture.
- Every removed migration test is mapped to a generic invariant, minimal regression fixture, or documented one-time
  deletion rationale.
- Workflow and architecture test failures identify the violated contract rather than only a missing string.

## Performance Budgets

Budgets are evaluated as the median of three consecutive runs on the same reference machine:

- Fast unit suite: target 20 seconds or less.
- No isolated unit test: target greater than 0.5 seconds only with an explicit allowlist rationale.
- Full aggregate suite after Phases 1 and 2: target at least 25% faster than the 57.014-second baseline.
- Repository-contract and integration suites: report the 30 slowest tests, but do not impose a cross-machine hard timeout
  until stable CI history exists.

Store benchmark output in the implementing PR description or CI summary rather than committing machine-specific timing
artifacts.

## Validation And Delivery Gate

Every phase must run:

```powershell
uv run python format_repo_files.py --check
uv run python -m unittest discover -s tests -b --durations 0
```

After Phase 3 introduces the suite runner, replace the second command in completion documentation with the aggregate
suite command while continuing to run the legacy discovery command temporarily as a migration cross-check.

Completion evidence must include:

- test counts;
- pass/fail/skip totals;
- median wall-clock timing from three runs;
- the 30 slowest tests;
- proof that no test is unassigned or duplicated across primary suites;
- confirmation that the working tree contains no generated timing artifacts.

## Suggested Commit Sequence

1. `test(unittest): isolate socket http and config boundaries`
2. `perf(yaml): use safe C loader and cache parsed artifacts`
3. `test(suites): split unit contract redis and release tests`
4. `refactor(tests): replace migration and workflow text guards`

Each commit should be independently reviewable and keep the aggregate test gate green.

## Expected Outcome

After all four phases:

- local unit feedback should complete in approximately 15-20 seconds on the reference machine;
- the full regression gate should retain repository, Redis, and release transaction coverage;
- large trusted YAML files should no longer be repeatedly parsed through the slow pure-Python path;
- unit tests should not wait on real sockets, server shutdown polling, Redis expiry, or Git transactions;
- workflow tests should protect behavior rather than incidental source formatting;
- completed migrations should no longer impose permanent high-cost tests unless they represent a durable invariant.
