---
name: find-CCSGameRules_ResetRound
description: |
  Find and identify the CCSGameRules_ResetRound function in CS2 server binary using IDA Pro MCP.
  Use this skill when reverse engineering CS2 server.dll or libserver.so to locate the round-reset
  routine. It is the only function that references the "GMR_ResetRound\n" debug log string, and is
  the predecessor anchor for find-CCSGameRules_PostCleanUp (which it calls). Emits a unique IDA-style
  byte signature and a func YAML. Mirrors the find-CCSGameRules_ResetRound.py preprocessor
  (xref_strings "GMR_ResetRound\n").
  Trigger: CCSGameRules_ResetRound, ResetRound, GMR_ResetRound
disable-model-invocation: true
---

# Find CCSGameRules_ResetRound

Locate `CCSGameRules_ResetRound` in CS2 `server.dll` or `libserver.so` using IDA Pro MCP tools.

This is a **non-virtual, direct-call** member function (no vtable slot — emit a byte sig, not an
offset). It is the **predecessor anchor** for `CCSGameRules_PostCleanUp`: ResetRound directly calls
PostCleanUp, and PostCleanUp has no unique string of its own, so PostCleanUp is resolved downstream
by decompiling ResetRound.

**Primary resolution = the unique debug string** `"GMR_ResetRound\n"`. Exactly one function
references it: `CCSGameRules::ResetRound`.

## Method

### 1. Reuse previous signature (fast path)

If a prior `CCSGameRules_ResetRound.{platform}.yaml` exists, try its `func_sig` via
`mcp__ida-pro-mcp__find_bytes`. Single match → resolve to function start, skip to Step 4. Else continue.

### 2. Locate the anchor string and its referencer

```
mcp__ida-pro-mcp__find            type="string"  targets=["GMR_ResetRound"]
mcp__ida-pro-mcp__xrefs_to        addrs="<string_va>"
```

`"GMR_ResetRound\n"` has **exactly one** code referencer — that function is `ResetRound`. Record
`func_addr` (the containing function start). Optionally rename it to `CCSGameRules_ResetRound`.

### 3. Confirm (optional)

Decompile and confirm it is a round-reset routine: logs `GMR_ResetRound`, then performs the reset
sequence including the call to the entity-cleanup helper (`CCSGameRules_PostCleanUp`).

### 4. Generate signature

**ALWAYS** use SKILL `/generate-signature-for-function` with `addr=<func_addr>`. Emit IDA style
verbatim (space hex, `?` wildcards).

Reference sig (build 14165 — sanity check only, regenerate per binary):
- linux: `55 BE ? ? ? ? 48 89 E5 41 54 53 48 89 FB 48 83 EC ? 4C 8D 25 ? ? ? ? 41 8B 3C 24 E8 ? ? ? ? 84 C0 0F 85 ? ? ? ? F3 0F 10 83`

### 5. Write func YAML

**ALWAYS** use SKILL `/write-func-as-yaml`:
- `func_name`: `CCSGameRules_ResetRound`
- `func_addr`: `<func_addr>`
- `func_sig`: validated sig from step 4

## Function Characteristics

- **Linkage**: non-virtual, direct-call (no vtable entry)
- **Binary**: `server.dll` / `libserver.so`
- **Distinguishing trait**: only referencer of `"GMR_ResetRound\n"`; calls `CCSGameRules_PostCleanUp`

## Discovery Strategy (why this is stable across updates)

`"GMR_ResetRound\n"` is a durable debug log string with a single referencer, so ResetRound
re-resolves deterministically each game update. The final byte sig is regenerated per binary, so it
self-heals once the function is re-resolved.

## Preprocessor pipeline equivalent

```
find-CCSGameRules_ResetRound        [xref_strings "GMR_ResetRound\n"]
 -> find-CCSGameRules_PostCleanUp    [LLM_DECOMPILE ResetRound, entity-cleanup callee]
```

## Output YAML Format

- `server.dll`   -> `CCSGameRules_ResetRound.windows.yaml`
- `libserver.so` -> `CCSGameRules_ResetRound.linux.yaml`
