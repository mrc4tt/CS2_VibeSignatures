---
name: find-CBaseEntity_m_NetworkTransmitComponent
description: |
  Agent fallback for CBaseEntity_m_NetworkTransmitComponent (auto-generated, category: structmember). Locate
  CBaseEntity::m_NetworkTransmitComponent in the CS2 server module via IDA Pro MCP and emit a fresh,
  minimal-unique artifact. The deterministic preprocessor could not resolve this
  symbol on the current gamever - your job is the re-sign.
  Trigger: CBaseEntity_m_NetworkTransmitComponent, CBaseEntity::m_NetworkTransmitComponent
disable-model-invocation: true
---

# Find CBaseEntity_m_NetworkTransmitComponent

Target: `CBaseEntity::m_NetworkTransmitComponent` (structmember) in the module loaded in THIS session.

> The old artifact/preprocessor anchors no longer match this build. Use anchors
> only to *locate* candidates; derive the artifact from the ACTUAL bytes you read.
> Produce ONLY this session's platform output. NEVER open another binary.

## Method

Resolve the class layout via the schema/network system or instructions that
dereference the member. Verify natural alignment and cross-check with
constructor/accessor functions.

## Mandatory self-check before emitting

The pipeline re-reads the bytes at your `func_va` and regenerates `func_sig` from
them - a mismatch aborts the run. Therefore: read the real bytes via IDA MCP,
derive the artifact FROM those bytes (wildcard relocated operands as `??`), start
at the TRUE function head, and only then write the YAML. A mismatch is always a
bug in YOUR output.

## Output schema (STRICT)

Write `<task>.{platform}.yaml` with EXACTLY these fields:

```yaml
struct_name: <owning class name>
member_name: <member name>
offset: "<hex byte offset as string>"
size: <member size in bytes, decimal>
offset_sig: "<short byte pattern of an instruction touching the offset>"
```
NEVER include func_* or vfunc_* fields.

## Verification

1. Decompile and confirm the behavior matches the symbol's semantics.
2. Uniqueness: the pattern must match exactly ONE location in the loaded binary.
3. If no candidate can be confirmed, report the shortlist - a skipped symbol is
   safer than a wrong signature.
