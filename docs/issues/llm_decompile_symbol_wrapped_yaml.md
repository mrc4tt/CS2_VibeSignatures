# Bug: symbol-wrapped LLM YAML is silently parsed as an empty result

## Status

Resolved on 2026-07-17 by adding schema-aware parsing, strict symbol-wrapped compatibility flattening, requested-symbol validation, schema-specific correction retries, and focused regression tests.

Follow-up audit: `ida_vcall_finder.py` has a similar but separate parser weakness tracked in [`ida_vcall_finder_unknown_yaml_schema.md`](ida_vcall_finder_unknown_yaml_schema.md).

Affected run:

- <https://github.com/HLND2T/CS2_VibeSignatures/actions/runs/29579900577>
- <https://github.com/HLND2T/CS2_VibeSignatures/actions/runs/29585099305/job/87900015629>

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

Use defense in depth. Keep the category-first `found_*` document as the canonical
contract, accept the observed symbol-wrapped document only through a strict
compatibility path, and route every ambiguous or unsupported document through the
existing hallucination-correction retry.

### 1. Preserve parse status instead of returning only normalized entries

Introduce an internal schema-aware parse result, for example:

```text
result: normalized canonical found_* mapping
schema_kind: canonical | symbol_wrapped | explicit_empty | invalid
issues: schema/parse issues to feed into correction retry
```

`parse_llm_decompile_response(...)` is re-exported and directly exercised by tests,
so its existing dictionary return value should remain compatible. Add an internal
helper such as `_parse_llm_decompile_response_with_issues(...)`, have the public
function return only its normalized `result`, and make
`_call_llm_decompile_with_validation(...)` consume the full parse outcome.

This prevents these states from collapsing into the same
`_empty_llm_decompile_result()` value before validation can inspect them:

- a canonical response containing valid entries;
- an explicit canonical no-result response;
- a supported symbol-wrapped compatibility response;
- invalid YAML;
- a YAML scalar or sequence instead of a mapping;
- a non-empty mapping with unknown root keys;
- a mapping whose entries have invalid container or field shapes.

### 2. Classify and validate the raw YAML mapping before normalization

Define the recognized result-section set once and use it for prompt generation,
schema validation, flattening, and correction guidance:

```text
found_vcall
found_call
found_funcptr
found_gv
found_struct_offset
```

Classify a parsed mapping using the following rules.

#### Canonical category-first response

A canonical response must satisfy all of these conditions:

- every root key is one of the recognized `found_*` keys;
- every section value is a list;
- every list element is a mapping with the required fields for that section;
- unknown root keys are rejected even when recognized keys are also present;
- symbol-root and category-root keys may not be mixed in one document.

The parser may continue to accept a subset of `found_*` sections when at least one
valid result entry is present. A no-result response should be considered explicit
only when it uses the complete canonical empty form:

```yaml
found_vcall: []
found_call: []
found_funcptr: []
found_gv: []
found_struct_offset: []
```

Blank text, YAML `null`, and `{}` should not be accepted as successful no-result
responses after the prompt has been updated. They do not prove that the model
followed or even processed the output contract and should therefore trigger a
schema correction retry.

#### Strict symbol-wrapped compatibility response

Treat the observed symbol-wrapped shape as a supported compatibility input only
when every structural and identity check succeeds:

- every root key is a member of the current request's complete
  `symbol_name_list`;
- every root value is a mapping;
- every nested key is a recognized `found_*` section;
- every nested section value is a list of mappings with the required fields;
- the document contains at least one valid entry;
- the wrapper symbol matches the symbol identity encoded in every nested entry;
- no canonical `found_*` key appears at the root alongside symbol wrappers.

For identity checks, reuse the same canonical symbol extraction used by result
validation:

- `func_name` for `found_vcall` and `found_call`;
- `funcptr_name` for `found_funcptr`;
- `gv_name` for `found_gv`;
- normalized `struct_name + "_" + member_name` for
  `found_struct_offset`.

If all checks pass, flatten the nested lists into the existing canonical result and
then run the normal instruction, category, virtual-offset, and requested-symbol
validation. This compatibility path avoids spending a shared retry attempt on a
response that contains valid, recoverable evidence while keeping the prompt and
downstream contract canonical.

Do not recursively flatten arbitrary mappings. An unknown wrapper, mixed schema,
wrapper/entry identity mismatch, invalid nested type, or all-empty symbol-wrapped
document must produce a schema issue and request a corrected canonical response.

### 3. Validate before performing lossy normalization

The current normalizers discard malformed entries. If schema checks run only after
normalization, a response containing only malformed entries can still become an
accepted empty result. Validate the raw section and entry shapes first, record an
issue for invalid entries, and normalize strings and struct-offset duplicates only
after the raw document is known to be structurally valid.

The compatibility flattening path must follow the same order:

1. validate wrapper and nested structure;
2. validate wrapper-to-entry symbol identity;
3. flatten into canonical `found_*` lists;
4. normalize fields;
5. run semantic validation against target disassembly and expected categories.

### 4. Validate against the complete requested-symbol set

Retain a normalized set derived from `symbol_name_list` and pass it into parsing and
validation separately from `expected_result_sections`.

`expected_result_sections` currently constrains only targets that require a
specific category, such as struct members and virtual functions. It does not cover
ordinary functions that may legitimately appear in `found_call` or
`found_funcptr`. It is therefore insufficient for validating wrapper names or
rejecting unrelated symbols.

Add requested-symbol validation for every canonical or flattened entry. An entry
whose extracted symbol identity is empty or is not in the requested-symbol set
must produce a validation issue rather than being ignored.

### 5. Feed parse and schema issues into the existing correction retry

Combine parse/schema issues with the current semantic validation issues before
deciding whether a response is acceptable:

```text
validation_issues =
    parse_outcome.issues
    + instruction_pair_issues
    + result_section_issues
    + requested_symbol_issues
    + vcall_offset_issues
```

Add explicit issue types such as:

- `yaml_parse_error`;
- `yaml_root_type_mismatch`;
- `yaml_schema_mismatch`;
- `yaml_section_type_mismatch`;
- `wrapped_symbol_mismatch`;
- `unexpected_result_symbol`.

Any issue must consume the existing shared retry budget and append the previous raw
assistant response plus an actionable correction request to the conversation.
After retry exhaustion, preserve the current fail-closed behavior and return the
empty normalized result, but emit debug output that distinguishes schema failure
from a valid explicit no-result response.

### 6. Make correction guidance schema-specific

Extend `_build_llm_instruction_correction_prompt(...)` (or rename it to reflect its
broader responsibility) so schema issues produce guidance that includes:

- the complete list of permitted root keys;
- a statement that symbol names must never be root keys;
- a statement that batched symbols must be appended to category lists;
- the complete canonical empty response;
- a compact canonical multi-symbol example;
- the concrete unknown keys or wrapper/identity mismatch found in the previous
  response.

The retry must still request the complete YAML document, not a patch or a partial
replacement.

### 7. Strengthen the initial prompt contract

Update `ida_preprocessor_scripts/prompt/call_llm_decompile.md` with wording similar
to:

```text
Return exactly one YAML mapping. The only permitted top-level keys are
found_vcall, found_call, found_funcptr, found_gv, and found_struct_offset.
Never use a requested symbol name as a top-level key. For batched requests,
place every result under its result-category list. If no references are found,
return all five top-level keys with empty lists. Do not return blank YAML, null,
or an empty mapping.
```

Keep the canonical category-first example immediately after this contract. Prompt
hardening reduces malformed responses but is not a correctness boundary; parser
classification and validation remain authoritative.

### 8. Preserve observability

When debug logging is enabled, print the detected `schema_kind`, root keys, whether
compatibility flattening was used, and the resulting schema issues. Do not log the
symbol-wrapped response as a normal canonical parse without indicating that the
compatibility path was taken.

This makes future schema drift distinguishable from a genuine absence of binary
references and from instruction/category hallucinations.

### 9. Test plan

Add focused unit tests covering at least:

- canonical single-symbol and batched responses remain unchanged;
- the complete canonical empty response is accepted without retry;
- blank text, `null`, `{}`, malformed YAML, and non-mapping YAML trigger retry;
- a single-symbol wrapped response is flattened and consumed successfully;
- a batched wrapped response spanning multiple result categories is flattened and
  consumed successfully;
- wrapper names not present in `symbol_name_list` are rejected;
- wrapper/entry symbol mismatches trigger correction retry;
- mixed canonical and symbol-wrapped root keys trigger correction retry;
- unknown canonical or nested keys trigger correction retry;
- invalid section container types and malformed entries are not silently dropped;
- unrelated entry symbols trigger correction retry even when they have valid
  instructions;
- a corrected canonical response is accepted on the next attempt;
- repeated schema failures exhaust the retry budget and fail closed;
- correction messages contain the root-key contract and canonical examples;
- the affected SDL3 batch path consumes a valid wrapped or corrected response
  without falling through solely because of YAML root shape.

After the focused unit tests pass, run the repository's normal Python validation
and the PR self-runner path that reproduced the incident.

### 10. Scope and follow-up

Do not treat adding the missing fallback skills or making their absence non-fatal as
the primary fix. That would only mask the parser defect and leave other batched
LLM_DECOMPILE requests vulnerable to the same failure.

`ida_vcall_finder.py` contains a similar parser pattern that turns unknown mappings
into an empty `found_vcall` result. Audit it after this fix and either reuse the
schema-aware parsing approach or create a separate issue if changing it would
expand the current patch beyond the affected `llm_decompile` flow.

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
