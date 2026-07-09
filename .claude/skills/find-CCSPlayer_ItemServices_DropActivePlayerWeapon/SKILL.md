---
name: find-CCSPlayer_ItemServices_DropActivePlayerWeapon
description: |
  Find and identify the CCSPlayer_ItemServices_DropActivePlayerWeapon virtual function in CS2 binary using IDA Pro
  MCP. Use this skill when reverse engineering CS2 server.dll or libserver.so to locate the "drop the currently
  held weapon" vfunc by RTTI-walking the CCSPlayer_ItemServices vtable and confirming the candidate reads the
  player's active weapon and forwards it, with a computed toss velocity, into the weapon's own drop vfunc.
  Trigger: CCSPlayer_ItemServices_DropActivePlayerWeapon
disable-model-invocation: true
---

# Find CCSPlayer_ItemServices_DropActivePlayerWeapon

Locate `CCSPlayer_ItemServices_DropActivePlayerWeapon` vfunc in CS2 `server.dll` or `libserver.so` using IDA Pro
MCP tools.

## Method

### 1. Load CCSPlayer_ItemServices VTable

**ALWAYS** Use SKILL `/get-vtable-address` with `class_name=CCSPlayer_ItemServices`.

```text
mcp__ida-pro-mcp__find_regex pattern="22CCSPlayer_ItemServices"
mcp__ida-pro-mcp__xrefs_to addrs="<name_string_addr>"      # hit - 8 = typeinfo
mcp__ida-pro-mcp__xrefs_to addrs="<typeinfo_addr>"          # hit - 8 = vtable candidate, keep offset_to_top==0
```

> Linux 14168 reference: name string `22CCSPlayer_ItemServices` at `0x8219d0`, typeinfo at `0x2489888`, primary
> vtable at `0x2489cf0`.

### 2. Read VTable Slot 27

```text
mcp__ida-pro-mcp__get_int addr="<vtable_va> + 0x10 + 27*8" ty="u64"
```

> Linux 14168 reference: slot 27 (`vfunc_offset = 0xD8`) is at `0x2489dd8`, function pointer `0x1578c30`, size
> `0x131` (305 bytes).

### 3. Confirm the Candidate

Decompile the resolved function:

```text
mcp__ida-pro-mcp__decompile addr="<slot_27_func_addr>"
```

Identification rules — `DropActivePlayerWeapon` takes no weapon/name argument beyond `this` (plus a small number
of scalar/vector-ish trailing parameters used only to compute the toss impulse), and its body:

1. First calls a small no-op-looking stub (`nullsub_1463`-style — a hook/telemetry point present on several
   `ItemServices` mutators, safe to ignore for identification purposes).
2. Fetches the owning pawn via the lazy-accessor pattern (`if (!v) { nullsub_1480(this); v = *(this+56); }`) seen
   throughout this class.
3. Reads the pawn's *active weapon* pointer via the pawn's `weaponServices+3344` member and an internal
   `GetActiveWeapon`-style helper (`sub_17604F0`-equivalent on the reference build) — **not** a weapon passed in
   as an argument. This "no explicit weapon argument, reads the active one internally" shape is what
   distinguishes it from a generic `DropWeapon(pWeapon)` overload.
4. If an active weapon was found, checks the weapon's "can be manually dropped" flag (a vfunc call at offset
   `232`, i.e. slot 29 of the *weapon's own* vtable) and, if allowed, computes a toss velocity/angle from the
   trailing scalar/vector parameters and calls the weapon's own drop vfunc (a second vcall at offset `232` — same
   slot, different receiver — passing the computed velocity struct).
5. If the "can be manually dropped" check fails, instead calls the weapon's drop vfunc with a null velocity
   pointer (an unconditional/forced drop with no toss impulse).

> Linux 14168 reference: the two calls both target `*(_QWORD*)v7 + 232` (offset 0xE8, i.e. slot **29** of the
> *weapon's* own vtable, a distinct class from `CCSPlayer_ItemServices` — do not confuse this internal vcall
> offset with `DropActivePlayerWeapon`'s own slot 27 in `CCSPlayer_ItemServices`).

If the candidate does not match, **STOP** and report to user.

### 4. Generate Function Signature

**ALWAYS** Use SKILL `/generate-signature-for-function` with `addr=<DropActivePlayerWeapon_func_addr>` to generate
a robust and unique `func_sig`.

### 5. Write IDA Analysis Output as YAML

**ALWAYS** Use SKILL `/write-vfunc-as-yaml` to write the analysis results.

Required parameters:
- `func_name`: `CCSPlayer_ItemServices_DropActivePlayerWeapon`
- `func_addr`: `<DropActivePlayerWeapon_func_addr>`
- `func_sig`: The validated signature from step 4

VTable parameters:
- `vtable_name`: `CCSPlayer_ItemServices`
- `vfunc_offset`: `0xD8` (`27 * 8`)
- `vfunc_index`: `27`

## Function Characteristics

- **Purpose**: Drops the player's currently active/held weapon, computing a toss velocity for it if the weapon
  permits manual drops, or force-dropping it with no toss impulse otherwise.
- **Binary**: `server.dll` / `libserver.so`
- **Parameters**: `(this, <toss-velocity/angle-related scalars>)` — no explicit weapon pointer; the active weapon
  is looked up internally.
- **Return value**: not consumed in a way that suggests a meaningful return type (effectively `void`)
- **VTable**: `CCSPlayer_ItemServices`, slot **27** (`vfunc_offset = 0xD8`) on the Linux 14168 reference build.

## Discovery Strategy

1. RTTI-walk `CCSPlayer_ItemServices`'s primary vtable via its typeinfo name string `22CCSPlayer_ItemServices`.
2. Read slot 27 directly (per the config's `FUNC_VTABLE_RELATIONS` mapping, ground truth for this build).
3. Confirm by decompiled shape: no explicit weapon argument (reads the active weapon internally), a
   can-manually-drop gate, and two mutually-exclusive calls into the weapon's own drop vfunc (with vs. without a
   computed toss velocity).

This is robust because:
- The vtable slot index is what CSS's runtime hook actually targets, so validating directly against slot 27 (per
  provided ground truth) rather than re-deriving it from an unrelated anchor keeps this skill both simple and
  authoritative.
- "No weapon argument, active weapon read internally, two drop-vfunc call sites gated by a manual-drop flag" is
  distinctive enough to disambiguate from sibling `ItemServices` mutators (e.g. `RemoveWeapons`, which iterates
  *all* weapons rather than just the active one — see the sibling skill
  `find-UTIL_PlayerSlotToPlayerController-AND-FireTargets-AND-CCSPlayer_ItemServices_RemoveWeapons`).

## Output YAML Format

The output YAML filename depends on the platform:
- `server.dll` -> `CCSPlayer_ItemServices_DropActivePlayerWeapon.windows.yaml`
- `libserver.so` -> `CCSPlayer_ItemServices_DropActivePlayerWeapon.linux.yaml`

Fields: `func_name`, `func_va`, `func_rva`, `func_size`, `func_sig`, `vtable_name`, `vfunc_offset`, `vfunc_index`.
