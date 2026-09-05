---
name: find-CEconItemView_CEconItemView
description: |
  Locate CEconItemView::CEconItemView in CS2 server.dll / libserver.so via IDA Pro MCP and emit a fresh, minimal-unique
  signature or offset for the WeaponPaints gamedata entry "CEconItemView::CEconItemView" (symbol CEconItemView_CEconItemView). This is the CONSTRUCTOR of CEconItemView. Shortlist via allocation sites: callers of operator-new whose result is immediately stored with the CEconItemView vtable (RTTI), followed by zeroing and initialization of definition-index/quantity/attribute-list fields. Distinguish from subobject constructors of derived classes by the vtable identity.
  Trigger: CEconItemView_CEconItemView, CEconItemView::CEconItemView
disable-model-invocation: true
---

# Find CEconItemView_CEconItemView

Target: `CEconItemView::CEconItemView` (func) in the CS2 server module, both `server.dll` (windows) and `libserver.so` (linux).

> Do NOT anchor on raw byte patterns from older releases — they shift. Use anchors only to *locate* the
> function, then generate a fresh minimal-unique function-head signature with relocated bytes wildcarded.

## Method

This is the CONSTRUCTOR of CEconItemView. Shortlist via allocation sites: callers of operator-new whose result is immediately stored with the CEconItemView vtable (RTTI), followed by zeroing and initialization of definition-index/quantity/attribute-list fields. Distinguish from subobject constructors of derived classes by the vtable identity.

## Output schema (STRICT)

Write the YAML file `CEconItemView_CEconItemView.{platform}.yaml` with EXACTLY these fields — no more, no fewer.
Unknown extra fields make the output invalid and abort the run.

```yaml
func_name: <SYMBOL_NAME>
func_va: "<hex virtual address, e.g. 0xaf8f90>"
func_rva: "<hex rva>"
func_size: "<hex size>"
func_sig: "<byte pattern, ?? wildcards, function head, minimal-unique>"
```
NEVER include vfunc_index, vfunc_offset, vfunc_sig or vtable_name — this is a non-virtual func artifact.

## Verification

1. Decompile the candidate and confirm the behavior matches the purpose above (not a caller or callee).
2. Confirm uniqueness: the generated pattern must match exactly one location in the loaded binary.
3. Values are per-platform — analyze BOTH server.dll and libserver.so and write one file per platform.

Prefer deterministic anchors first (RTTI / vtable / schema-network offsets); fall back to string anchors,
then caller/callee cross-checks. If a candidate cannot be confirmed, report the shortlist instead of
guessing — a skipped symbol is safer than a wrong signature.
