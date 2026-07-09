---
name: find-CCSPlayerPawn_SnapEyeAngles
description: |
  Find and identify the CCSPlayerPawn_SnapEyeAngles function in CS2 server binary using IDA Pro MCP.
  Use this skill when reverse engineering CS2 server.dll or libserver.so to locate the non-virtual
  SnapEyeAngles method. It is the one caller of the shared apply helper
  (CCSPlayerPawn_ApplyEyeAngleNetworkChange) that is NOT CCSPlayerPawn_SnapViewAngles. Emits a
  unique IDA-style byte signature and a func YAML. Mirrors the find-CCSPlayerPawn_SnapEyeAngles.py
  preprocessor (xref_funcs apply-helper, exclude_funcs SnapViewAngles).
  Trigger: CCSPlayerPawn_SnapEyeAngles, SnapEyeAngles
disable-model-invocation: true
---

# Find CCSPlayerPawn_SnapEyeAngles

Locate `CCSPlayerPawn_SnapEyeAngles` in CS2 `server.dll` or `libserver.so` using IDA Pro MCP tools.

This is a **non-virtual, direct-call** member function (no vtable slot — emit a byte sig, not an
offset). It is the structural **twin** of `CCSPlayerPawn_SnapViewAngles`: same normalize helper,
same apply helper, same network-change fields — but it does **NOT** cache the angle+previous into
the pawn, and sets a different internal state byte.

**Primary resolution = the apply-helper caller chain** (matches the preprocessor script): the
shared apply helper `CCSPlayerPawn_ApplyEyeAngleNetworkChange` has **exactly two callers** —
`SnapViewAngles` and `SnapEyeAngles`. Take the caller that is not `SnapViewAngles`.

## Method

### 1. Reuse previous signature (fast path)

If a prior `CCSPlayerPawn_SnapEyeAngles.{platform}.yaml` exists, try its `func_sig` via
`mcp__ida-pro-mcp__find_bytes`. Single match → resolve to function start, skip to Step 5. Else continue.

### 2. Load CCSPlayerPawn_SnapViewAngles (the anchor)

**ALWAYS** use SKILL `/get-func-from-yaml` with `func_name=CCSPlayerPawn_SnapViewAngles`.

If it errors (not yet found), run SKILL `/find-CCSPlayerPawn_SnapViewAngles` first, then retry.
Extract `func_va` of `CCSPlayerPawn_SnapViewAngles`.

### 3. Identify the apply helper inside SnapViewAngles

```
mcp__ida-pro-mcp__callees addrs="<SnapViewAngles_func_va>"
mcp__ida-pro-mcp__decompile addr="<SnapViewAngles_func_va>" include_addresses=false
```

The **apply helper** (`CCSPlayerPawn_ApplyEyeAngleNetworkChange`) is the call made late in
SnapViewAngles (just before the memfree tail), taking `(pawn, local)`; it applies the m_angEyeAngles
network-state change (touches the pawn's networkvar change-component). Record `apply_helper_addr`.
Optionally rename it to `CCSPlayerPawn_ApplyEyeAngleNetworkChange`.

### 4. Apply-helper caller minus SnapViewAngles → SnapEyeAngles

```
mcp__ida-pro-mcp__xrefs_to addrs="<apply_helper_addr>"
```

The apply helper has **exactly two code callers**: `SnapViewAngles` and `SnapEyeAngles` (plus
data/vtable refs). `SnapEyeAngles` = **the code caller that is not `SnapViewAngles`**. This is the
interactive form of the preprocessor's `xref_funcs=[ApplyEyeAngleNetworkChange]` +
`exclude_funcs=[SnapViewAngles]`. If a third code caller ever appears, fall back to the structural
confirmation below.

Decompile the candidate and confirm ALL:

1. Calls the **same** apply helper as SnapViewAngles.
2. Writes the **same** network-change fields, guarded by the same entity-handle validity check.
3. Does **NOT** perform the angle+previous cache stores into the pawn (no consecutive member stores
   at the SnapViewAngles cache offsets). ← key disambiguator.
4. Internal state byte set to the **eye** value (`2`), vs view's value.
5. (Confirmation) its only caller is the `eyeangle` console command handler (no string of its own;
   reached via a command-dispatch table).

Adjacency hint (linux often, not guaranteed on windows): SnapEyeAngles frequently sits immediately
**before** SnapViewAngles in address order. Use only as a hint — always confirm structurally.

Record `func_addr`. Optionally rename to `CCSPlayerPawn_SnapEyeAngles`.

### 5. Generate signature

**ALWAYS** use SKILL `/generate-signature-for-function` with `addr=<func_addr>`. Emit IDA style
verbatim (space hex, `?` wildcards) — do NOT convert to CSS `\x2A` unless a `gamedata.json` entry
is explicitly requested.

Reference sigs (build 14165 — sanity check only, regenerate per binary):
- linux:   `55 48 89 E5 41 57 41 56 41 55 41 54 53 48 89 FB 48 89 F7 48 81 EC ? ? ? ? E8 ? ? ? ? 8B 8B`
- windows: `48 89 5C 24 ? 48 89 74 24 ? 55 48 8D 6C 24 ? 48 81 EC ? ? ? ? 48 8B DA`

### 6. Write func YAML

**ALWAYS** use SKILL `/write-func-as-yaml`:
- `func_name`: `CCSPlayerPawn_SnapEyeAngles`
- `func_addr`: `<func_addr>`
- `func_sig`: validated sig from step 5

## Function Characteristics

- **Linkage**: non-virtual, direct-call (no vtable entry)
- **Binary**: `server.dll` / `libserver.so`
- **Parameters**: `(pawn, QAngle* angles)` (+ float on linux ABI)
- **Caller**: the `eyeangle` console-command handler
- **Distinguishing trait**: structural twin of SnapViewAngles WITHOUT the prediction cache;
  state byte = `2`; same normalize + apply helpers; networks `m_angEyeAngles`

## Discovery Strategy (why this is stable across updates)

1. `SnapViewAngles` is the durable anchor (found via the `setang` usage string → handler → its
   non-teleport branch call).
2. The apply helper `CCSPlayerPawn_ApplyEyeAngleNetworkChange` is pinned inside SnapViewAngles, and
   has exactly two callers; `SnapEyeAngles` is the non-view caller — deterministic, not
   address-based.
3. The final byte sig is regenerated per binary, so it self-heals each game update once the
   functions are re-resolved.

## Preprocessor pipeline equivalent

This skill is the interactive twin of the unattended chain in `ida_preprocessor_scripts/`:

```
find-Setang_CommandHandler                    [xref_strings "setang pitch yaw"]
 -> find-CCSPlayerPawn_SnapViewAngles          [LLM_DECOMPILE off handler, non-teleport call]
 -> find-CCSPlayerPawn_ApplyEyeAngleNetworkChange [LLM_DECOMPILE off SnapViewAngles, apply call]
 -> find-CCSPlayerPawn_SnapEyeAngles           [xref_funcs apply-helper, exclude_funcs SnapViewAngles]
```

Reference YAMLs live in `references/server/{Setang_CommandHandler,CCSPlayerPawn_SnapViewAngles}.{platform}.yaml`.

## Output YAML Format

- `server.dll`     -> `CCSPlayerPawn_SnapEyeAngles.windows.yaml`
- `libserver.so`   -> `CCSPlayerPawn_SnapEyeAngles.linux.yaml`
