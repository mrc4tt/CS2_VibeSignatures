# run_cpp_tests

## Overview

`run_cpp_tests.py` is a deterministic C++ compile and layout-validation driver based on `config.yaml`. It probes clang
target support, runs compatible tests, compares compiler vtable or record layouts with YAML references, prints detailed
differences, and returns non-zero when validation fails. Header repair is intentionally outside this script.

## Responsibilities

- Parse config path, bin directory, game version, clang path, C++ standard, and debug options.
- Validate `cpp_tests` entries and compile supported targets.
- Compare vtable layouts when `fdump-vtable-layouts` is configured.
- Compare record layouts when `fdump-record-layouts` is configured.
- Compare every configured `reference_module` and report structured differences.
- Return failure for compile errors, invalid test entries, or layout differences.

## Header Repair Boundary

- Use the project-level `.claude/skills/fix-cppheaders/SKILL.md` for header repair.
- The SKILL runs `uv run run_cpp_tests.py -gamever <gamever> -debug` to obtain current layout differences.
- `cpp_tests[].headers` maps a failing test to the allowed `hl2sdk_cs2` edit targets.
- `run_cpp_tests.py` does not invoke Claude, Codex, OpenCode, or `agent_runner.py`.

## Involved Files

- `run_cpp_tests.py`
- `cpp_tests_util.py`
- `config.yaml`
- `.claude/skills/fix-cppheaders/SKILL.md`
- `bin/<gamever>/<module>/*.yaml`

## Notes

- `additional_compiler_options` and `additional_compile_options` are both accepted.
- Unsupported target triples are skipped rather than failed.
- Missing `symbol`, `cpp`, or `target`, and missing C++ sources, are invalid test failures.
- If target-to-platform mapping fails, compilation can pass while comparison is skipped with notes.

## Callers

- CLI: `uv run run_cpp_tests.py -gamever <gamever> [-debug]`
- Header repair: invoke the `fix-cppheaders` SKILL.
