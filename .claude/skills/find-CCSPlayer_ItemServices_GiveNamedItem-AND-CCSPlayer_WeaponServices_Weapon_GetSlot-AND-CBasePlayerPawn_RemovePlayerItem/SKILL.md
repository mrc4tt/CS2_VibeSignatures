---
name: find-CCSPlayer_ItemServices_GiveNamedItem-AND-CCSPlayer_WeaponServices_Weapon_GetSlot-AND-CBasePlayerPawn_RemovePlayerItem
description: |
  Find and identify the CCSPlayer_ItemServices_GiveNamedItem virtual function, the
  CCSPlayer_WeaponServices_Weapon_GetSlot helper, and the CBasePlayerPawn_RemovePlayerItem helper in CS2 binary
  using IDA Pro MCP. Use this skill when reverse engineering CS2 server.dll or libserver.so to locate GiveNamedItem
  by RTTI-walking the CCSPlayer_ItemServices vtable, then to locate the other two by decompiling the already-known
  CCSPlayer_ItemServices_GiveDefaultItems anchor and matching its callees' argument shapes and inventory-slot
  bookkeeping semantics.
  Trigger: CCSPlayer_ItemServices_GiveNamedItem, CCSPlayer_WeaponServices_Weapon_GetSlot, CBasePlayerPawn_RemovePlayerItem
disable-model-invocation: true
---

# Find CCSPlayer_ItemServices_GiveNamedItem, CCSPlayer_WeaponServices_Weapon_GetSlot, CBasePlayerPawn_RemovePlayerItem

Locate `CCSPlayer_ItemServices_GiveNamedItem`, `CCSPlayer_WeaponServices_Weapon_GetSlot`, and
`CBasePlayerPawn_RemovePlayerItem` in CS2 `server.dll` or `libserver.so` using IDA Pro MCP tools.

## Method

### 1. Resolve CCSPlayer_ItemServices_GiveNamedItem via VTable RTTI Walk

**ALWAYS** Use SKILL `/get-vtable-address` with `class_name=CCSPlayer_ItemServices`.

```text
mcp__ida-pro-mcp__find_regex pattern="22CCSPlayer_ItemServices"
mcp__ida-pro-mcp__xrefs_to addrs="<name_string_addr>"      # hit - 8 = typeinfo
mcp__ida-pro-mcp__xrefs_to addrs="<typeinfo_addr>"          # hit - 8 = vtable candidate, keep offset_to_top==0
```

Then read slot 24 (`vtable_va + 0x10 + 24*8`).

> Linux 14168 reference: name string `22CCSPlayer_ItemServices` at `0x8219d0`, typeinfo at `0x2489888`, primary
> vtable at `0x2489cf0`. Slot 24 (`vfunc_offset = 0xC0`) is at `0x2489dc0`, holding a tiny **15-byte thunk** at
> `0x152cfb0` whose entire body is `return sub_152C560(a1, a2, 0, 0, 0, 0);` — i.e. it forwards to the real
> implementation with the trailing default parameters (`nSubType`, an econ-item struct pointer, a "swap" bool, an
> item-definition-index override) zeroed out. **The vtable slot's function pointer IS this thunk** — sign the
   thunk itself (`func_va = 0x152cfb0`), not the larger worker it jumps to, since that is what CSS's vtable-slot
   hook actually intercepts.

Confirm by decompiling the thunk's target (`sub_152C560` on the reference build): it takes
`(this, const char *pszItemName, ...)`, contains hard-coded weapon-classname aliasing tables, and references the
literal debug strings `"GiveNamedItem: interpreting '%s' as '%s'\n"` and `"nullptr Ent in GiveNamedItem: %s!\n"` —
unambiguous confirmation this is `GiveNamedItem`.

### 2. Load CCSPlayer_ItemServices_GiveDefaultItems from YAML

**ALWAYS** Use SKILL `/get-func-from-yaml` with `func_name=CCSPlayer_ItemServices_GiveDefaultItems`.

If the skill returns an error, **STOP** and report to user (this skill's anchor must already be resolved).

Otherwise, extract:
- `func_va` of `CCSPlayer_ItemServices_GiveDefaultItems`

### 3. Decompile the Anchor and Enumerate Callees

```text
mcp__ida-pro-mcp__decompile addr="<GiveDefaultItems_func_addr>"
```

`GiveDefaultItems` gives the player their starting kevlar/knife/taser and, on warmup/pistol-round-style paths,
strips conflicting default weapons before re-granting them. It calls the just-resolved `GiveNamedItem` thunk (or
its worker directly) dozens of times — use pointer-identity comparisons against the thunk address from step 1
(`v15 == sub_152CFB0`-shaped branches in the decompilation) to distinguish those calls from the two helpers below.

### 4. Identify CCSPlayer_WeaponServices_Weapon_GetSlot

Among the anchor's other direct callees, find the one matching `(WeaponServices *this, int slot, int
requiredSubType)`:

- Iterates a `(count, ptr)` weapon-handle array at `this+72`/`this+80`.
- For each handle, resolves it through the global handle-table bucket lookup (`qword_26784E0`-style pattern) to a
  weapon entity pointer.
- Filters by calling the resolved weapon's own vtable slot at offset **2712** (its `GetLoadoutSlot`-style vfunc)
  against the `slot` argument (when `slot >= 0`), and vtable slot at offset **2720** against `requiredSubType`
  (when `requiredSubType >= 0`).
- Returns the first matching weapon pointer, or `0`/`nullptr`.
- Called from the anchor as `sub_1760210(weaponServicesThis, <slotIndex>, 0xFFFFFFFF)` to check whether the player
  already holds a weapon in a given loadout slot before granting the default weapon for that slot.

> Linux 14168 reference: `Weapon_GetSlot` is at `0x1760210`, size `0x1AD` (429 bytes). Generated `func_sig`:
> `55 48 89 E5 41 57 41 56 41 55 41 54 53 89 F3 48 83 EC ? 48 63 77`.

### 5. Identify CBasePlayerPawn_RemovePlayerItem

Still within the anchor, find the helper invoked in the loop that strips an existing slot-conflicting weapon
before granting a replacement (e.g. the pre-taser-grant "remove any existing slot-2 weapon" loop, which calls
`Weapon_GetSlot(weaponServicesThis, 2, -1)` repeatedly and passes each result into this helper):

- Takes `(WeaponServices *this, CBasePlayerWeapon *pWeapon)`.
- If `pWeapon` equals the currently-active weapon (via the class's `GetActiveWeapon(this)` helper) or the
  last-active weapon (`GetLastWeapon`-equivalent), clears associated aim-punch/recoil state on the weapon (two
  helper calls taking `(pWeapon, 0, ...)` shape) and clears the services' "last weapon" pointer.
- Unconditionally calls a detach helper `(this, pWeapon)` (the same detach helper also used by `EquipWeapon`, see
  the sibling skill `find-CCSPlayer_WeaponServices_EquipWeapon-AND-CCSPlayer_WeaponServices_CanUse`) followed by a
  destroy-entity helper `(pWeapon)`.

**Confidence note**: this helper operates at the `CCSPlayer_WeaponServices` level (its `this` is the weapon
services pointer, consistent with every other sibling function in this class), which is the effective
implementation reached for "remove a specific weapon from the player" during `GiveDefaultItems`'s conflict-clearing
loop. It is the strongest candidate found via this anchor for `RemovePlayerItem`-shaped semantics, but — unlike
`GiveNamedItem` (RTTI-vtable-confirmed) and `Weapon_GetSlot` (argument/vtable-offset-confirmed) — it was **not**
independently cross-checked against a `CBasePlayerPawn` vtable slot in this session. Before trusting it in a
release gamedata entry, additionally confirm it (or a thin forwarding wrapper around it) is reachable from a
`CBasePlayerPawn` vfunc slot, or from another anchor that unambiguously operates on a `CBasePlayerPawn *this`.

> Linux 14168 reference: candidate at `0x1580110`, size `0x92` (146 bytes), reached via a thin `(this,
> weapon)`-forwarding wrapper at `0x1587c60` (7 bytes: `if (pWeapon) return sub_1580110();`). Generated `func_sig`
> for `0x1580110`: `55 48 89 E5 41 54 49 89 FC 53 48 89 F3 E8 ? ? ? ? 48 39 C3`.

### 6. Generate Function Signature for CCSPlayer_WeaponServices_Weapon_GetSlot

**ALWAYS** Use SKILL `/generate-signature-for-function` with `addr=<Weapon_GetSlot_func_addr>`.

### 7. Generate Function Signature for CBasePlayerPawn_RemovePlayerItem

**ALWAYS** Use SKILL `/generate-signature-for-function` with `addr=<RemovePlayerItem_func_addr>`.

### 8. Write CCSPlayer_ItemServices_GiveNamedItem as YAML

**ALWAYS** Use SKILL `/write-vfunc-as-yaml`.

Required parameters:
- `func_name`: `CCSPlayer_ItemServices_GiveNamedItem`
- `func_addr`: `<GiveNamedItem_thunk_addr>` (the 15-byte vtable-slot thunk, not its worker)
- `vfunc_sig`: leave unset unless a stable sig for the thunk is required; the thunk's own bytes are short and may
  need `func_sig_allow_across_function_boundary`-style handling if the worker's address moves.

VTable parameters:
- `vtable_name`: `CCSPlayer_ItemServices`
- `vfunc_offset`: `0xC0` (`24 * 8`)
- `vfunc_index`: `24`

### 9. Write CCSPlayer_WeaponServices_Weapon_GetSlot as YAML

**ALWAYS** Use SKILL `/write-func-as-yaml`.

Required parameters:
- `func_name`: `CCSPlayer_WeaponServices_Weapon_GetSlot`
- `func_addr`: `<Weapon_GetSlot_func_addr>`
- `func_sig`: The validated signature from step 6

### 10. Write CBasePlayerPawn_RemovePlayerItem as YAML

**ALWAYS** Use SKILL `/write-func-as-yaml`.

Required parameters:
- `func_name`: `CBasePlayerPawn_RemovePlayerItem`
- `func_addr`: `<RemovePlayerItem_func_addr>`
- `func_sig`: The validated signature from step 7

## Function Characteristics

### CCSPlayer_ItemServices_GiveNamedItem

- **Purpose**: Grants an item/weapon to the player by classname string (e.g. `"weapon_ak47"`), handling legacy
  weapon-name aliasing and econ-item lookup.
- **Binary**: `server.dll` / `libserver.so`
- **Parameters**: `(this, const char *pszItemName, int nSubType = 0, ...)`
- **Return value**: pointer to the created/given entity, or `0`/`nullptr`
- **VTable**: `CCSPlayer_ItemServices`, slot **24** (`vfunc_offset = 0xC0`) on the Linux 14168 reference build.

### CCSPlayer_WeaponServices_Weapon_GetSlot

- **Purpose**: Finds the weapon (if any) the player is currently carrying in a given loadout slot / with a given
  subtype.
- **Binary**: `server.dll` / `libserver.so`
- **Parameters**: `(this, int slot, int requiredSubType)` — either may be `-1` to mean "don't filter on this".
- **Return value**: matching `CBasePlayerWeapon *`, or `0`/`nullptr`
- **Not virtual** — resolved via callee analysis of `GiveDefaultItems`.

### CBasePlayerPawn_RemovePlayerItem

- **Purpose**: Removes/destroys a specific weapon the player is currently carrying (used when a conflicting
  default weapon must be cleared before granting a replacement).
- **Binary**: `server.dll` / `libserver.so`
- **Parameters**: `(this, CBasePlayerWeapon *pWeapon)` (per this session's evidence, `this` resolves to the
  `CCSPlayer_WeaponServices` instance rather than a `CBasePlayerPawn` directly — see confidence note in step 5).
- **Return value**: not consumed by callers in the decompiled body observed (effectively `void`)
- **Not virtual** in this build (resolved via callee analysis, no vtable slot located).

## Discovery Strategy

1. `GiveNamedItem` is found with full confidence via RTTI vtable walk of `CCSPlayer_ItemServices` plus a
   distinctive-string confirmation in its worker function — this is the primary ground-truth-validated output of
   this skill (`vfunc_offset = 0xC0`, slot 24).
2. `Weapon_GetSlot` and `RemovePlayerItem` are both plain (non-virtual) helpers, so they are instead anchored via
   the already-resolved `CCSPlayer_ItemServices_GiveDefaultItems` function, which is known to call both while
   granting/replacing default equipment. `Weapon_GetSlot` is confirmed by its distinctive vtable-offset-2712 /
   vtable-offset-2720 filtering shape; `RemovePlayerItem` is a best-effort candidate reached through the
   conflict-clearing loop and should be independently re-verified if used as authoritative ground truth.

This is robust because:
- `GiveNamedItem`'s vtable-slot resolution is unaffected by any `.text` reshuffling.
- Anchoring the two helpers on `GiveDefaultItems`'s decompiled callee list survives address churn, since neither
  helper is itself independently stringref-able.

## Output YAML Format

The output YAML filenames depend on the platform:
- `server.dll` -> `CCSPlayer_ItemServices_GiveNamedItem.windows.yaml`,
  `CCSPlayer_WeaponServices_Weapon_GetSlot.windows.yaml`, `CBasePlayerPawn_RemovePlayerItem.windows.yaml`
- `libserver.so` -> `CCSPlayer_ItemServices_GiveNamedItem.linux.yaml`,
  `CCSPlayer_WeaponServices_Weapon_GetSlot.linux.yaml`, `CBasePlayerPawn_RemovePlayerItem.linux.yaml`

`CCSPlayer_ItemServices_GiveNamedItem.{platform}.yaml` fields: `func_name`, `func_va`, `func_rva`, `func_size`,
`vfunc_sig`, `vfunc_offset`, `vfunc_index`, `vtable_name`.

`CCSPlayer_WeaponServices_Weapon_GetSlot.{platform}.yaml` fields: `func_name`, `func_sig`, `func_va`, `func_rva`, `func_size`.

`CBasePlayerPawn_RemovePlayerItem.{platform}.yaml` fields: `func_name`, `func_sig`, `func_va`, `func_rva`, `func_size`.
