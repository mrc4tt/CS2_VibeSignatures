---
name: find-CCSPlayerController_Respawn
description: |
  Find and identify the CCSPlayerController_Respawn virtual function in CS2 binary using IDA Pro MCP. Use this
  skill when reverse engineering CS2 server.dll or libserver.so to locate the Respawn vfunc slot by RTTI-walking
  the CCSPlayerController vtable and confirming the candidate's decompiled body performs a full controller-state
  reset (networked flags, per-round fields, comeback/damage-info bookkeeping) rather than any other lifecycle vfunc.
  Trigger: CCSPlayerController_Respawn
disable-model-invocation: true
---

# Find CCSPlayerController_Respawn

Locate `CCSPlayerController_Respawn` vfunc in CS2 `server.dll` or `libserver.so` using IDA Pro MCP tools.

## Method

### 1. Load CCSPlayerController VTable

**ALWAYS** Use SKILL `/get-vtable-address` with `class_name=CCSPlayerController` to RTTI-walk the primary vtable.

```text
mcp__ida-pro-mcp__find_regex pattern="19CCSPlayerController"
mcp__ida-pro-mcp__xrefs_to addrs="<name_string_addr>"      # hit - 8 = typeinfo
mcp__ida-pro-mcp__xrefs_to addrs="<typeinfo_addr>"          # hit - 8 = vtable candidate, keep offset_to_top==0
```

Search for the mangled typeinfo name string `19CCSPlayerController` (**not** the many longer
`N19CCSPlayerController...NetworkVar_...EE` template-instantiation strings that also contain the substring — those
are unrelated `CNetworkVarBase`/`CNetworkHandle` instantiations, not the class's own RTTI name). The class's own
typeinfo name is the standalone `<len>ClassName` string with no further `N...E` nesting after it.

> Linux 14168 reference: name string `19CCSPlayerController` at `0x81ef30`, typeinfo at `0x2487778`, primary
> vtable at `0x24885b0` (`offset_to_top == 0`).

### 2. Read VTable Slot 272

Since `CCSPlayerController` inherits `Respawn` from `CBasePlayerController` at a fixed, ABI-stable slot index
(Itanium single-inheritance derived-class vtables preserve base-class slot ordering), the slot number is portable
across builds even though the function's own address is not. Read the function pointer directly:

```text
mcp__ida-pro-mcp__get_int addr="<vtable_va> + 0x10 + 272*8" ty="u64"
```

> Linux 14168 reference: `vtable_va = 0x24885b0`, slot 272 address `0x24885b0 + 0x10 + 272*8 = 0x2488e40`,
> function pointer `0x14e5870`, size `0x2A3` (675 bytes).

### 3. Confirm the Candidate

Decompile the resolved function and confirm it matches `Respawn()`-shaped semantics:

```text
mcp__ida-pro-mcp__decompile addr="<slot_272_func_addr>"
```

Identification rules:
1. Single argument (`this` only) — `Respawn()` takes no parameters.
2. The body is a broad member-state reset: dozens of direct byte/dword/qword writes to `this`-relative offsets
   spread across a wide range (hundreds of bytes apart), zeroing/defaulting networked per-life fields.
3. Near the top, it clears a "pending state change" flag pattern via the class's generic networked-bool-setter
   helper (`this+2993` bool cleared through a `CNetworkTransmitComponent::StateChanged`-style call, matching the
   pattern seen throughout this class's other setters) before falling into the bulk reset.
4. It reads a global respawn/spawn-protection time constant (`off_261F328`-style float array) and clamps a
   per-controller timestamp field (`this+1336`) against it — a spawn-protection-timer initialization step
   distinctive to `Respawn`.
5. As a sanity cross-check, confirm slot 271 and slot 273 (the immediate neighbors) decompile to visibly smaller,
   differently-shaped functions (e.g. simple accessors) — `Respawn` should stand out as one of the larger,
   broad-reset functions in its immediate slot neighborhood.

If the candidate does not match, **STOP** and report to user.

### 4. Generate Function Signature

**ALWAYS** Use SKILL `/generate-signature-for-function` with `addr=<Respawn_func_addr>` to generate a robust and
unique `func_sig`.

### 5. Write IDA Analysis Output as YAML

**ALWAYS** Use SKILL `/write-vfunc-as-yaml` to write the analysis results.

Required parameters:
- `func_name`: `CCSPlayerController_Respawn`
- `func_addr`: `<Respawn_func_addr>`
- `func_sig`: The validated signature from step 4

VTable parameters:
- `vtable_name`: `CCSPlayerController`
- `vfunc_offset`: `0x880` (`272 * 8`)
- `vfunc_index`: `272`

## Function Characteristics

- **Purpose**: Resets a `CCSPlayerController`'s per-life networked state on respawn — clears pending-damage,
  comeback, and per-round bookkeeping fields and re-arms the spawn-protection timer.
- **Binary**: `server.dll` / `libserver.so`
- **Parameters**: `(this)` only
- **Return value**: not consumed by callers in the decompiled body observed (effectively `void`)
- **VTable**: `CCSPlayerController`, slot **272** (`vfunc_offset = 0x880`) on the Linux 14168 reference build,
  inherited-slot position (`INHERIT_VFUNCS` relation to `CBasePlayerController_Respawn`).

## Discovery Strategy

1. RTTI-walk `CCSPlayerController`'s primary vtable via its own (non-template) typeinfo name string.
2. Read slot 272 directly — the slot index is stable across builds because it derives from `CBasePlayerController`
   base-class layout, which the Itanium ABI guarantees stays contiguous in the derived class's vtable regardless
   of how many further overrides `CCSPlayerController` itself adds afterward.
3. Confirm the resolved function's decompiled body matches the broad per-life state-reset + spawn-protection-timer
   pattern unique to `Respawn`.

This is robust because:
- The vtable slot index is derived from ABI-guaranteed base-class layout, not from a fragile byte offset or string
  xref, so it survives most recompiles as long as `CBasePlayerController`'s own vfunc ordering is unchanged.
- The broad multi-field reset + spawn-protection-timer-clamp shape is distinctive enough to disambiguate `Respawn`
  from neighboring accessor-style vfuncs even without a known reference sig.

## Output YAML Format

The output YAML filename depends on the platform:
- `server.dll` -> `CCSPlayerController_Respawn.windows.yaml`
- `libserver.so` -> `CCSPlayerController_Respawn.linux.yaml`

Fields: `func_name`, `func_va`, `func_rva`, `func_size`, `func_sig`, `vtable_name`, `vfunc_offset`, `vfunc_index`.
