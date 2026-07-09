---
name: find-CBaseEntity_TakeDamageOld
description: |
  Find and identify the CBaseEntity::TakeDamageOld function in the CS2 server binary using IDA Pro MCP.
  Use this skill when reverse engineering CS2 server.dll or libserver.so to locate the legacy damage-application
  entry point by finding the code that references its self-identifying assert/warning message
  "CBaseEntity::TakeDamageOld: damagetype %d with info.GetDamageForce() == Vector::vZero".
  Trigger: CBaseEntity_TakeDamageOld
disable-model-invocation: true
---

# Find CBaseEntity_TakeDamageOld

Locate `CBaseEntity::TakeDamageOld` in CS2 `server.dll` / `libserver.so` using IDA Pro MCP tools.

## Method

### 1. Find the Self-Identifying Warning String

```text
mcp__ida-pro-mcp__find_regex pattern="TakeDamageOld: damagetype"
```

There are two closely related warning strings (one for `GetDamagePosition() == VectorWS::vZero`, one for
`GetDamageForce() == Vector::vZero`); either works as an anchor since both are printed from inside the same
function. Use `"CBaseEntity::TakeDamageOld: damagetype %d with info.GetDamageForce() == Vector::vZero"`.

> Linux 14168 reference: the string is at `0x982d40` (the `GetDamagePosition` variant is at `0x97a258`).

### 2. Get the Referencing Function

```text
mcp__ida-pro-mcp__xrefs_to addr="0x982d40"
```

The string has exactly one xref; its containing function is `CBaseEntity::TakeDamageOld`.

> Linux 14168 reference: `0x982d40` is referenced from `0xd4c387`, inside the function starting at `0xd4c280`
> (size `0xd15`).

### 3. Sanity-Check the Candidate

```text
mcp__ida-pro-mcp__decompile addr="0xd4c280"
```

Confirm the decompilation is consistent with `TakeDamageOld`'s known role: takes `this` plus a
`CTakeDamageInfo`-like structure/handle and additional damage-position/force parameters, validates the
damage-force/position vectors are non-zero (emitting the anchor warning otherwise), and applies health reduction,
armor absorption, and damage-event bookkeeping. The candidate's prologue also has a distinctive `pxor xmm0, xmm0`
(`66 0F EF C0`) immediately after the `push rbp`, used to zero-initialize a local vector/float before the
standard `mov rbp, rsp` — a useful secondary fingerprint alongside the string anchor.

### 4. Generate Function Signature

**ALWAYS** Use SKILL `/generate-signature-for-function` with `addr=0xd4c280` to generate a robust and unique
`func_sig`.

> Linux 14168 reference: generated signature is `55 66 0F EF C0 48 89 E5 41 57 41 56 41 55 49 89 FD 31 FF` —
> already unique across the binary at this length.

### 5. Write IDA Analysis Output as YAML

**ALWAYS** Use SKILL `/write-func-as-yaml` to write the analysis results.

Required parameters:
- `func_name`: `CBaseEntity_TakeDamageOld`
- `func_addr`: `0xd4c280`
- `func_sig`: The validated signature from step 4

## Function Characteristics

- **Purpose**: Legacy/compat damage-application entry point on `CBaseEntity`. Validates the incoming damage
  info's force/position vectors (warning if either is exactly zero for a damage type that expects a nonzero
  value), then applies health/armor reduction and damage-event bookkeeping.
- **Binary**: `server.dll` / `libserver.so`
- **Parameters**: `(this, damage info handle/pointer, double, float, ...)` (observed decompiled shape: `(_QWORD
  *a1, __int64 a2, void **a3, double a4, float a5)`).
- **Return value**: `__int64` (result/status, exact meaning not confirmed beyond "not a simple bool").

## Discovery Strategy

1. `TakeDamageOld` prints a self-identifying warning message (embedding its own qualified name,
   `"CBaseEntity::TakeDamageOld: ..."`) when it detects an invalid zero damage-force/position vector — this kind
   of self-naming assert string is an extremely reliable, low-ambiguity anchor since the function name is baked
   directly into the string.
2. The string has a single xref, so its containing function is unambiguous.
3. The candidate's parameter shape and the distinctive early `pxor xmm0, xmm0` in its prologue corroborate the
   identification.

This is robust because the anchor string literally contains the fully-qualified function name, making
misidentification essentially impossible as long as the string survives (which self-documenting assert/warning
strings reliably do across recompiles).

## Output YAML Format

The output YAML filename depends on the platform:
- `server.dll` -> `CBaseEntity_TakeDamageOld.windows.yaml`
- `libserver.so` -> `CBaseEntity_TakeDamageOld.linux.yaml`

Fields: `func_name`, `func_va`, `func_rva`, `func_size`, `func_sig`.
