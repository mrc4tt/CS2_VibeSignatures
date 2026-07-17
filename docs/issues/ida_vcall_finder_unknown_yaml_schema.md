# Bug: ida_vcall_finder unknown YAML schemas collapse into empty results

## Status

Open. Identified during the follow-up audit for `llm_decompile_symbol_wrapped_yaml.md` on 2026-07-17.

## Summary

`ida_vcall_finder.parse_llm_vcall_response(...)` accepts a YAML mapping and reads only its root-level `found_vcall` key. Blank responses, invalid YAML, non-mapping YAML, empty mappings, unknown root keys, invalid section containers, and malformed entries all normalize to the same empty `found_vcall` result.

This mirrors the state-collapsing weakness fixed in `ida_llm_decompile.py`, but the vcall finder has a separate single-category prompt and call path without the same semantic-validation and correction-retry pipeline.

## Evidence

Relevant code:

- `ida_vcall_finder.py:221-247`
- `ida_vcall_finder.py:294-304`

The parser returns `{"found_vcall": []}` when a parsed mapping does not contain the recognized root key:

```python
return {"found_vcall": normalize_found_vcalls(parsed.get("found_vcall", []))}
```

Malformed entries are also silently discarded by `normalize_found_vcalls(...)`.

## Recommended Follow-up

Add a schema-aware parse outcome local to the vcall finder that distinguishes:

- a canonical `found_vcall` response;
- an explicit canonical empty response;
- invalid YAML or root types;
- unknown root keys;
- invalid section and entry shapes.

Then route schema issues through an explicit correction retry or fail with a diagnostic that cannot be mistaken for a valid no-result response. Keep this work separate from the batched `llm_decompile` fix because the prompt contract, accepted fields, and retry ownership differ.

## Acceptance Criteria

- Unknown or malformed YAML cannot be silently accepted as a valid empty vcall result.
- Explicit empty output has a documented canonical form.
- Parser status is observable in debug output.
- Unit tests cover invalid roots, malformed entries, explicit empty output, correction, and retry exhaustion.
