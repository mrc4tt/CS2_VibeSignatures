---
name: find-UTIL_PlayerSlotToPlayerController-AND-FireTargets-AND-CCSPlayer_ItemServices_RemoveWeapons
description: |
  Find and identify the UTIL_PlayerSlotToPlayerController function, the FireTargets function, and the
  CCSPlayer_ItemServices_RemoveWeapons virtual function in CS2 binary using IDA Pro MCP. Use this skill when
  reverse engineering CS2 server.dll or libserver.so to locate all three by decompiling the already-known
  CMultiplayRules_ClientDisconnected anchor, which calls all three in sequence (slot->controller lookup, then a
  "game_playerleave" FireTargets broadcast, then a devirtualized RemoveWeapons(true) call), and to confirm
  RemoveWeapons's vtable slot against the CCSPlayer_ItemServices vtable.
  Trigger: UTIL_PlayerSlotToPlayerController, FireTargets, CCSPlayer_ItemServices_RemoveWeapons
disable-model-invocation: true
---

# Find UTIL_PlayerSlotToPlayerController, FireTargets, CCSPlayer_ItemServices_RemoveWeapons

Locate `UTIL_PlayerSlotToPlayerController`, `FireTargets`, and `CCSPlayer_ItemServices_RemoveWeapons` in CS2
`server.dll` or `libserver.so` using IDA Pro MCP tools.

## Method

### 1. Load CMultiplayRules_ClientDisconnected from YAML

**ALWAYS** Use SKILL `/get-func-from-yaml` with `func_name=CMultiplayRules_ClientDisconnected`.

If the skill returns an error, **STOP** and report to user (this skill's anchor must already be resolved).

Otherwise, extract:
- `func_va` of `CMultiplayRules_ClientDisconnected`

### 2. Decompile the Anchor

```text
mcp__ida-pro-mcp__decompile addr="<ClientDisconnected_func_addr>"
```

`ClientDisconnected(this, unsigned int playerSlot)` is a short function (roughly 100-120 bytes) with exactly three
meaningful calls in its body, in this order — identify each by shape as described below.

### 3. Identify UTIL_PlayerSlotToPlayerController

The **first** call, taking the raw `playerSlot` integer argument directly:

- Bounds-checks the slot against a global max-player-count field (`off_261F328`-style global, dereferenced and
  compared as `> slot`).
- On success, converts `slot` to a 1-based index and performs an entity-handle-table lookup
  (`sub_16A49A0`/handle-resolve-style call) to return the corresponding `CCSPlayerController *`.
- Returns `0`/`nullptr` on failure (negative slot or out-of-range).

> Linux 14168 reference: `UTIL_PlayerSlotToPlayerController` is at `0x1785a00`, size `0x33` (51 bytes). Generated
> `func_sig`: `48 8D 05 ? ? ? ? 48 8B 00 85 FF`.

### 4. Identify FireTargets

The controller returned by step 3 is passed through one more helper (a `CHandle`/pawn-resolve step) and then into
the **second** call, which takes a **literal string** as its first argument. On the `ClientDisconnected` path this
string is `"game_playerleave"`:

- Signature shape: `(const char *pszTargetName, <2 packed 8-byte fields, e.g. an activator/caller entity handle
  pair>, int useType, float value)`.
- Body: early-outs if the name string is null/empty; otherwise logs `"Firing: (%s)\n"` at verbosity 2, then loops
  calling `CGameEntitySystem::FindEntityByName`-equivalent with the target name, and for each non-marked-for-deletion
  match, logs `"[%03d] Found: %s, firing (%s)\n"` and invokes that entity's own **I/O-fire vfunc** (a vcall at
  offset `1152` on Linux / `1144` on some builds — read directly off the found entity, do not hard-code) with the
  packed activator/caller/useType/value payload.
- The two format strings `"Firing: (%s)\n"` and `"[%03d] Found: %s, firing (%s)\n"` are present verbatim and are
  the single most reliable independent fingerprint — locate them directly with `find_regex` and take the
  containing function if the call-site approach is inconvenient.

> Linux 14168 reference: `FireTargets` is at `0x1aa0060`, size `0x118` (280 bytes). Independently confirmed via
> `find_regex pattern="Firing: \(%s\)"` -> string at `0x93ba4a` -> sole xref inside `0x1aa0060`. Generated
> `func_sig`: `55 48 89 E5 41 57 41 56 41 55 41 54 53 48 83 EC ? 89 4D ? F3 0F 11 45 ? 48 85 FF`.

### 5. Identify CCSPlayer_ItemServices_RemoveWeapons

The **third** call in the anchor reads the disconnecting pawn's `ItemServices` pointer (`pawn + 3352` on the
reference build) and, if non-null, issues a **devirtualized-looking indirect call** through that pointer's own
vtable at offset **224** (`0xE0`) with a single `true`/`1` argument:

```c
if ( v4 ) return (*(*(_QWORD *)v4 + 224))(v4, 1);
```

Offset `224 = 28 * 8`, i.e. vtable **slot 28** of `CCSPlayer_ItemServices` — cross-check this against the RTTI
vtable walk below.

**ALWAYS** Use SKILL `/get-vtable-address` with `class_name=CCSPlayer_ItemServices` to independently RTTI-walk the
vtable and confirm slot 28's function pointer matches the call target implied above:

```text
mcp__ida-pro-mcp__find_regex pattern="22CCSPlayer_ItemServices"
mcp__ida-pro-mcp__xrefs_to addrs="<name_string_addr>"      # hit - 8 = typeinfo
mcp__ida-pro-mcp__xrefs_to addrs="<typeinfo_addr>"          # hit - 8 = vtable candidate, keep offset_to_top==0
mcp__ida-pro-mcp__get_int addr="<vtable_va> + 0x10 + 28*8" ty="u64"
```

Decompile the resolved slot-28 function and confirm it matches "remove all weapons" semantics: a single `bool`
parameter (drop-vs-destroy or similar), and a body that clears multiple per-player-item bookkeeping fields
(`this+72`-region flag, an inventory-count field at `this+5560`-region) and conditionally calls further
weapon-teardown helpers depending on the bool argument, ending in a call into an entity-teardown/network-reset
helper.

> Linux 14168 reference: `CCSPlayer_ItemServices` name string `22CCSPlayer_ItemServices` at `0x8219d0`, typeinfo
> at `0x2489888`, primary vtable at `0x2489cf0`. Slot 28 (`vfunc_offset = 0xE0`) is at `0x2489de0`, function
> pointer `0x1578d70`, size `0x17B` (379 bytes) — matching the anchor's devirtualized-call target exactly.

### 6. Generate Function Signature for UTIL_PlayerSlotToPlayerController

**ALWAYS** Use SKILL `/generate-signature-for-function` with `addr=<UTIL_PlayerSlotToPlayerController_func_addr>`.

### 7. Generate Function Signature for FireTargets

**ALWAYS** Use SKILL `/generate-signature-for-function` with `addr=<FireTargets_func_addr>`.

### 8. Generate Function Signature for CCSPlayer_ItemServices_RemoveWeapons

**ALWAYS** Use SKILL `/generate-signature-for-function` with `addr=<RemoveWeapons_func_addr>`.

### 9. Write UTIL_PlayerSlotToPlayerController as YAML

**ALWAYS** Use SKILL `/write-func-as-yaml`.

Required parameters:
- `func_name`: `UTIL_PlayerSlotToPlayerController`
- `func_addr`: `<UTIL_PlayerSlotToPlayerController_func_addr>`
- `func_sig`: The validated signature from step 6

### 10. Write FireTargets as YAML

**ALWAYS** Use SKILL `/write-func-as-yaml`.

Required parameters:
- `func_name`: `FireTargets`
- `func_addr`: `<FireTargets_func_addr>`
- `func_sig`: The validated signature from step 7

### 11. Write CCSPlayer_ItemServices_RemoveWeapons as YAML

**ALWAYS** Use SKILL `/write-vfunc-as-yaml`.

Required parameters:
- `func_name`: `CCSPlayer_ItemServices_RemoveWeapons`
- `func_addr`: `<RemoveWeapons_func_addr>`
- `func_sig`: The validated signature from step 8

VTable parameters:
- `vtable_name`: `CCSPlayer_ItemServices`
- `vfunc_offset`: `0xE0` (`28 * 8`)
- `vfunc_index`: `28`

## Function Characteristics

### UTIL_PlayerSlotToPlayerController

- **Purpose**: Converts a raw engine player-slot index into the corresponding `CCSPlayerController *`.
- **Binary**: `server.dll` / `libserver.so`
- **Parameters**: `(int playerSlot)` — no `this` pointer, a free function.
- **Return value**: `CCSPlayerController *`, or `0`/`nullptr` if the slot is out of range.

### FireTargets

- **Purpose**: Classic Source-engine I/O-firing helper — finds all entities matching a target name and fires an
  input on each (used for `logic_relay`/trigger-output-style dispatch, and reused here to broadcast the
  `"game_playerleave"` game event target on client disconnect).
- **Binary**: `server.dll` / `libserver.so`
- **Parameters**: `(const char *pszTargetName, <activator handle>, <caller handle>, int useType, float value)` —
  no `this` pointer, a free function.
- **Return value**: `void`

### CCSPlayer_ItemServices_RemoveWeapons

- **Purpose**: Strips all weapons from the player's inventory (used on disconnect, death, and similar full-reset
  paths).
- **Binary**: `server.dll` / `libserver.so`
- **Parameters**: `(this, bool <drop-vs-silently-remove or similar>)`
- **Return value**: not consumed in a way that suggests a meaningful return type (effectively `void`)
- **VTable**: `CCSPlayer_ItemServices`, slot **28** (`vfunc_offset = 0xE0`) on the Linux 14168 reference build.

## Discovery Strategy

1. Reuse the already-resolved `CMultiplayRules_ClientDisconnected` anchor, which is short enough (~110 bytes) that
   all three targets appear as its only three non-trivial calls, in a fixed logical order: slot→controller lookup,
   then event broadcast, then inventory teardown.
2. Identify `UTIL_PlayerSlotToPlayerController` by its raw-integer-slot argument, bounds check against a
   max-player global, and handle-table resolve.
3. Identify `FireTargets` by its literal `"game_playerleave"` string argument at the call site, or independently
   by locating its distinctive embedded format strings `"Firing: (%s)\n"` / `"[%03d] Found: %s, firing (%s)\n"`
   directly via `find_regex` — either path converges on the same function, which is a strong cross-check.
4. Identify `CCSPlayer_ItemServices_RemoveWeapons` two ways simultaneously: (a) the anchor's devirtualized-looking
   call through the item-services vtable at a fixed offset (`224` = slot 28 × 8), and (b) an independent RTTI walk
   of `CCSPlayer_ItemServices`'s own vtable reading slot 28 directly — both must agree.

This is robust because:
- The anchor is small and has an unusually clean, fixed 3-call structure, making positional identification
  reliable even without argument-shape analysis.
- `FireTargets` has a second, fully independent discovery path via its embedded debug strings, so this skill does
  not depend solely on the anchor surviving future recompiles.
- `RemoveWeapons`'s vtable slot is corroborated two independent ways (anchor call-site offset **and** direct RTTI
  vtable walk), which is the strongest possible confirmation for a vtable-slot-based ground truth.

## Output YAML Format

The output YAML filenames depend on the platform:
- `server.dll` -> `UTIL_PlayerSlotToPlayerController.windows.yaml`, `FireTargets.windows.yaml`,
  `CCSPlayer_ItemServices_RemoveWeapons.windows.yaml`
- `libserver.so` -> `UTIL_PlayerSlotToPlayerController.linux.yaml`, `FireTargets.linux.yaml`,
  `CCSPlayer_ItemServices_RemoveWeapons.linux.yaml`

`UTIL_PlayerSlotToPlayerController.{platform}.yaml` fields: `func_name`, `func_sig`, `func_va`, `func_rva`, `func_size`.

`FireTargets.{platform}.yaml` fields: `func_name`, `func_sig`, `func_va`, `func_rva`, `func_size`.

`CCSPlayer_ItemServices_RemoveWeapons.{platform}.yaml` fields: `func_name`, `func_va`, `func_rva`, `func_size`,
`func_sig`, `vtable_name`, `vfunc_offset`, `vfunc_index`.
