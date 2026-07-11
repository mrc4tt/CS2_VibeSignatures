---
name: run-validation-until-no-failure
description: |
  Use when the user wants to run the IDA validation pipeline (`uv run ida_analyze_bin.py -debug`)
  repeatedly until it reports zero failures, recording each failing skill's reason and disabling it
  in config.yaml so the run can proceed. Use after a game-version bump or a large batch of new skills
  when several skills may fail and you want an automated triage-and-quarantine pass.
  Triggers: run validation until no failure, validate until green, get validation passing,
  disable failing skills, quarantine failing skills, loop ida_analyze_bin until no failures
disable-model-invocation: true
---

# Run Validation Until No Failure

Loop the analysis/validation pipeline until it reports **`Failed: 0`**. Each iteration: run
`ida_analyze_bin.py -debug`; if a skill failed (the pipeline is fail-fast, so it's exactly one),
record *why* in a dated doc and comment that skill out of `config.yaml`. Then run the unittest suite
before resuming validation. If the config dependency test reports consumers whose `expected_input`
can no longer be produced, quarantine those dependent skills one at a time and re-run unittest until
it passes. Environment / infrastructure failures are **not** skill bugs — STOP and surface those
instead of quarantining a skill.

## When to Use

- The user asks to "run validation until it passes / until no failures", "get validation green", or
  "disable the failing skills and keep going".
- After bumping to a new game version or landing many new skills, to triage a wave of failures — each
  gets quarantined with its reason for later fixing.

## Why the loop works (pipeline facts)

- `uv run ida_analyze_bin.py -oldgamever none -debug` ends with a summary and exits non-zero when `Failed > 0`:
  ```
  ============================================================
  Summary
  ============================================================
    Successful: N
    Failed: N
    Skipped: N
  ```
- It is **fully fail-fast**: the first failing skill aborts the remaining skills, the remaining
  platforms, **and** the remaining modules. So each run surfaces **exactly one** actionable failing
  skill — that is why you disable one skill per iteration.
- Skills whose `expected_output` YAML already exist on disk are **skipped** on re-runs, so each
  iteration advances quickly to the next unresolved skill.

## Safety Rules — STOP conditions (never loop forever)

- **Infra / environment failure → STOP and report.** If the failure is not attributable to a
  specific skill's logic, do **not** comment out a skill. Signals:
  - `Failed: IDB lock file detected (...)`
  - `Failed: opened binary verification failed` / `Aborting current binary after opened binary verification failure`
  - `Failed to restore MCP connection ...`
  - `Error: Binary file not found` or any `idalib-mcp` startup error
  These mean the toolchain / binary / IDB is broken, not the skill. Fix the environment or ask the user.
- **`-gamever` required error → STOP.** The command relies on `$CS2VIBE_GAMEVER`. If the run errors,
  `{gamever}` can be obtained from `.env` -> `CS2VIBE_GAMEVER`,
  gamever is required, ask the user for the version if not specified.
- **No progress → STOP.** If a run's failing skill is the *same* one you just commented (the config
  edit didn't take), or the `Failed` count did not go down, STOP and report. Never re-comment the same
  block or force past it.
- **Unrelated unittest failure → STOP and report.** Only dependency gaps reported by
  `TestConfigSkillDependencyGraph.test_config_module_skills_have_no_expected_input_order_gaps` may
  quarantine more skills. Do not hide failures from any other test, exception, import error, or test
  infrastructure problem by commenting out config entries.
- **Only** two kinds of edits are allowed: append to the dated failure doc, and comment (prefix `#`)
  a validation-failing skill or dependency-broken descendant's block in `config.yaml`. Comment one
  skill block at a time, re-run the relevant gate, do not delete config entries, do not touch unrelated
  skills, and do not uncomment anything.

## Method

### Step 1 — Run validation; capture full log + summary

```bash
uv run ida_analyze_bin.py -oldgamever none -debug > /tmp/ida_validation_output.txt 2>&1; tail -15 /tmp/ida_validation_output.txt
```

The full log goes to `/tmp/ida_validation_output.txt`; `tail -15` is only for the pass/fail verdict.

### Step 2 — Read the verdict from the summary

From the `tail` output, read `  Failed: N`.

- `Failed: 0` → **DONE.** Report success and stop the loop.
- `Failed: N` (N ≥ 1) → continue. (Fail-fast means one actionable skill; `N` counts the pending work
  items that one failure aborted.)

### Step 3 — Identify the failing skill + its module + platform (from the FULL log)

The per-skill failure detail is not reliably in the last 15 lines — parse the whole file. Find the
last real failure signal (the pattern excludes the `Failed: N` summary line):

```bash
grep -nE "^  (Failed: [^0-9]|Pre-processed but missing expected_output:|Preprocess failed:)" /tmp/ida_validation_output.txt | tail -5
```

The failing skill is named on that line (or, on the agent-fallback path, on the last
`  Processing skill: <skill>` immediately followed by a bare `    Failed`). Then read upward for
context:

- **Module** = nearest preceding `Module: <module_name>` header.
- **Platform** = nearest preceding `  Platform: <platform>` line.
- **Reason** = the indented lines of that skill's block (e.g. `missing expected_input: ...`,
  `Skill file not found: ...`, preprocess diagnostics).

Now apply the **Safety Rules**: if this is an infra failure, STOP here.

### Step 4 — Append the failure reason to the dated doc

Compute the date once as ISO `YYYY-MM-DD` (`date +%F`). File: `docs/validation_failure-<DATE>.md`.
Create it if missing, otherwise **append** a new section (several skills can fail across iterations on
the same day). Record: skill name, module, platform, the verbatim failure block from the log, and a
one-line diagnosis.

```markdown
## find-ConnectInterfaces  (module: engine2, platform: windows/linux)

Failure (from `ida_analyze_bin.py -debug`):

    Start skill: find-ConnectInterfaces
      Preprocess: no old YAML for ConnectInterfaces.windows.yaml
      Preprocess: trying func_xrefs fallback for ConnectInterfaces
      Preprocess: exclude_func YAML missing or invalid: CNetSupportImpl_Connect.windows.yaml
      Preprocess: failed to locate ConnectInterfaces
    Preprocess failed: find-ConnectInterfaces; falling back to AGENT SKILL
    Processing skill: find-ConnectInterfaces
      Falling back to: .claude\skills\find-ConnectInterfaces\SKILL.md
      Error: Skill file not found: .claude\skills\find-ConnectInterfaces\SKILL.md
      Failed

Diagnosis: preprocessor could not locate ConnectInterfaces and no agent SKILL.md exists to fall back
to. Needs a preprocessor fix or a find-ConnectInterfaces SKILL.md.
```

### Step 5 — Comment the failing skill out of config.yaml

Comment the skill's entire list-item block **under the correct module**, and add one `Awaiting fix`
line above it that points at the dated doc. The rule: insert a `#` right after the 6-space base indent
on every line of the block, keeping `{platform}` placeholders verbatim (this disables it for all
platforms).

Before:

```yaml
      - name: find-ConnectInterfaces
        expected_output:
          - ConnectInterfaces.{platform}.yaml
        expected_input:
          - CNetSupportImpl_Connect.{platform}.yaml
```

After:

```yaml
      #  Awaiting fix, failure reason has been written into "docs/validation_failure-2026-07-09.md"
      #- name: find-ConnectInterfaces
      #  expected_output:
      #    - ConnectInterfaces.{platform}.yaml
      #  expected_input:
      #    - CNetSupportImpl_Connect.{platform}.yaml
```

The block runs from its `- name:` line (6-space indent) through every more-indented line until the
next `- name:` at the same level, or a dedent.

**Disambiguation (important):** the same skill name can appear under several modules (e.g.
`find-ConnectInterfaces` exists in 3 modules). Comment **only** the one under the `Module:` you found
in Step 3. Use the Edit tool with an `old_string` that includes the *preceding sibling skill entry*
(which differs per module) so the match is unique — a bare block match would silently hit the wrong
module.

### Step 6 — Run unittest after every config.yaml quarantine

Immediately after commenting out any skill block, run the non-MCP unittest suite:

```bash
uv run python -c "from pathlib import Path; import sys, unittest; excluded={'test_ida_mcp_session', 'test_smoke_ida_mcp_2'}; modules=[f'tests.{path.stem}' for path in Path('tests').glob('test_*.py') if path.stem not in excluded]; result=unittest.TextTestRunner(buffer=True).run(unittest.defaultTestLoader.loadTestsFromNames(modules)); sys.exit(not result.wasSuccessful())"
```

The command excludes the IDA MCP adapter and smoke modules (`test_ida_mcp_session`,
`test_smoke_ida_mcp_2`) because this loop does not modify MCP routing or lifecycle code. Run them
separately whenever MCP code changes.

- **All tests pass** → the active `config.yaml` dependency chain is intact; continue to Step 7.
- **Only**
  `TestConfigSkillDependencyGraph.test_config_module_skills_have_no_expected_input_order_gaps`
  fails → inspect its dependency-gap list. Each entry identifies a consumer whose `expected_input`
  is no longer produced, for example:

  ```text
  windows module[2] server/find-ChildSkill missing: _artifacts/server/Parent.windows.yaml
  ```

  Here `server/find-ChildSkill` is the child skill to quarantine. Append its unittest failure and a
  one-line dependency diagnosis to the same dated failure doc, then comment that child's full block
  under the named module using the Step 5 rules. Re-run the full unittest suite immediately.
- **Any other unittest failure** → STOP and report it. It is not evidence that another skill should
  be quarantined.

Quarantine one unique child skill per unittest iteration. A child may be listed once per platform;
comment its all-platform `{platform}` block only once. Keep following newly exposed descendants and
re-running unittest until the suite passes. Do not return to IDA validation while unittest is red.

### Step 7 — Resume the validation loop

Go back to Step 1. The just-disabled skill is now skipped, and previously-successful skills are
skipped (their outputs exist), so the next run reaches the next failure quickly. Repeat until
`Failed: 0` (DONE) or a STOP condition trips.

> **Cascading is expected and must be resolved before validation resumes.** Disabling a producer can
> break a consumer whose `expected_input` names the disabled output. The unittest dependency graph
> catches this immediately, even when stale YAML artifacts would otherwise let the validation run
> skip past the broken config chain. Quarantine descendants until unittest passes, and call the full
> dependency chain out in the report.

## Quick reference — failure signal lines

| Log line (2-space indent) | Meaning | Action |
|---|---|---|
| `Failed: <skill> (missing expected_input: ...)` | dependency YAML absent | quarantine skill |
| `Failed: <skill> (invalid expected_input ...)` | dependency YAML malformed | quarantine skill |
| `Pre-processed but missing expected_output: <skill> (...)` | preprocess ran, output not written | quarantine skill |
| `Preprocess failed: <skill>; falling back to AGENT SKILL` → `    Failed` | preprocess AND agent fallback failed | quarantine skill |
| `Failed: <skill> (<exception>)` | skill raised | quarantine skill |
| `Failed: IDB lock file detected ...` | stale lock / another IDA instance | **STOP** (infra) |
| `Failed: opened binary verification failed` | wrong/broken binary open | **STOP** (infra) |
| `Failed to restore MCP connection ...` | idalib-mcp died | **STOP** (infra) |
| unittest dependency gap: `<module>/<skill> missing: <artifact>` | active consumer has no active producer | quarantine that child, re-run unittest |
| any other unittest failure | unrelated code/test/infrastructure failure | **STOP** |

## Notes

- `tail -15` is only for the verdict; always parse the **full** `/tmp/ida_validation_output.txt` to
  identify the failing skill and its reason.
- IDA validation quarantines one skill per iteration (fail-fast). The mandatory unittest loop may
  quarantine several dependency descendants, still one block per unittest iteration.
- Never run the next IDA validation iteration until the non-MCP unittest command above passes with
  zero failures.
- Purely additive to `config.yaml` (commenting only). Re-enabling a skill once it's fixed is a
  separate manual step — the commented blocks plus the dated doc are the resulting to-do list.
- This skill does not `git commit`; leave staging/committing to the user unless they ask.
