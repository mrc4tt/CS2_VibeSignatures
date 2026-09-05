---
name: find-CCSPlayerInventory_m_pSOCache
description: |
  Locate CCSPlayerInventory::m_pSOCache in CS2 server.dll / libserver.so via IDA Pro MCP and emit a fresh, minimal-unique
  signature or offset for the WeaponPaints gamedata entry "CCSPlayerInventory::m_pSOCache" (symbol CCSPlayerInventory_m_pSOCache). This is a STRUCT MEMBER OFFSET (schema netvar). Resolve the CCSPlayerInventory class layout via the schema system; m_pSOCache is the CGCClientSharedObjectCache pointer member. Cross-check: CCSPlayerInventory methods load this pointer and pass it to CGCClientSharedObjectCache methods (the GetItemInLoadout shortlist is a strong caller-side witness).
  Trigger: CCSPlayerInventory_m_pSOCache, CCSPlayerInventory::m_pSOCache
disable-model-invocation: true
---

# Find CCSPlayerInventory_m_pSOCache

Target: `CCSPlayerInventory::m_pSOCache` (structmember) in the CS2 server module, both `server.dll` (windows) and `libserver.so` (linux).

> Do NOT anchor on raw byte patterns from older releases — they shift. Use anchors only to *locate* the
> function, then generate a fresh minimal-unique function-head signature with relocated bytes wildcarded.

## Method

This is a STRUCT MEMBER OFFSET (schema netvar). Resolve the CCSPlayerInventory class layout via the schema system; m_pSOCache is the CGCClientSharedObjectCache pointer member. Cross-check: CCSPlayerInventory methods load this pointer and pass it to CGCClientSharedObjectCache methods (the GetItemInLoadout shortlist is a strong caller-side witness).

## Output schema (STRICT)

Write the YAML file `CCSPlayerInventory_m_pSOCache.{platform}.yaml` with EXACTLY these fields — no more, no fewer.
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
