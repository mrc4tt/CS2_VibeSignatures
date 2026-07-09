---
name: find-CCSPlayer_WeaponServices_EquipWeapon-AND-CCSPlayer_WeaponServices_CanUse
description: |
  Find and identify the CCSPlayer_WeaponServices_EquipWeapon function and the CCSPlayer_WeaponServices_CanUse
  virtual function in CS2 binary using IDA Pro MCP. Use this skill when reverse engineering CS2 server.dll or
  libserver.so to locate the weapon-equip helper and the "is this weapon usable right now" vfunc by RTTI-walking
  the CCSPlayer_WeaponServices vtable and confirming each candidate's decompiled body against the known
  CCSPlayer_WeaponServices_PickupItem anchor's callee shapes.
  Trigger: CCSPlayer_WeaponServices_EquipWeapon, CCSPlayer_WeaponServices_CanUse
disable-model-invocation: true
---

# Find CCSPlayer_WeaponServices_EquipWeapon and CCSPlayer_WeaponServices_CanUse

Locate `CCSPlayer_WeaponServices_EquipWeapon` and `CCSPlayer_WeaponServices_CanUse` in CS2 `server.dll` or
`libserver.so` using IDA Pro MCP tools.

## Method

### 1. Load CCSPlayer_WeaponServices_PickupItem from YAML

**ALWAYS** Use SKILL `/get-func-from-yaml` with `func_name=CCSPlayer_WeaponServices_PickupItem`.

If the skill returns an error, **STOP** and report to user (this skill's anchor must already be resolved).

Otherwise, extract:
- `func_va` of `CCSPlayer_WeaponServices_PickupItem`

### 2. Load CCSPlayer_WeaponServices VTable

**ALWAYS** Use SKILL `/get-vtable-address` with `class_name=CCSPlayer_WeaponServices` to RTTI-walk the primary
vtable (typeinfo name string `"24CCSPlayer_WeaponServices"` -> typeinfo -> primary vtable where
`offset_to_top == 0`).

```text
mcp__ida-pro-mcp__find_regex pattern="24CCSPlayer_WeaponServices"
mcp__ida-pro-mcp__xrefs_to addrs="<name_string_addr>"      # hit - 8 = typeinfo
mcp__ida-pro-mcp__xrefs_to addrs="<typeinfo_addr>"          # hit - 8 = vtable candidate, keep offset_to_top==0
```

> Linux 14168 reference: name string `24CCSPlayer_WeaponServices` at `0x824140`, typeinfo at `0x248bf00`, primary
> vtable at `0x248c798`. `PickupItem` (`CCSPlayer_WeaponServices_PickupItem`, resolved separately) sits at
> `0x1597b70`, vtable slot **30** (`vfunc_offset = 0xf0`) — this cross-checks the vtable base, since PickupItem's
> own YAML independently records `vfunc_offset: 0xf0`.

### 3. Identify CCSPlayer_WeaponServices_CanUse

Decompile vtable slots below `PickupItem`'s own slot (slot 30 on the 14168 build) and look for a two-argument
`(this, CBasePlayerWeapon *pWeapon)` function whose body:

```text
mcp__ida-pro-mcp__decompile addr="<vtable_slot_N_func_addr>"
```

- Dynamic-casts the argument to `CCSWeaponBase` via the RTTI dynamic-cast thunk (`typeinfo for'CBasePlayerWeapon`
  -> `typeinfo for'CCSWeaponBase`).
- Reads a "restrict to primary/melee-only" flag off `this+168` and bails early if set.
- Reads the owning pawn via `this+56` (the lazy pawn-accessor pattern `if (!v) { nullsub_1480(this); v = *(this+56); }`
  seen throughout this class) and checks that pawn's own vtable slot at offset `1336` for a buy-time/ammo gate.
- Walks the pawn's ammo-array (`this+72`/`this+80`, a `(count, ptr)` pair) checking each ammo type against a
  reserved-slot hash table (`qword_26784E0`-style bucket lookup) — this is the "does the player already have a
  weapon that uses the same ammo/slot" check.
- Returns a `bool` (0/1), never touches any output parameter.

The candidate satisfying all of the above is `CCSPlayer_WeaponServices_CanUse`.

> Linux 14168 reference: `CanUse` is vtable slot **28** (`vfunc_offset = 0xE0`), function at `0x1582aa0`, size
> `0x3AF` (943 bytes). Its prologue is distinctive and unique across the whole binary:
> `55 48 8D 15 ? ? ? ? 48 89 E5 41 55 41 54 49 89 FC 53 48 89 F3 48 83 EC ? 48 8B 07 48 8B 80` — the
> `lea rdx, <RIP-rel>` right after `push rbp` loads a devirtualization-check constant (`sub_1580DA0`, itself another
> `CCSPlayer_WeaponServices` vfunc) that the function compares its own resolved vtable slot 33 read against, and
> the trailing `mov rax,[rdi]; mov rax,[rax+0x108]` (264 decimal) reads slot 33 of `this`'s own vtable — this
   nested self-vtable-offset-264 read is a strong independent fingerprint, unique to this function.

### 4. Identify CCSPlayer_WeaponServices_EquipWeapon

`EquipWeapon` is **not** a virtual function on this class — it is a plain member function reachable from
`PickupItem`'s decompiled body (and also as the immediate next vtable-adjacent function on the 14168 build,
though that adjacency is not guaranteed across builds — always confirm by decompiled shape, not position):

```text
mcp__ida-pro-mcp__decompile addr="<PickupItem_func_addr>"
```

Look for the callee taking `(this, CBasePlayerWeapon *pWeapon, <angles-ish int64>, <velocity/orientation vec ptr>)`
whose body:

- Early-outs if the weapon pointer is null or the weapon's "no swap" flag (`weapon+392`, bit `0x2`) is set.
- Reads the *current* active weapon via the same `GetActiveWeapon(this)` helper used by `CanUse`'s sibling
  functions, then calls the new weapon's own vtable slot at offset `2576` (an internal "set owner/holster old"
  step) followed by a direct (non-virtual) helper `(this, pWeapon)` that performs the actual services-level swap.
- If the newly-equipped weapon **is** the weapon that was already active, calls a small `(this, 0, 0)` helper
  (a "no-op re-equip" short-circuit).
- Dynamic-casts the weapon to `CCSWeaponBase` and, depending on a buy-time/restrict-to-slot config check, sends a
  networked state-change broadcast for a `bool` at offset `4228` on the weapon.

> Linux 14168 reference: `EquipWeapon` is at `0x15939b0`, size `0x2FB` (763 bytes), immediately following `CanUse`
> at vtable slot 29 on this build (`this` class is not overridden further beyond slot 30, `PickupItem`, on this
> particular layout) — but re-derive it from `PickupItem`'s callee, not from slot position, since ordering is not
> an ABI guarantee.

### 5. Generate Function Signature for CCSPlayer_WeaponServices_CanUse

**ALWAYS** Use SKILL `/generate-signature-for-function` with `addr=<CanUse_func_addr>` to generate a robust and
unique `vfunc_sig`.

### 6. Generate Function Signature for CCSPlayer_WeaponServices_EquipWeapon

**ALWAYS** Use SKILL `/generate-signature-for-function` with `addr=<EquipWeapon_func_addr>` to generate a robust
and unique `func_sig`.

### 7. Write CCSPlayer_WeaponServices_EquipWeapon as YAML

**ALWAYS** Use SKILL `/write-func-as-yaml`.

Required parameters:
- `func_name`: `CCSPlayer_WeaponServices_EquipWeapon`
- `func_addr`: `<EquipWeapon_func_addr>`
- `func_sig`: The validated signature from step 6

### 8. Write CCSPlayer_WeaponServices_CanUse as YAML

**ALWAYS** Use SKILL `/write-vfunc-as-yaml`.

Required parameters:
- `func_name`: `CCSPlayer_WeaponServices_CanUse`
- `func_addr`: `<CanUse_func_addr>`
- `vfunc_sig`: The validated signature from step 5

VTable parameters:
- `vtable_name`: `CCSPlayer_WeaponServices`
- `vfunc_offset`: `0xE0` (slot 28, on the Linux 14168 reference build)
- `vfunc_index`: `28`

## Function Characteristics

### CCSPlayer_WeaponServices_CanUse

- **Purpose**: Determines whether the player can currently pick up / use a given weapon — checks ammo-type/slot
  conflicts against already-carried weapons and buy-time restrictions.
- **Binary**: `server.dll` / `libserver.so`
- **Parameters**: `(this, CBasePlayerWeapon *pWeapon)`
- **Return value**: `bool` — whether the weapon can be used/picked up
- **VTable**: `CCSPlayer_WeaponServices`, slot 28 (`vfunc_offset = 0xE0`) on the Linux 14168 reference build.

### CCSPlayer_WeaponServices_EquipWeapon

- **Purpose**: Performs the actual weapon-services-level swap of the player's active weapon to the given weapon
  (holsters the old one, sets the new one active, networks the state change).
- **Binary**: `server.dll` / `libserver.so`
- **Parameters**: `(this, CBasePlayerWeapon *pWeapon, <angle/velocity-ish args used for holster animation>)`
- **Return value**: `void`
- **Not virtual** — resolved via callee analysis of `PickupItem`, not via a vtable slot.

## Discovery Strategy

1. Reuse the already-resolved `CCSPlayer_WeaponServices_PickupItem` anchor (own vtable slot 30) as a scope anchor
   for the `CCSPlayer_WeaponServices` class and as the direct caller of `EquipWeapon`.
2. RTTI-walk `CCSPlayer_WeaponServices`'s primary vtable (typeinfo name string `24CCSPlayer_WeaponServices`) to
   enumerate virtual-function candidates for `CanUse`.
3. Identify `CanUse` by its distinctive two-argument shape, RTTI dynamic-cast to `CCSWeaponBase`, and
   ammo/slot-conflict hash-bucket walk — confirmed independently by an exact byte-for-byte match against a known
   reference prologue.
4. Identify `EquipWeapon` as `PickupItem`'s callee that performs the holster/swap/broadcast sequence — since it is
   not virtual, position-in-vtable is not used for identification, only decompiled shape.

This is robust because:
- `CanUse`'s ammo/slot-conflict walk and the self-vtable-slot-33 devirtualization check are unusual enough that no
  other function in the vtable matches the shape.
- Anchoring `EquipWeapon`'s discovery on `PickupItem` (rather than raw vtable position) survives vtable-layout
  churn, since `EquipWeapon` is a plain function and its position in `.text` is not ABI-constrained.

## Output YAML Format

The output YAML filenames depend on the platform:
- `server.dll` -> `CCSPlayer_WeaponServices_EquipWeapon.windows.yaml`, `CCSPlayer_WeaponServices_CanUse.windows.yaml`
- `libserver.so` -> `CCSPlayer_WeaponServices_EquipWeapon.linux.yaml`, `CCSPlayer_WeaponServices_CanUse.linux.yaml`

`CCSPlayer_WeaponServices_EquipWeapon.{platform}.yaml` fields: `func_name`, `func_sig`, `func_va`, `func_rva`, `func_size`.

`CCSPlayer_WeaponServices_CanUse.{platform}.yaml` fields: `func_name`, `vfunc_sig`, `vfunc_offset`, `vfunc_index`, `vtable_name`.
