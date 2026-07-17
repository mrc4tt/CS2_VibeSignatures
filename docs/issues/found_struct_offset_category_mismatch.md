# Bug: `found_struct_offset` category mismatches bypass LLM validation retries

## Status

Resolved on 2026-07-17. The root cause was observed in PR validation run
<https://github.com/HLND2T/CS2_VibeSignatures/actions/runs/29576361945/job/87871597433>.

The fix now propagates authoritative struct-member result-section expectations,
derives canonical symbol identities for `found_struct_offset`, and gives the LLM
both initial and retry-time category guidance. Invalid category responses remain
subject to the existing retry budget and fail-closed behavior.

Local verification completed with:

- `python -m unittest discover -s tests -b`: 899 tests passed.
- `python format_repo_files.py --check`: all tracked Python and YAML files passed.

The IDA/binary-backed PR self-runner remains the authoritative external integration
check and should confirm the original SDL regeneration path on the next PR run.

## Summary

`ida_llm_decompile.py` already validates instruction addresses, disassembly text,
result sections, and `found_vcall` displacements. Validation failures are formatted
through `_format_llm_validation_issue(...)` and returned to the LLM for another
attempt.

However, the caller currently declares an expected result section only for symbols
whose desired output includes `vfunc_offset`. Struct-member targets are not declared
as requiring `found_struct_offset`. As a result, a struct function-pointer member can
be returned under `found_vcall`, pass all existing validation, and reach the
section-specific consumer that only searches `found_struct_offset`.

The retry engine supports `found_struct_offset` instruction validation. The missing
capability is category expectation propagation for struct-member targets, plus
complete symbol identity extraction for entries in `found_struct_offset`.

## Incident

PR #577 changed `agent_runner.py`. PR validation classifies that file as a core
analysis change, restores the deterministic `14168b` snapshot, and invalidates all
affected generated YAML before re-running the analyzer.

While processing `find-SDL_PerformWarpMouseInWindow-decompiles`, the LLM returned:

```yaml
found_vcall:
  - insn_va: '0x18007872A'
    insn_disasm: mov     rdx, [rax+30h]
    vfunc_offset: '0x30'
    func_name: SDL_Mouse_WarpMouse
```

The address, instruction, and displacement were real, but the category was wrong.
`SDL_Mouse_WarpMouse` is a function-pointer field in `SDL_Mouse`, not a C++ virtual
function slot. The expected representation is:

```yaml
found_struct_offset:
  - insn_va: '0x18007872A'
    insn_disasm: mov     rdx, [rax+30h]
    offset: '0x30'
    size: 8
    struct_name: SDL_Mouse
    member_name: WarpMouse
```

The accepted `14168b` snapshot confirms this metadata:

```yaml
SDL3/SDL_Mouse_WarpMouse.windows.yaml:
  member_name: WarpMouse
  offset: '0x30'
  offset_sig: 48 8B 50 ?? 48 85 D2 74 ?? 84 C9
  offset_sig_disp: 0
  size: 8
  struct_name: SDL_Mouse
```

Relevant files:

- `ida_preprocessor_scripts/find-SDL_PerformWarpMouseInWindow-decompiles.py:8-15`
- `ida_preprocessor_scripts/find-SDL_PerformWarpMouseInWindow-decompiles.py:108-118`
- `gamesymbols/14168b.yaml:24-30`

## Failure Sequence

1. `preprocess_common_skill(...)` groups the six `SDL_Mouse` targets into one
   `LLM_DECOMPILE` request.
2. `_build_expected_llm_result_sections(...)` receives the requested symbol names
   and desired field metadata.
3. The helper only adds an expectation when a symbol requests `vfunc_offset`:

   ```python
   if "vfunc_offset" in desired_fields:
       expected_sections[symbol_name] = "found_vcall"
   ```

4. `SDL_Mouse_WarpMouse` requests `struct_name`, `member_name`, `offset`, `size`,
   `offset_sig`, and `offset_sig_disp`. It therefore receives no expected section.
5. `_validate_llm_result_sections(...)` looks up the expected section for the
   returned `func_name`. An empty expectation is treated as unconstrained:

   ```python
   if not expected_sections or section_name in expected_sections:
       continue
   ```

6. The remaining validators also accept the entry:
   - `insn_va` identifies the reported instruction.
   - `insn_disasm` matches the target disassembly.
   - the instruction contains the reported `0x30` displacement.
7. No validation issue is produced, so `_format_llm_validation_issue(...)` is not
   called and the hallucination/category retry loop returns the first response.
8. The struct-member consumer later iterates only
   `llm_result["found_struct_offset"]`. It cannot see the misplaced
   `found_vcall` entry and reports `failed to locate SDL_Mouse_WarpMouse`.
9. The preprocessor attempts agent fallback, but
   `.claude/skills/find-SDL_PerformWarpMouseInWindow-decompiles/SKILL.md` does not
   exist. Binary analysis exits with code `1`.

Relevant code:

- `ida_analyze_util.py:2421-2428`
- `ida_analyze_util.py:8035-8059`
- `ida_analyze_util.py:8550-8615`
- `ida_llm_decompile.py:550-568`
- `ida_llm_decompile.py:590-616`
- `ida_llm_decompile.py:651-687`
- `ida_llm_decompile.py:700-745`

## Root Cause

### Primary cause: struct category expectations are never declared

The retry mechanism can only reject a category mismatch when
`expected_result_sections` contains an expectation for the returned symbol.
`_build_expected_llm_result_sections(...)` currently describes `found_vcall`
targets only. It does not use the caller's explicit `struct_member_names` registry
to declare `found_struct_offset` targets.

Consequently, the validator cannot distinguish these two interpretations of the
same memory load:

```text
C++ virtual dispatch slot:      found_vcall
function-pointer struct field:  found_struct_offset
```

### Secondary cause: `found_struct_offset` has no canonical symbol-key extractor

`_LLM_RESULT_SYMBOL_KEYS` maps single-field identities for these sections:

```text
found_vcall   -> func_name
found_call    -> func_name
found_funcptr -> funcptr_name
found_gv      -> gv_name
```

`found_struct_offset` is absent because its identity is split across
`struct_name` and `member_name`. This does not prevent detection of the exact
incident once `SDL_Mouse_WarpMouse -> found_struct_offset` is declared: the
incorrect entry was under `found_vcall`, so its `func_name` is available.

It does prevent symmetric and general category validation when an entry is returned
under `found_struct_offset`. A complete fix must derive the canonical symbol name
using the same convention as the analyzer:

```python
f"{struct_name}_{member_name}".replace(".", "_")
```

### Contributing cause: the initial prompt does not state per-symbol categories

The common prompt includes examples for both virtual-function pointer fetching and
struct function-pointer fields, but the requested symbol list does not state which
section each symbol requires. For a load such as `mov rdx, [rax+30h]`, both examples
appear superficially plausible to the model.

Post-response validation must remain authoritative, but proactively including the
expected section mapping will reduce avoidable retries and model-dependent behavior.

### Failure amplification: no agent fallback exists for this preprocessor

The absent `SKILL.md` is not the classification root cause. It turns a recoverable
preprocessor failure into an immediate job failure after LLM retries or validation
have already failed. The primary correction should make the deterministic
validation/retry path handle category mistakes. Adding a fallback skill is a
separate resilience decision and is not required for the primary fix.

## Existing Capability Versus Missing Capability

Already implemented:

- `found_struct_offset` participates in instruction address/disassembly validation.
- `_format_llm_validation_issue(...)` can format generic
  `result_section_mismatch` issues for any expected section.
- The conversation retry loop can send the rejected response and correction prompt
  back to the model.
- Retry exhaustion fails closed by returning an empty LLM result.

Missing:

- Declaring struct-member targets as requiring `found_struct_offset`.
- Deriving a canonical symbol name from `struct_name` and `member_name` during
  section validation.
- Initial prompt guidance that exposes per-symbol result-section requirements.
- Regression coverage for a struct member returned under `found_vcall`.

## Goals

- Reject a struct-member target returned under `found_vcall`, `found_call`,
  `found_funcptr`, or `found_gv`.
- Retry the LLM with an explicit message that the symbol requires
  `found_struct_offset`.
- Preserve existing instruction and displacement validation.
- Support mixed batched requests containing functions, virtual functions, globals,
  and struct members.
- Keep retry-count, backoff, cache-key, and fail-closed semantics unchanged.
- Preserve the accepted YAML schema and output for existing preprocessors.

## Non-goals

- Do not automatically reinterpret or move entries between sections without an LLM
  retry. The corrected response should remain auditable LLM output.
- Do not add missing-symbol retries as part of this change. A symbol may genuinely
  be absent from a target function, and the existing caller-level failure path owns
  that decision.
- Do not add the missing SDL agent skill as part of the category-validation fix.
- Do not change how struct offset signatures are generated after a valid entry is
  accepted.
- Do not broaden regular-function policy unless required by tests. A regular
  function may legitimately be discovered through `found_call` or
  `found_funcptr`.

## Proposed Fix

### 1. Build expectations from explicit target categories

Extend `_build_expected_llm_result_sections(...)` so it receives the explicit
target registries available inside `preprocess_common_skill(...)`, rather than
inferring every category from output fields.

Minimum required behavior:

```python
def _build_expected_llm_result_sections(
    symbol_names,
    desired_fields_map,
    *,
    struct_member_names=(),
):
    struct_member_names = set(struct_member_names)
    expected_sections = {}
    for symbol_name in symbol_names:
        if symbol_name in struct_member_names:
            expected_sections[symbol_name] = "found_struct_offset"
            continue

        desired_spec = desired_fields_map.get(symbol_name) or {}
        desired_fields = set(desired_spec.get("desired_output_fields", []))
        if "vfunc_offset" in desired_fields:
            expected_sections[symbol_name] = "found_vcall"
    return expected_sections
```

The call inside `_call_llm_decompile_for_request(...)` should pass the current,
post-fast-path `struct_member_names` collection. Explicit category membership is
preferred over detecting `struct_name`/`member_name` field combinations because it
uses the analyzer's authoritative routing data and avoids accidental coupling to
output schema details.

The normalized expectation format already supports either a string or a collection
of allowed sections. Preserve this so future targets can allow more than one valid
discovery representation.

### 2. Add section-aware symbol identity extraction

Replace direct `_LLM_RESULT_SYMBOL_KEYS` lookup in
`_validate_llm_result_sections(...)` with a helper:

```python
def _get_llm_result_symbol_name(section_name, entry):
    if section_name == "found_struct_offset":
        struct_name = str(entry.get("struct_name", "")).strip()
        member_name = str(entry.get("member_name", "")).strip()
        if not struct_name or not member_name:
            return ""
        return f"{struct_name}_{member_name}".replace(".", "_")

    symbol_key = _LLM_RESULT_SYMBOL_KEYS.get(section_name)
    return str(entry.get(symbol_key, "") if symbol_key else "").strip()
```

Use this helper for every instruction result entry. This makes section mismatch
validation symmetric and keeps struct naming aligned with
`_build_struct_member_symbol_name(...)` in `ida_analyze_util.py` without introducing
a circular import.

Malformed struct entries with missing `struct_name` or `member_name` should continue
through existing schema/consumer handling unless a dedicated validation issue is
introduced separately. The category fix should not silently invent an identity.

### 3. Include category requirements in the initial prompt

After normalizing `expected_result_sections`, append a compact generated block to
the initial user prompt when expectations are present:

```text
Required result sections:
- SDL_Mouse_WarpMouse: found_struct_offset
- CEntitySystem_OnRemoveEntity: found_vcall

Function-pointer fields stored inside a regular struct are found_struct_offset,
not found_vcall. Use found_vcall only for virtual dispatch/vtable slots.
```

This guidance should be generated centrally in `ida_llm_decompile.py`; individual
prompt templates should not need modification. The validator remains the source of
truth if the model ignores the guidance.

Prompt caching behavior must remain stable within one retry conversation. The same
generated requirements should be present in the initial message reused across all
attempts.

### 4. Add struct-specific retry guidance

`_format_llm_result_section_issue(...)` already produces the essential correction:

```text
symbol 'SDL_Mouse_WarpMouse' was returned in found_vcall, but it requires
found_struct_offset
```

Enhance `_build_llm_instruction_correction_prompt(...)` when any issue expects
`found_struct_offset`:

```text
For found_struct_offset, report the exact instruction that accesses the member and
provide offset, size, struct_name, and member_name. A function pointer loaded from a
regular struct field is still found_struct_offset, not found_vcall.
```

Keep the existing `found_vcall` displacement guidance unchanged. A mixed invalid
response may need both guidance blocks.

### 5. Preserve retry and failure semantics

Do not create a separate retry loop. Continue using
`_call_llm_decompile_with_validation(...)` so transport failures and validation
failures share the configured total-attempt budget exactly as they do today.

Expected behavior for the incident:

1. First response returns `SDL_Mouse_WarpMouse` under `found_vcall`.
2. `_validate_llm_result_sections(...)` emits `result_section_mismatch`.
3. `_format_llm_validation_issue(...)` states that the symbol requires
   `found_struct_offset`.
4. The next conversation attempt includes the original response plus the correction.
5. A corrected `found_struct_offset` entry is validated and consumed normally.
6. If all attempts remain invalid, the existing empty-result and preprocessor
   failure path is retained.

## Test Plan

Add focused tests to `tests/test_ida_analyze_util.py`.

### Expectation construction

- A symbol listed in `struct_member_names` maps to `found_struct_offset`.
- A symbol requiring `vfunc_offset` continues to map to `found_vcall`.
- A mixed request produces expectations for both categories.
- A regular function without a strict category remains unconstrained unless current
  policy already requires otherwise.

### LLM validation retry

- First response returns a requested struct member under `found_vcall`; second
  response returns it under `found_struct_offset`; assert two LLM calls and accept
  the corrected result.
- Assert that the correction prompt includes:
  - the original `found_vcall[index]` location;
  - `requires found_struct_offset`;
  - the function-pointer struct-field guidance.
- A correct `found_struct_offset` response succeeds on the first call.
- Repeated category mismatches exhaust the configured total attempts and return the
  empty LLM result.

### Symbol identity

- `found_struct_offset` with `SDL_Mouse` and `WarpMouse` resolves to
  `SDL_Mouse_WarpMouse`.
- Names containing dots use the same dot-to-underscore canonicalization as
  `_build_struct_member_symbol_name(...)`.
- Empty `struct_name` or `member_name` does not produce a false symbol match.

### Existing validation regression

- Existing `found_vcall` versus `found_call`/`found_funcptr` retry tests continue to
  pass.
- `found_struct_offset` instruction address/disassembly mismatch still triggers a
  retry.
- Existing `found_vcall` displacement validation remains unchanged.
- Mixed-section responses report all mismatches in one correction prompt.

### Preprocessor integration

Add a `preprocess_common_skill(...)` test representing the SDL incident:

- Requested target: `SDL_Mouse_WarpMouse` as a struct member.
- First mocked LLM result: valid instruction under `found_vcall`.
- Corrected result: `found_struct_offset` with offset `0x30` and size `8`.
- Assert that the generated YAML contains `struct_name: SDL_Mouse`,
  `member_name: WarpMouse`, and `offset: '0x30'`.
- Assert that the preprocessor succeeds without reaching agent fallback.

## Implementation Order

1. Add failing unit tests for struct expectation construction and the exact
   `found_vcall -> found_struct_offset` retry.
2. Add section-aware symbol identity extraction in `ida_llm_decompile.py`.
3. Extend expectation construction and pass explicit struct-member categories from
   `preprocess_common_skill(...)`.
4. Add initial-prompt category requirements and struct-specific retry guidance.
5. Add the SDL-shaped preprocessor integration test.
6. Run targeted LLM/preprocessor tests, then the complete Python test suite and
   repository formatting gate.
7. Re-run PR validation and confirm the analyzer either regenerates the accepted
   `SDL_Mouse_WarpMouse` YAML or reports a genuine post-retry failure.

## Acceptance Criteria

- The incident response is rejected before section-specific result consumption.
- Debug output contains a `result_section_mismatch` for
  `SDL_Mouse_WarpMouse` requiring `found_struct_offset`.
- A corrected response is requested automatically within the existing retry budget.
- Correct `found_struct_offset` output generates the accepted `0x30`, size `8`
  `SDL_Mouse.WarpMouse` metadata.
- Correct struct entries remain single-attempt operations.
- Existing `found_vcall`, `found_call`, `found_funcptr`, `found_gv`, and instruction
  validation tests do not regress.
- Batched requests preserve per-symbol category expectations.
- Retry exhaustion remains fail-closed and does not accept or auto-convert an invalid
  section.
- The full Python unit test suite, formatting checks, and PR self-runner validation
  pass.

## Risks and Mitigations

### Canonical-name mismatch

Risk: `struct_name + member_name` normalization differs between validation and the
consumer, causing valid entries to be rejected.

Mitigation: mirror `_build_struct_member_symbol_name(...)` exactly and cover dotted
names and empty fields with tests.

### Over-constraining valid discovery forms

Risk: a target legitimately supports more than one result section.

Mitigation: retain the existing set-valued expectation normalization and allow
callers to declare multiple sections. Only struct-member targets with authoritative
pipeline category metadata should be restricted to `found_struct_offset`.

### Increased LLM calls

Risk: stricter validation consumes more retry attempts.

Mitigation: add the expected category requirements to the initial prompt so correct
classification is more likely on the first attempt. Do not change retry counts or
backoff policy.

### Hidden dependency on missing fallback skills

Risk: retry exhaustion still fails when a preprocessor has no agent skill.

Mitigation: keep that behavior explicit. The classification fix prevents known
recoverable mistakes from reaching fallback, while missing fallback coverage can be
tracked independently where resilience requires it.

## Verification Evidence for the Original Failure

The failed run demonstrates all conditions required by this diagnosis:

- Formatting passed.
- Python unit tests passed.
- The LLM returned `SDL_Mouse_WarpMouse` once, under `found_vcall`.
- No `llm_decompile instruction mismatches` or hallucination retry was logged for
  that response.
- The struct consumer generated the other five struct-member YAML files but logged
  `failed to locate SDL_Mouse_WarpMouse`.
- Agent fallback then failed because the corresponding `SKILL.md` was absent.

This distinguishes the bug from MCP connectivity, malformed disassembly, an
incorrect offset, and retry transport failure. The missing link is category
expectation and validation for struct-member targets.
