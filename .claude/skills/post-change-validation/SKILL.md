---
name: post-change-validation
description: |
  Run the repository's C++ post-change validation gate with run_cpp_tests.py before snapshot packing and commit.
  Use when a project workflow explicitly requests final C++ validation after formatting and gamedata updates.
  Any failed, skipped, or non-runnable validation stops the calling task and must be reported to the user.
disable-model-invocation: true
---

# Post-Change Validation

Run `run_cpp_tests.py` as a hard pre-commit gate. This skill validates only; never edit files, repair failures,
pack a snapshot, stage changes, or commit.

## Inputs

- `gamever` — use the caller-provided value. If omitted, read `CS2VIBE_GAMEVER` from `.env`.

If no non-empty game version is available, stop immediately:

```text
<skill_error>post-change-validation cannot run: gamever was not provided and .env has no CS2VIBE_GAMEVER.</skill_error>
```

## Method

### Step 1 — Run the C++ validation and retain the full log

Use the resolved game version explicitly:

```bash
LOG_FILE="/tmp/post-change-validation-${GAMEVER}.log"
set -o pipefail
uv run run_cpp_tests.py -gamever "$GAMEVER" -debug 2>&1 | tee "$LOG_FILE"
STATUS=${PIPESTATUS[0]}
```

Do not hide or normalize the exit code. Preserve the complete log so compile diagnostics and layout differences
can be reported verbatim.

### Step 2 — Require evidence that tests actually ran

Validation succeeds only when all of the following are true:

- `STATUS` is `0`.
- The log contains both `=== running cpp_tests ===` and `=== done ===`.
- The final counters report zero compile failures, invalid test items, and layout differences.
- The log does not contain `No cpp_tests defined`, `No target triples found`, or
  `No runnable tests for current clang++ environment.`

An exit code of zero without runnable tests is not a successful validation; treat it as blocked and stop.

### Step 3 — Stop and report any failure

On any failed or non-runnable result, inspect the full log and report:

- game version and process exit code;
- every failing test name;
- whether the cause was compilation, invalid configuration, vtable/record layout differences, or an unusable
  clang environment;
- the relevant compiler diagnostic or layout-difference lines;
- the full log path.

Use this form:

```text
<skill_error>post-change-validation failed for gamever GAMEVER: FAILURE_REASON. Full log: LOG_FILE</skill_error>
```

Then **STOP the entire calling task**. Do not attempt a fix or retry, do not invoke
`/post-change-update phase=after-validation`, and do not enter any commit step.

### Step 4 — Report success

When the gate passes, report the game version and the zero-valued failure counters. The caller may then invoke
`/post-change-update phase=after-validation` for the same game version.
