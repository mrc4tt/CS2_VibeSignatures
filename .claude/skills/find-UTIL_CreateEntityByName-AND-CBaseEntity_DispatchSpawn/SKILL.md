---
name: find-UTIL_CreateEntityByName-AND-CBaseEntity_DispatchSpawn
description: |
  Find and identify the UTIL_CreateEntityByName free function and the CBaseEntity_DispatchSpawn free function in
  the CS2 server binary using IDA Pro MCP. Use this skill when reverse engineering server.dll or libserver.so to
  locate the entity-factory helper that allocates a new entity by classname, and the spawn-dispatch helper that
  invokes an already-allocated entity's Spawn() and performs engine-side post-spawn bookkeeping. Both are plain
  (non-virtual) C++ free functions, cross-validated against each other because every caller of one also calls
  the other in the classic "create, then spawn" entity-creation idiom.
  Trigger: UTIL_CreateEntityByName, CBaseEntity_DispatchSpawn
disable-model-invocation: true
---

# Find UTIL_CreateEntityByName and CBaseEntity_DispatchSpawn

Locate `UTIL_CreateEntityByName` and `CBaseEntity_DispatchSpawn` in CS2 `server.dll` / `libserver.so` using IDA
Pro MCP tools.

## Method

### 1. Locate CBaseEntity_DispatchSpawn via a fixed-heavy byte pattern

`DispatchSpawn` is a free function, not a vtable slot, so there is no RTTI/vtable path to it. Instead scan the
whole image directly for its highly-distinctive prologue, which starts with a `test rdi,rdi; jz` null-check
**before** the `push rbp` (the compiler hoisted the `if (!pEntity) return;` guard ahead of the frame setup):

```text
mcp__ida-pro-mcp__data find_bytes pattern="48 85 FF 74 ?? 55 48 89 E5 41 55 41 54 49 89 FC"
```

This is expected to return exactly **one** hit. Before trusting it, confirm the match address is IDA's actual
function head (not a mid-function byte run) — the `test rdi,rdi` instruction IS the entry point here, the
`push rbp`/frame-setup only begins 5 bytes later:

```text
mcp__ida-pro-mcp__idalib get_func_boundaries addr="<hit_addr>"
```

`start_ea` must equal `<hit_addr>` exactly.

> Linux 14168 reference: unique hit at `0x1785b00`, and `idaapi.get_func(0x1785b00).start_ea == 0x1785b00` —
> confirms the function head is at the `test rdi,rdi` instruction, matching the reference sig's first byte.

### 2. Confirm CBaseEntity_DispatchSpawn's Body

Decompile the hit:

```text
mcp__ida-pro-mcp__decompile addr="<hit_addr>"
```

Confirm the shape: `(CBaseEntity *pEntity, KeyValues *pKeyValues)`. If `!pEntity`, return immediately. If
`!pKeyValues`, allocate a default `KeyValues` and populate a single `"classname"` key from the entity's own
class-info classname string. Finally call a two-argument helper `(g_pEntitySystemSingleton, pEntity,
pKeyValues)`-shaped function that performs the actual `Spawn()` dispatch plus `CEntitySystem`-side bookkeeping
(this inner call is where the entity's virtual `Spawn()` actually gets invoked, several frames deeper — do not
expect to see a direct vtable call in `DispatchSpawn` itself).

### 3. Locate UTIL_CreateEntityByName via DispatchSpawn's Callers

`UTIL_CreateEntityByName` and `DispatchSpawn` are always called together at each of `DispatchSpawn`'s call
sites (`pEntity = UTIL_CreateEntityByName(classname, ...); DispatchSpawn(pEntity, NULL);`), so find
`DispatchSpawn`'s callers and look for a small 2-argument wrapper each of them also calls:

```text
mcp__ida-pro-mcp__idalib xrefs_to addrs="<DispatchSpawn_addr>"
```

For each caller, decompile it and find the small (~0x2e-byte) thin-wrapper callee taking `(const char
*pClassname, int iForceEdictIndex)` that forwards to a much larger, many-parameter entity-factory function
(`(g_pEntitySystemSingleton, -1, pClassname, 0, iForceEdictIndex, -1, 0)`-shaped). That thin wrapper is
`UTIL_CreateEntityByName`.

**Cross-check** (do this — it's a strong independent confirmation): resolve `UTIL_CreateEntityByName`'s own
caller set via `func_profile`/`xrefs_to` and confirm it is the **exact same set** of functions that call
`DispatchSpawn`. An accidental match of all N callers between two unrelated functions is extremely unlikely.

> Linux 14168 reference: `DispatchSpawn` (`0x1785b00`) has 4 callers: `0xc9d8a0`, `0xd08b70`, `0x13caf00`,
> `0x152c560` (bot/chicken/prop spawning helpers). `UTIL_CreateEntityByName` candidate `0x16a9140` has the
> **identical** 4 callers. One of them (`0xc9d8a0`, the "chicken" NPC spawner) calls both back-to-back:
> `v21 = sub_16A9140("chicken", 0xFFFFFFFF); sub_D2FAB0(v21, ...); sub_1785B00(v21, 0);` — a `CreateEntityByName`
> → (position/setup) → `DispatchSpawn` chain, confirming both identifications simultaneously.

### 4. Generate Function Signatures

**ALWAYS** Use SKILL `/generate-signature-for-function` with `addr=<DispatchSpawn_addr>` to generate a robust and
unique `func_sig` for `CBaseEntity_DispatchSpawn`.

**ALWAYS** Use SKILL `/generate-signature-for-function` with `addr=<UTIL_CreateEntityByName_addr>` to generate a
robust and unique `func_sig` for `UTIL_CreateEntityByName`.

### 5. Write IDA Analysis Output as YAML

**ALWAYS** Use SKILL `/write-func-as-yaml` twice, once for each symbol:

- `func_name`: `CBaseEntity_DispatchSpawn`, `func_addr`: `<DispatchSpawn_addr>`, `func_sig`: from step 4.
- `func_name`: `UTIL_CreateEntityByName`, `func_addr`: `<UTIL_CreateEntityByName_addr>`, `func_sig`: from step 4.

## Function Characteristics

### CBaseEntity_DispatchSpawn

- **Purpose**: Given an already-allocated `CBaseEntity`, dispatches its `Spawn()` virtual call and performs
  engine-side post-spawn bookkeeping (registering the entity with the entity system / notifying listeners). If
  no `KeyValues` block is supplied, synthesizes a minimal one containing just the `"classname"` key.
- **Binary**: `server.dll` / `libserver.so`
- **Parameters**: `(CBaseEntity *pEntity, KeyValues *pKeyValues)` — `pKeyValues` may be `nullptr`.
- **Return value**: unused (always effectively `0`/`void`).
- **Not virtual** — a plain free/static function, found by byte pattern rather than RTTI/vtable walk.

### UTIL_CreateEntityByName

- **Purpose**: Allocates a new entity instance of the given classname via the engine's entity-factory system,
  without spawning it (spawning is a separate, subsequent `DispatchSpawn` call made by the caller).
- **Binary**: `server.dll` / `libserver.so`
- **Parameters**: `(const char *pClassname, int iForceEdictIndex = -1)`.
- **Return value**: the newly-created `CBaseEntity*` (or `nullptr` on failure).
- **Not virtual** — a thin free-function wrapper (~0x2e bytes) around a much larger internal factory call; not
  independently useful without also resolving `DispatchSpawn` since gameplay code always pairs them.

## Discovery Strategy

1. `DispatchSpawn` has an unmistakable, highly fixed-byte-heavy prologue (`test rdi,rdi; jz +N` immediately
   followed by full push-heavy frame setup) that is unique across the entire image — a single `find_bytes` scan
   resolves it directly with no RTTI dependency, and the match address is confirmed to be the true function head.
2. `UTIL_CreateEntityByName` has no distinctive byte pattern of its own (it's a generic thin wrapper), so instead
   it is located **relationally**: every caller of `DispatchSpawn` also calls it, and the reverse holds too (same
   caller set both ways). This caller-set-identity check is robust because it does not depend on either
   function's absolute address, only on the call-graph shape, which is stable across recompiles.
3. Both signatures are re-derived fresh from whatever addresses are found on the currently-loaded binary, so the
   recipe self-heals across game updates even if the exact bytes/addresses shift.

## Output YAML Format

The output YAML filenames depend on the platform:
- `server.dll` -> `CBaseEntity_DispatchSpawn.windows.yaml`, `UTIL_CreateEntityByName.windows.yaml`
- `libserver.so` -> `CBaseEntity_DispatchSpawn.linux.yaml`, `UTIL_CreateEntityByName.linux.yaml`

Fields (both files): `func_name`, `func_va`, `func_rva`, `func_size`, `func_sig`.
