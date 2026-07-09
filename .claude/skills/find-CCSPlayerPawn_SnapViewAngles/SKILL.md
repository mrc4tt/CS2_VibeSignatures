---
name: find-CCSPlayerPawn_SnapViewAngles
description: |
  Find and identify the CCSPlayerPawn_SnapViewAngles function in CS2 server binary using IDA Pro MCP.
  Use this skill when reverse engineering CS2 server.dll or libserver.so to locate the non-virtual
  SnapViewAngles method, anchored on the "setang" console-command usage string and its non-teleport
  call branch. Emits a unique IDA-style byte signature and a func YAML.
  Trigger: CCSPlayerPawn_SnapViewAngles, SnapViewAngles
disable-model-invocation: true
---

# Find CCSPlayerPawn_SnapViewAngles

Locate `CCSPlayerPawn_SnapViewAngles` in CS2 `server.dll` or `libserver.so` using IDA Pro MCP tools.

This is a **non-virtual, direct-call** member function (no vtable slot — emit a byte sig, not an
offset). It snaps the pawn's networked eye angle (`m_angEyeAngles`, `CNetworkVectorBase<QAngle>`)
**and** caches the angle + previous value into the pawn for prediction — that cache is what
distinguishes it from its sibling `SnapEyeAngles`.

## Method

### 1. Reuse previous signature (fast path)

If a prior `CCSPlayerPawn_SnapViewAngles.{platform}.yaml` exists, try its `func_sig` first via
`mcp__ida-pro-mcp__find_bytes`. Single match → resolve to function start, skip to Step 5 to
regenerate a fresh sig and re-emit. If absent or non-unique, continue.

### 2. Anchor on the `setang` command handler

```
mcp__ida-pro-mcp__find_regex pattern="setang pitch yaw"
```

Expect: `"Usage:  setang pitch yaw <roll optional> <prediction sync ticks optional>\n"`.
Find the referencing function (the **setang handler**, tracked as `Setang_CommandHandler` in the
preprocessor pipeline):

```
mcp__ida-pro-mcp__xrefs_to addrs="<usage_string_addr>"
mcp__ida-pro-mcp__decompile addr="<setang_handler_addr>" include_addresses=false
```

### 3. Pick the non-teleport branch call target

The setang handler parses `pitch yaw [roll] [predticks]` then branches:

- **Teleport / prediction-sync branch** — taken when `argc >= 5 && atoi(predticks) > 0`. Builds a
  `CPredictionEvent_Teleport` (constructs + dispatches through the `CPredictionEvent_Teleport_t`
  vtable). **Ignore the call here.**
- **else branch** — directly `return SnapViewAngles(pawn, &localQAngle)` (no prediction event).

`SnapViewAngles` = **the function called/returned in the else (non-teleport) branch.** On
`server.dll` the same target is returned from two non-teleport returns (`argc < 5` and `predticks <= 0`).

### 4. Confirm identity

Decompile the candidate and verify ALL:

1. Normalizes the QAngle through a helper near the top (`normalize(a2) -> local`).
2. **Caches angle + previous into the pawn**: four stores at consecutive member offsets
   (current angle, current roll/float, prior angle, prior float). Linux build 14165 example:
   `*(pawn+0xD98)=angle; *(pawn+0xDA4)=oldangle; *(pawn+0xDA0)=roll; *(pawn+0xDAC)=oldroll`.
   This prediction cache is the **view** signature trait (the sibling `SnapEyeAngles` has no cache).
3. Networks the eye-angle QAngle through change-accessor helpers, guarded by the entity-handle
   validity check (`handle != -1 && != -2 && global_ent_table != 0`).
4. Internal state byte set to the **view** value (linux: change-field id `48`; the eye sibling uses `2`).

Record `func_addr`. Optionally rename to `CCSPlayerPawn_SnapViewAngles` via `mcp__ida-pro-mcp__rename`.

### 5. Generate signature

**ALWAYS** use SKILL `/generate-signature-for-function` with `addr=<func_addr>` to produce a
unique IDA-style `func_sig`. Emit IDA style verbatim (space hex, `?` wildcards) — do NOT convert
to CSS `\x2A` unless a `gamedata.json` entry is explicitly requested.

Reference sigs (build 14165 — sanity check only, regenerate per binary):
- linux:   `55 48 89 E5 41 57 49 89 FF 48 89 F7 41 56 41 55 41 54 53 48 81 EC`
- windows: `48 89 5C 24 ? 48 89 74 24 ? 48 89 7C 24 ? 55 48 8D 6C 24 ? 48 81 EC ? ? ? ? 48 8B DA 48 8B F1 48 8D 55`

### 6. Write func YAML

**ALWAYS** use SKILL `/write-func-as-yaml`:
- `func_name`: `CCSPlayerPawn_SnapViewAngles`
- `func_addr`: `<func_addr>`
- `func_sig`: validated sig from step 5

Include `func_va/func_rva/func_size` (this function is the predecessor anchor for both
`find-CCSPlayerPawn_ApplyEyeAngleNetworkChange` and `find-CCSPlayerPawn_SnapEyeAngles`).

## Preprocessor pipeline equivalent

Interactive twin of the unattended chain in `ida_preprocessor_scripts/`:

```
find-Setang_CommandHandler                    [xref_strings "setang pitch yaw"]
 -> find-CCSPlayerPawn_SnapViewAngles          [LLM_DECOMPILE off handler, non-teleport call]   <- this skill
 -> find-CCSPlayerPawn_ApplyEyeAngleNetworkChange [LLM_DECOMPILE off SnapViewAngles, apply call]
 -> find-CCSPlayerPawn_SnapEyeAngles           [xref_funcs apply-helper, exclude_funcs SnapViewAngles]
```

Reference YAML: `references/server/Setang_CommandHandler.{platform}.yaml`.

## Function Characteristics

- **Linkage**: non-virtual, direct-call (no vtable entry)
- **Binary**: `server.dll` / `libserver.so`
- **Parameters**: `(pawn, QAngle* angles)` (+ float on linux ABI)
- **Caller**: the `setang` console-command handler, non-teleport branch
- **Distinguishing trait**: caches angle + previous into the pawn (prediction); networks `m_angEyeAngles`

## Output YAML Format

- `server.dll`     -> `CCSPlayerPawn_SnapViewAngles.windows.yaml`
- `libserver.so`   -> `CCSPlayerPawn_SnapViewAngles.linux.yaml`
