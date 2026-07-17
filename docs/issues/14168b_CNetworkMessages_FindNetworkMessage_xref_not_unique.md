# Bug: valid `found_call` is rejected and creates a false FindNetworkMessage xref ambiguity

## Status

Resolved on 2026-07-17 by replacing the positional `LLM_DECOMPILE` contract with strict dict specs, making result sections explicit, and decoupling reference discovery from final artifact fields.

The failure was reproduced in PR #577 self-runner validation after the SDL3 preprocessing path completed successfully.

Affected run:

- <https://github.com/HLND2T/CS2_VibeSignatures/actions/runs/29588922944/job/87912814817>

Implemented resolution:

- All repository `LLM_DECOMPILE` declarations now provide `symbol_name`, `prompt_path`, `reference_yaml_paths`, and `expected_result_sections`.
- Tuple, schema-less, malformed, unknown-field, duplicate-symbol, and target-kind-incompatible specs fail before an LLM request is sent.
- Batched requests build their per-symbol expected-section mapping directly from the normalized specs.
- Function result consumption follows the declared sections instead of inferring a path from `vfunc_offset`.
- Directly called vfunc implementations can resolve `func_va` first and then derive their vtable slot through `FUNC_VTABLE_RELATIONS`.
- `CNetworkMessages_FindNetworkMessagePartial` and `CCSPlayerController_Respawn` explicitly use `found_call` despite producing vfunc artifacts.
- The incident regression resolves `0x1800D6BA0` and derives index `14`, offset `0x70`, while ignoring the unrelated `[rdx+10h]` call.

## Summary

The two-candidate failure in `find-CNetworkMessages_FindNetworkMessage` is a downstream symptom. The primary failure occurs earlier while locating `CNetworkMessages_FindNetworkMessagePartial` through the LLM decompile fallback.

`CNetChan_ParseNetMessageShowFilter` contains a direct call to the target function:

```text
call    sub_1800D6BA0
```

The LLM correctly returned that instruction under `found_call`. The analyzer incorrectly inferred that every symbol whose generated YAML needs `vfunc_offset` must be reported under `found_vcall`, and rejected the correct result:

```json
{
  "issue_type": "result_section_mismatch",
  "section_name": "found_call",
  "entry_index": 0,
  "symbol_name": "CNetworkMessages_FindNetworkMessagePartial",
  "reported_disasm": "call sub_1800D6BA0",
  "expected_sections": [
    "found_vcall"
  ]
}
```

The correction retry then caused the LLM to relabel a different, unrelated virtual call as the requested symbol:

```yaml
found_vcall:
  - insn_va: '0x1800BAB8A'
    insn_disasm: call    qword ptr [rdx+10h]
    vfunc_offset: '0x10'
    func_name: CNetworkMessages_FindNetworkMessagePartial
```

That `+0x10` call is made on the network-message object returned by `CNetworkMessages_FindNetworkMessagePartial`. It is not a dispatch through the `CNetworkMessages` vtable and therefore does not identify the target function's vtable slot.

## Correct Resolution

The reference category and the generated symbol metadata are separate concerns:

1. Consume the direct `found_call` and resolve its callee to `0x1800D6BA0`.
2. Use the declared relation `("CNetworkMessages_FindNetworkMessagePartial", "CNetworkMessages")` to reverse-lookup that function address in `CNetworkMessages_vtable`.
3. The address is at vtable index `14`, so the correct offset is `14 * 8 = 0x70`.

The local `14168b` artifacts confirm this mapping:

```yaml
# CNetworkMessages_vtable.windows.yaml
vtable_entries:
  14: '0x1800d6ba0'
```

```yaml
# CNetworkMessages_FindNetworkMessagePartial.windows.yaml
func_va: '0x1800d6ba0'
vtable_name: CNetworkMessages
vfunc_offset: '0x70'
vfunc_index: 14
```

For comparison, the actual `CNetworkMessages_FindNetworkMessage` function is `0x1800D69E0`, at vtable index `13` and offset `0x68`.

## Failure Chain

1. `GENERATE_YAML_DESIRED_FIELDS` requests `vfunc_offset` because the final function YAML must contain vtable metadata.
2. `_build_expected_llm_result_sections(...)` treats that output field as proof that the reference instruction must be a `found_vcall`.
3. `_validate_llm_result_sections(...)` rejects the correct `found_call` to `0x1800D6BA0` and asks the LLM to return `found_vcall` instead.
4. The retry selects `call qword ptr [rdx+10h]`, so the analyzer treats vtable offset `0x10` as belonging to `CNetworkMessages_FindNetworkMessagePartial`.
5. Offset `0x10` resolves to index `2` of the `CNetworkMessages` vtable rather than the real function at index `14`.
6. The later `find-CNetworkMessages_FindNetworkMessage` preprocessor excludes the wrongly generated Partial address, not `0x1800D6BA0`.
7. Both `0x1800D69E0` and `0x1800D6BA0` therefore survive the xref intersection, producing the apparent non-unique result.

With the correct Partial YAML, excluding `0x1800D6BA0` leaves exactly one candidate: `0x1800D69E0`.

## Code Evidence

The incorrect behavior is produced by two coupled assumptions in `ida_analyze_util.py`:

```python
def _build_expected_llm_result_sections(symbol_names, desired_fields_map, *, struct_member_names=()):
    ...
    if "vfunc_offset" in desired_fields:
        expected_sections[symbol_name] = "found_vcall"
```

```python
expects_vfunc = "vfunc_offset" in desired_fields_set
can_use_direct_func_fallback = not expects_vfunc
```

The first conflates the desired output schema with the kind of reference present in the decompiled caller. The second prevents the existing `found_call -> direct_func_va -> vtable reverse lookup` path from running for functions that need `vfunc_offset` in their final YAML.

The required reverse-lookup capability already exists later in `preprocess_common_skill(...)`: when `func_va` is known and `vfunc_offset`/`vfunc_index` are missing, it scans the related vtable entries and derives the slot.

Relevant files:

- `ida_analyze_util.py:2421-2432`
- `ida_analyze_util.py:8081-8085`
- `ida_analyze_util.py:8136-8169`
- `ida_analyze_util.py:8310-8392`
- `ida_llm_decompile.py:782-799`
- `ida_llm_decompile.py:959-973`
- `ida_preprocessor_scripts/find-CNetworkMessages_FindNetworkMessagePartial.py:19-39`
- `ida_preprocessor_scripts/find-CNetworkMessages_FindNetworkMessage.py:10-24`

## Commit Provenance

The incident was observed on commit `ae000cb631e8bce56ac852ca5586dc672a6c737d`, whose schema-aware retry pipeline reported the diagnostic shown above. Git history shows that the incorrect category inference itself predates that commit:

- `a580787ea5f451e39c49489a864bb188e25bf759` changed direct-call eligibility to `can_use_direct_func_fallback = not expects_vfunc`.
- `4d74a246afeb94e1dc87092b46873de4b9ac0bb3` introduced `_build_expected_llm_result_sections(...)` and the rule that a desired `vfunc_offset` requires `found_vcall`.
- `ae000cb631e8bce56ac852ca5586dc672a6c737d` retained that semantic rule while refactoring and strengthening YAML/schema validation and correction retries.

Therefore `ae000cb...` is the commit on which the bad judgment was observed, but it is not the original source of the `vfunc_offset -> found_vcall` inference.

## Approved Implementation Plan

`LLM_DECOMPILE` must explicitly declare the result section that the LLM is expected to use. The analyzer must no longer infer that contract from `GENERATE_YAML_DESIRED_FIELDS`.

The existing positional tuple contract:

```python
LLM_DECOMPILE = [
    (
        "CNetworkMessages_FindNetworkMessagePartial",
        "prompt/call_llm_decompile.md",
        "references/networksystem/CNetChan_ParseNetMessageShowFilter.{platform}.yaml",
    ),
]
```

will be replaced by a dict contract similar to `FUNC_XREFS`:

```python
LLM_DECOMPILE = [
    {
        "symbol_name": "CNetworkMessages_FindNetworkMessagePartial",
        "prompt_path": "prompt/call_llm_decompile.md",
        "reference_yaml_paths": [
            "references/networksystem/CNetChan_ParseNetMessageShowFilter.{platform}.yaml",
        ],
        "expected_result_sections": ["found_call"],
    },
]
```

`expected_result_sections` is deliberately plural. Most targets will declare one section, while targets that genuinely permit multiple reference forms can declare a non-empty subset of the canonical sections:

- `found_call`
- `found_vcall`
- `found_funcptr`
- `found_gv`
- `found_struct_offset`

The implementation must satisfy the following rules:

1. `_build_llm_decompile_specs_map(...)` accepts dict specs only and fails closed on missing, unknown, malformed, or conflicting fields.
2. Every spec explicitly provides `symbol_name`, `prompt_path`, non-empty `reference_yaml_paths`, and non-empty `expected_result_sections`.
3. Batched requests preserve the expected sections for each individual symbol, including batches that mix function, global-variable, and struct-member results.
4. `_build_expected_llm_result_sections(...)` must no longer derive result categories from desired output fields and should be removed or replaced by spec-backed lookup.
5. `GENERATE_YAML_DESIRED_FIELDS` continues to define only the final artifact fields. It must not decide whether an observed reference is a direct call, virtual call, function pointer, global-variable access, or struct-member access.
6. Result consumption follows the explicitly declared and validated section. In particular, a vfunc artifact may be discovered through `found_call`; after resolving its `func_va`, `FUNC_VTABLE_RELATIONS` and the existing vtable reverse lookup derive `vtable_name`, `vfunc_index`, and `vfunc_offset`.
7. Direct-call/function-pointer consumption must not be disabled merely because the final artifact requests `vfunc_offset`. A configuration that cannot produce required fields such as `vfunc_sig` must instead fail during spec/output compatibility validation.
8. Genuine `found_vcall` results retain exact instruction/disassembly and displacement validation.
9. All repository `LLM_DECOMPILE` declarations are migrated atomically; the old tuple form is not retained as a silent compatibility path.
10. Focused tests cover spec validation, mixed-section batching, direct-call discovery plus vtable enrichment, and the exact `[rdx+10h]` regression before the complete Python suite is run.

The missing `.claude/skills/find-CNetworkMessages_FindNetworkMessage/SKILL.md` fallback is a separate resilience gap. Adding it would not correct the poisoned `CNetworkMessages_FindNetworkMessagePartial` metadata and is not the primary fix.

## Acceptance Criteria

- The initial `found_call` containing `call sub_1800D6BA0` is accepted without a correction retry.
- `LLM_DECOMPILE` explicitly declares `expected_result_sections: ["found_call"]` for `CNetworkMessages_FindNetworkMessagePartial`.
- Tuple-based or schema-less `LLM_DECOMPILE` entries fail before an LLM request is sent.
- `CNetworkMessages_FindNetworkMessagePartial` resolves to `func_va 0x1800D6BA0`.
- Its vtable metadata is derived by reverse lookup as index `14`, offset `0x70`.
- `call qword ptr [rdx+10h]` is not attributed to `CNetworkMessages_FindNetworkMessagePartial`.
- The downstream exclusion removes `0x1800D6BA0`, leaving `0x1800D69E0` as the unique `CNetworkMessages_FindNetworkMessage` candidate.
- Focused tests cover direct-call discovery of a vfunc target, vtable-slot enrichment, result-section validation, and the downstream two-candidate regression.
- PR self-runner proceeds past both network-message preprocessing skills without relying on an arbitrary candidate choice.
