# Bug: symbol-wrapped LLM YAML is silently parsed as an empty result

## Status

Open. Reproduced twice on 2026-07-17 in PR #577 validation run attempts.

Affected run:

- <https://github.com/HLND2T/CS2_VibeSignatures/actions/runs/29579900577>

Attempt 1 failed while processing
`find-SDL_MouseWarpEmulationChanged-decompiles`. Attempt 2 progressed further and
failed while processing `find-SDL_SetRelativeMouseMode-decompiles`.

## Summary

The LLM sometimes returns valid YAML whose first-level keys are requested symbol
names and whose second-level keys are `found_call`, `found_struct_offset`, or other
result sections.

The parser only recognizes `found_*` keys at the document root. A symbol-wrapped
document therefore parses successfully as YAML but is normalized into an entirely
empty result. Because empty result lists do not create validation issues, the
hallucination retry loop accepts the empty parse instead of asking the LLM to
correct its output shape.

The downstream symbol consumer then reports `failed to locate ...` and attempts an
agent-skill fallback. In both observed failures, the fallback skill did not exist,
so binary analysis exited with code `1`.

## Expected YAML Contract

The parser expects result categories at the document root:

```yaml
found_call:
  - insn_va: '0x180079B84'
    insn_disasm: call    sub_1800786A0
    func_name: SDL_PerformWarpMouseInWindow

found_struct_offset:
  - insn_va: '0x180079AEE'
    insn_disasm: cmp     dil, [rsi+0C1h]
    offset: '0xC1'
    size: 1
    struct_name: SDL_Mouse
    member_name: relative_mode
```

## Hallucinated Response Shape

The LLM instead returned symbol names at the document root:

```yaml
SDL_PerformWarpMouseInWindow:
  found_call:
    - insn_va: '0x180079B84'
      insn_disasm: call    sub_1800786A0
      func_name: SDL_PerformWarpMouseInWindow

SDL_Mouse_relative_mode:
  found_struct_offset:
    - insn_va: '0x180079AEE'
      insn_disasm: cmp     dil, [rsi+0C1h]
      offset: '0xC1'
      size: 1
      struct_name: SDL_Mouse
      member_name: relative_mode
```

This is syntactically valid YAML and contains the requested references, but it does
not satisfy the parser's schema.

## Failure Sequence

1. A batched `LLM_DECOMPILE` request asks for multiple symbols.
2. The prompt includes examples with root-level `found_*` sections and also lists
   required result sections per symbol.
3. The LLM hallucinates a symbol-grouped output structure.
4. `parse_llm_decompile_response(...)` successfully loads the YAML mapping.
5. The parser reads only `parsed.get("found_vcall")`,
   `parsed.get("found_call")`, `parsed.get("found_funcptr")`,
   `parsed.get("found_gv")`, and `parsed.get("found_struct_offset")`.
6. None of those keys exist at the document root, so every normalized result list
   becomes empty.
7. `_validate_llm_decompile_result(...)` iterates no entries and reports no
   validation issues.
8. `_call_llm_decompile_with_validation(...)` treats the empty result as valid and
   returns it without consuming the hallucination retry budget.
9. `preprocess_common_skill(...)` cannot locate the requested symbol in the empty
   result and triggers agent fallback.
10. The corresponding `.claude/skills/<skill-name>/SKILL.md` is absent, causing the
    analyzer to abort.

Relevant files:

- `ida_llm_decompile.py:411-459`
- `ida_llm_decompile.py:547-576`
- `ida_llm_decompile.py:727-782`
- `ida_analyze_util.py:8032-8145`
- `ida_preprocessor_scripts/prompt/call_llm_decompile.md`

## Incident Evidence

### Attempt 1

The raw response grouped these symbols:

```yaml
SDL_SetRelativeMouseMode:
  found_call: ...

SDL_Mouse_warp_emulation_active:
  found_struct_offset: ...
```

The debug output immediately afterward showed:

```json
{
  "found_vcall": [],
  "found_call": [],
  "found_funcptr": [],
  "found_gv": [],
  "found_struct_offset": []
}
```

The consumer then reported:

```text
Preprocess: failed to locate SDL_SetRelativeMouseMode
Error: Skill file not found: .claude\skills\find-SDL_MouseWarpEmulationChanged-decompiles\SKILL.md
```

### Attempt 2

The same shape appeared for a later batch containing:

- `SDL_PerformWarpMouseInWindow`
- `SDL_Mouse_relative_mode`
- `SDL_Mouse_SetRelativeMouseMode`

Again, all parsed result lists were empty. The terminal error was:

```text
Preprocess: failed to locate SDL_PerformWarpMouseInWindow
Error: Skill file not found: .claude\skills\find-SDL_SetRelativeMouseMode-decompiles\SKILL.md
```

The different failure location between attempts demonstrates that this is
LLM-output variability exposing a deterministic parser weakness, not a stable
absence of the requested references in the binary.

## Root Cause

The parser conflates two distinct states:

1. The LLM intentionally found no references and returned the supported schema
   with empty `found_*` sections.
2. The LLM returned a non-empty mapping using an unsupported top-level schema.

Both states normalize to `_empty_llm_decompile_result()`. The validation layer then
has no schema-level rule requiring recognized root keys or requiring the expected
symbols to appear before accepting the response.

## Recommended Fix Direction

Use defense in depth:

1. Strengthen the prompt with an explicit root-key contract:

   ```text
   The only permitted top-level YAML keys are found_vcall, found_call,
   found_funcptr, found_gv, and found_struct_offset. Never use a symbol name as a
   top-level key.
   ```

2. Add schema validation after YAML loading. If the parsed mapping is non-empty but
   contains no recognized `found_*` root key, produce a validation issue and invoke
   the existing correction retry.
3. Consider normalizing the observed symbol-wrapped form into the canonical flat
   result as a compatibility fallback, while still validating every flattened
   entry's instruction, category, and symbol identity.
4. Distinguish an explicit canonical empty result from an unrecognized schema.
5. Add a retry correction message that includes the permitted top-level keys and
   the canonical flattened example.

Prompt hardening alone is insufficient because LLM output is nondeterministic. The
parser must fail closed when it receives a non-empty but unsupported structure.

## Acceptance Criteria

- A symbol-wrapped response is never silently converted into an accepted empty
  result.
- Unsupported root keys trigger a hallucination/schema retry with actionable
  correction guidance.
- A corrected canonical response is parsed and consumed successfully.
- An explicitly empty canonical response remains supported when no references
  exist.
- Tests cover single-symbol and batched symbol-wrapped responses.
- Tests cover both retry-based correction and any compatibility-flattening path.
- The PR self-runner completes the affected SDL3 preprocessing path without falling
  through to a missing agent skill solely because of YAML root shape.
