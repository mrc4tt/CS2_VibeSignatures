---
name: find-CCSPlayerController_InventoryServices_m_pInventory
description: |
  Locate CCSPlayerController_InventoryServices::m_pInventory in CS2 server.dll / libserver.so via IDA Pro MCP and emit a fresh, minimal-unique
  signature or offset for the WeaponPaints gamedata entry "CCSPlayerController_InventoryServices::m_pInventory" (symbol CCSPlayerController_InventoryServices_m_pInventory). This is a STRUCT MEMBER OFFSET (schema netvar), not a function. Resolve the CCSPlayerController_InventoryServices class layout via the schema/network system; m_pInventory is an 8-byte pointer member early in the class (must stay 8-aligned). Cross-check: functions of the class dereference this->m_pInventory shortly after entry.
  Trigger: CCSPlayerController_InventoryServices_m_pInventory, CCSPlayerController_InventoryServices::m_pInventory
disable-model-invocation: true
---

# Find CCSPlayerController_InventoryServices_m_pInventory

Target: `CCSPlayerController_InventoryServices::m_pInventory` (structmember) in the CS2 server module, both `server.dll` (windows) and `libserver.so` (linux).

> Do NOT anchor on raw byte patterns from older releases — they shift. Use anchors only to *locate* the
> function, then generate a fresh minimal-unique function-head signature with relocated bytes wildcarded.

## Method

This is a STRUCT MEMBER OFFSET (schema netvar), not a function. Resolve the CCSPlayerController_InventoryServices class layout via the schema/network system; m_pInventory is an 8-byte pointer member early in the class (must stay 8-aligned). Cross-check: functions of the class dereference this->m_pInventory shortly after entry.

## Mandatory self-check before emitting (func artifacts)

The pipeline re-reads the bytes at your \`func_va\` and deterministically regenerates \`func_sig\` from
them — if your \`func_sig\` does not match those bytes EXACTLY (with \`??\` matching anything), the run
aborts. Therefore:

1. After picking the function, read the actual bytes at \`func_va\` via the IDA MCP (get-bytes/disasm).
2. Derive \`func_sig\` FROM those bytes: keep stable opcode bytes literally, wildcard relocated/
   variable operands (displacements, immediates, stack sizes) as \`??\`.
3. \`func_sig\` MUST start at \`func_va\` (the true function head — verify with IDA's function start).
4. Only then write the YAML. A mismatch is always a bug in YOUR output, never in the pipeline.

## Output schema (STRICT)

Write the YAML file `CCSPlayerController_InventoryServices_m_pInventory.{platform}.yaml` with EXACTLY these fields — no more, no fewer.
Unknown extra fields make the output invalid and abort the run.

```yaml
struct_name: <owning class name>
member_name: <member name>
offset: "<hex byte offset as string, e.g. 0x70>"
size: <member size in bytes, decimal>
offset_sig: "<short byte pattern of an instruction touching the offset, ?? wildcards>"
```
NEVER include func_* or vfunc_* fields — this is a struct-member (offset) artifact, not a function.

## Verification

1. Decompile the candidate and confirm the behavior matches the purpose above (not a caller or callee).
2. Confirm uniqueness: the generated pattern must match exactly one location in the loaded binary.
3. Values are per-platform — analyze BOTH server.dll and libserver.so and write one file per platform.

Prefer deterministic anchors first (RTTI / vtable / schema-network offsets); fall back to string anchors,
then caller/callee cross-checks. If a candidate cannot be confirmed, report the shortlist instead of
guessing — a skipped symbol is safer than a wrong signature.
