---
name: find-CBaseEntity_SpawnRadius
description: |
  Find and identify the CBaseEntity_SpawnRadius function in the CS2 server binary using IDA Pro MCP. Use
  this skill when reverse engineering CS2 server.dll or libserver.so to locate the radius-aware spawn
  helper that resolves an entity's effect/trigger radius from either its float argument or the "radius"
  keyvalue, then applies it and reads the entity's "hammerUniqueId" keyvalue. Resolved via the two econ/
  hammer keyvalue literals "radius" and "hammerUniqueId": the single function that references BOTH is the
  target.
  Trigger: CBaseEntity_SpawnRadius, SpawnRadius
disable-model-invocation: true
---

# Find CBaseEntity_SpawnRadius

Locate `CBaseEntity_SpawnRadius` in CS2 `server.dll` / `libserver.so` using IDA Pro MCP tools.

This is a **non-virtual, direct-call** member function (no vtable entry of its own — emit a byte sig, not
an offset).

> **Do not** anchor the discovery recipe on the raw byte pattern below — bytes/wildcards shift release to
> release. Use it only to *locate/confirm* the function on the currently loaded binary, then generate a
> fresh signature at the end.

## Method

### 1. Locate the durable anchor string

`CBaseEntity_SpawnRadius` reads two entity keyvalues by name — `"radius"` and `"hammerUniqueId"`. The
`"hammerUniqueId"` literal is the rarer, more distinctive anchor (a single string in the module).

```text
mcp__ida-pro-mcp__find   type="string" targets=["hammerUniqueId"]
```

> Linux 14168 reference: `"hammerUniqueId"` is at `0x92a4b9`.

### 2. Shortlist the referencing functions

```text
mcp__ida-pro-mcp__xrefs_to   addrs="0x92a4b9"
```

`"hammerUniqueId"` is referenced by a small handful of functions (its keyvalue lookup appears at the tail
of several spawn/precache-style routines).

> Linux 14168 reference: referenced by three functions — `sub_D4AB10` (`0xD4AB10`, size `0x4bd`),
> `sub_16BFA90` (`0x16BFA90`), and `sub_181F580` (`0x181F580`).

### 3. Disambiguate with the "radius" keyvalue

`CBaseEntity_SpawnRadius` is the **only** one of those functions that also references the `"radius"`
keyvalue string. Decompile each candidate and keep the one that references both `"radius"` and
`"hammerUniqueId"`:

```text
mcp__ida-pro-mcp__decompile   addr="<candidate_func_va>"
```

The target's body has this distinctive shape:

- Signature `(entity *this, KeyValues *pKV, float radius)` — takes a **float radius argument**.
- When the float argument is negative, it falls back to reading the `"radius"` keyvalue by name (via the
  keyvalue-by-name lookup helper) and coerces the result (int/uint64/double/string) to a float.
- If the resolved radius is `> 0.0`, it applies it to the entity's collision/trigger bounds structure;
  otherwise it takes the zero-radius path.
- Near the end it reads the `"hammerUniqueId"` keyvalue and stores the resulting string on the entity.

> Linux 14168 reference: the target is `sub_D4AB10` at `0xD4AB10`. It reads `"radius"` (`0x90068f`) in the
> `a3 < 0.0` branch and `"hammerUniqueId"` (`0x92a4b9`) near the end. The other two candidates reference
> only `"hammerUniqueId"`.

### 4. Generate function signature

**ALWAYS** Use SKILL `/generate-signature-for-function` with `addr=<target_func_va>` to generate a robust
and unique `func_sig`.

> Linux 14168 reference: `55 48 89 E5 41 57 41 56 41 55 41 54 49 89 F4 53 48 89 FB 48 83 EC 68 F3 0F 11 85
> 7C FF FF FF` — unique across the binary at this length (no wildcards required).

### 5. Write IDA Analysis Output as YAML

**ALWAYS** Use SKILL `/write-func-as-yaml` to write the analysis results.

Required parameters:
- `func_name`: `CBaseEntity_SpawnRadius`
- `func_addr`: `<target_func_va>`
- `func_sig`: The validated signature from step 4

## Function Characteristics

- **Purpose**: Resolves an entity's radius (from a float argument, or the `"radius"` keyvalue when the
  argument is negative), applies it to the entity's bounds/collision, and reads the `"hammerUniqueId"`
  keyvalue.
- **Binary**: `server.dll` / `libserver.so`
- **Linkage**: non-virtual, direct-call (no vtable entry).
- **Parameters**: `(__int64 this, __int64 pKeyValues, float radius)` (observed decompiled shape).
- **Return value**: non-void (propagates an allocation/cleanup result).

## Discovery Strategy

1. Anchor on the rare literal `"hammerUniqueId"` and take its (few) referencers.
2. Intersect with the `"radius"` keyvalue literal — exactly one referencer uses both.
3. Confirm the candidate takes a `float radius` argument and has the negative-argument → `"radius"`
   keyvalue fallback body shape.

This is robust because both anchors are verbatim keyvalue-name literals that survive recompilation, and
the two-string intersection is unambiguous.

## Output YAML Format

```yaml
func_name: CBaseEntity_SpawnRadius
func_va: '0x<va>'
func_rva: '0x<rva>'
func_size: '0x<size>'
func_sig: <space-separated byte pattern from step 4>
```
