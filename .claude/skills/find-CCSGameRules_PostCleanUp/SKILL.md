---
name: find-CCSGameRules_PostCleanUp
description: |
  Find and identify the CCSGameRules_PostCleanUp function in CS2 server binary using IDA Pro MCP.
  Use this skill when reverse engineering CS2 server.dll or libserver.so to locate the post-round
  entity-cleanup routine. It is non-virtual and has no unique string of its own, so it is found via
  the CCSGameRules_ResetRound predecessor: PostCleanUp is the entity-cleanup call ResetRound makes.
  Emits a unique IDA-style byte signature and a func YAML. Mirrors the find-CCSGameRules_PostCleanUp.py
  preprocessor (LLM_DECOMPILE CCSGameRules_ResetRound).
  Trigger: CCSGameRules_PostCleanUp, PostCleanUp, CGameRules::PostCleanUp
disable-model-invocation: true
---

# Find CCSGameRules_PostCleanUp

Locate `CCSGameRules_PostCleanUp` in CS2 `server.dll` or `libserver.so` using IDA Pro MCP tools.

This is a **non-virtual, direct-call** member function (no vtable slot — emit a byte sig, not an
offset). It has **no unique string of its own**: it references `"cs_respawn"`, which is shared with
another large function — so a pure string anchor is **not** unique. It is found via its predecessor
`CCSGameRules_ResetRound`, which calls it.

**Primary resolution = decompile the ResetRound predecessor and pick the entity-cleanup callee.**

## Method

### 1. Reuse previous signature (fast path)

If a prior `CCSGameRules_PostCleanUp.{platform}.yaml` exists, try its `func_sig` via
`mcp__ida-pro-mcp__find_bytes`. Single match → resolve to function start, skip to Step 5. Else continue.

### 2. Load CCSGameRules_ResetRound (the anchor)

**ALWAYS** use SKILL `/get-func-from-yaml` with `func_name=CCSGameRules_ResetRound`.

If it errors (not yet found), run SKILL `/find-CCSGameRules_ResetRound` first, then retry.
Extract `func_va` of `CCSGameRules_ResetRound`.

### 3. Enumerate ResetRound's callees

```
mcp__ida-pro-mcp__callees   addrs="<ResetRound_func_va>"
mcp__ida-pro-mcp__decompile addr="<ResetRound_func_va>" include_addresses=false
```

### 4. Identify PostCleanUp among the callees

`PostCleanUp` is the callee of ResetRound that performs the post-round entity cleanup. Decompile the
candidate and confirm ALL:

1. **Iterates the global entity list** (walks entity handles via the entity-system helpers).
2. **dynamic-casts** to `CCSWeaponBase`, `CBombTarget`, and `CHostageRescueZone` (RTTI typeinfo refs
   `_ZTI13CCSWeaponBase`, `_ZTI11CBombTarget`, `_ZTI18CHostageRescueZone`). ← key fingerprint.
3. **References the `"cs_respawn"` string** (and the `ai_network` / `ai_hint` entity-name pointers).
4. Frees/cleans up the matched entities (calls into the mem-free / entity-destroy path).

The `"cs_respawn"` string has two referencers; PostCleanUp is the one reached as a callee of
ResetRound (the other is a much larger think/restart function, not called by ResetRound).

Record `func_addr`. Optionally rename to `CCSGameRules_PostCleanUp`.

### 5. Generate signature

**ALWAYS** use SKILL `/generate-signature-for-function` with `addr=<func_addr>`. Emit IDA style
verbatim (space hex, `?` wildcards) — do NOT convert to CSS `\x2A` unless a `gamedata.json` entry
is explicitly requested.

Reference sig (build 14165 — sanity check only, regenerate per binary):
- linux: `55 48 89 E5 41 57 49 89 FF 41 56 41 55 41 54 53 48 81 EC ? ? ? ? E8 ? ? ? ? 66 83 F8`

### 6. Write func YAML

**ALWAYS** use SKILL `/write-func-as-yaml`:
- `func_name`: `CCSGameRules_PostCleanUp`
- `func_addr`: `<func_addr>`
- `func_sig`: validated sig from step 5

## Function Characteristics

- **Linkage**: non-virtual, direct-call (no vtable entry)
- **Binary**: `server.dll` / `libserver.so`
- **Caller**: `CCSGameRules_ResetRound` (and one other round-restart path)
- **Distinguishing trait**: entity-list walk + dynamic_cast to CCSWeaponBase/CBombTarget/
  CHostageRescueZone + `"cs_respawn"` reference

## Discovery Strategy (why this is stable across updates)

1. `ResetRound` is the durable anchor (found via the unique `"GMR_ResetRound\n"` string).
2. PostCleanUp is pinned as ResetRound's entity-cleanup callee — deterministic, not address-based.
3. The final byte sig is regenerated per binary, so it self-heals each game update once the
   functions are re-resolved.

## Preprocessor pipeline equivalent

```
find-CCSGameRules_ResetRound        [xref_strings "GMR_ResetRound\n"]
 -> find-CCSGameRules_PostCleanUp    [LLM_DECOMPILE ResetRound, entity-cleanup callee]
```

Reference YAML lives in `references/server/CCSGameRules_ResetRound.{platform}.yaml`.

## Output YAML Format

- `server.dll`   -> `CCSGameRules_PostCleanUp.windows.yaml`
- `libserver.so` -> `CCSGameRules_PostCleanUp.linux.yaml`
