---
name: find-INetworkMessages_GetNetworkGroupCount-AND-INetworkMessages_GetNetworkGroupName-AND-INetworkMessages_GetNetworkGroupColor
description: |
  Find and identify INetworkMessages_GetNetworkGroupCount, INetworkMessages_GetNetworkGroupName and
  INetworkMessages_GetNetworkGroupColor virtual functions in CS2 binary using IDA Pro MCP. Use this skill when
  reverse engineering CS2 networksystem.dll or libnetworksystem.so to locate the three network-group accessor
  vfuncs by decompiling the already-resolved CNetworkSystem_SendNetworkStats anchor and reading the three
  consecutive devirtualized calls it makes into the CNetworkMessages singleton (count, then name/color per
  group index), then confirming each slot against the CNetworkMessages vtable.
  Trigger: INetworkMessages_GetNetworkGroupCount, INetworkMessages_GetNetworkGroupName, INetworkMessages_GetNetworkGroupColor
disable-model-invocation: true
---

# Find INetworkMessages_GetNetworkGroupCount, INetworkMessages_GetNetworkGroupName, INetworkMessages_GetNetworkGroupColor

Locate `INetworkMessages_GetNetworkGroupCount`, `INetworkMessages_GetNetworkGroupName` and
`INetworkMessages_GetNetworkGroupColor` vfuncs in CS2 `networksystem.dll` or `libnetworksystem.so` using IDA Pro
MCP tools.

## Method

### 1. Load CNetworkSystem_SendNetworkStats from YAML

**ALWAYS** Use SKILL `/get-func-from-yaml` with `func_name=CNetworkSystem_SendNetworkStats`.

If the skill returns an error, locate the anchor directly in IDA instead of stopping (see "Fallback anchor
lookup" below), since this skill's dependency chain only requires the anchor to exist as *code*, not as a
pre-written YAML.

Otherwise, extract:
- `func_va` of `CNetworkSystem_SendNetworkStats`

#### Fallback anchor lookup

If no YAML exists yet, find `CNetworkSystem_SendNetworkStats` by its distinctive string/behavior fingerprint
(this matches the repo's own `find-CNetworkSystem_SendNetworkStats` preprocessor recipe):

1. Find all functions that reference the string `"Stack depth limit hit (%d)"` (a generic KV3/DTI recursion
   guard string, so this string alone is **not** unique — expect several hits).
2. Discard any candidate that also references the string `"Class data is a '%s', not a table\n"` (that string
   marks unrelated schema-cast-error functions).
3. Among the remaining candidates, the correct one is the single large function that: reads a group **count**
   via a devirtualized call taking only `this`, then loops `[0, count)` calling two more devirtualized calls
   taking `(this, i)` to fetch a **name** (`const char *`) and a **color** (packed 32-bit value) per index, and
   writes the results into a `"groupnames"` array of `{name, color}` records consumed by a KV3/DTI save routine
   (look for the literal strings `"groupnames"`, `"name"`, `"color"` in its string references — these are the
   KV3 field names for the serialized network-group table).

> Linux 14168 reference: `CNetworkSystem_SendNetworkStats` is `sub_2ca180` at VA `0x2ca180` (size `0x1555`). It
> is the only "Stack depth limit hit" candidate that also references `"groupnames"`/`"name"`/`"color"`, and it
> does **not** reference `"Class data is a '%s', not a table\n"`.

### 2. Load CNetworkMessages VTable from YAML

**ALWAYS** Use SKILL `/get-vtable-from-yaml` with `class_name=CNetworkMessages`.

If the skill returns an error, **STOP** and report to user.

Otherwise, extract:
- `vtable_va`
- `vtable_numvfunc`
- `vtable_entries`

### 3. Decompile the Anchor and Find the Three Call Sites

```text
mcp__ida-pro-mcp__decompile addr="<CNetworkSystem_SendNetworkStats_func_va>"
```

Inside the group-enumeration loop, look for three **devirtualized** calls (direct `call`s, not `call qword ptr
[reg+offset]`, since the compiler knows the singleton's concrete type in this translation unit) through the same
`CNetworkMessages`/`INetworkMessages` singleton pointer, at three consecutive vtable byte-offsets 8 apart:

```c
v103 = (*(vt + 128))(pNetworkMessagesSingleton);              // count:  (this) -> int
...
v57 = (*(vt + 136))(pNetworkMessagesSingleton, (unsigned int)v54); // name:  (this, i) -> const char*
v58 = (*(vt + 144))(pNetworkMessagesSingleton, (unsigned int)v54); // color: (this, i) -> uint32
```

Record the three raw callee addresses resolved at those offsets (or read them directly off the
`CNetworkMessages_vtable` entries at `offset/8`, `offset/8 + 1`, `offset/8 + 2` — the three getters are
consecutive vtable slots).

Confirm each candidate's own decompiled body:

- **Count** candidate: zero-argument (besides `this`), body is essentially `return <int32 member of this>;`
  (behind a read-write-lock acquire/release pair). No index parameter.
- **Name** candidate: `(this, int groupIndex)`. First instruction checks `groupIndex < 0` and returns the
  literal string `"Invalid"` if so; otherwise compares `groupIndex` against the same count member read by the
  Count candidate and again returns `"Invalid"` if out of range; otherwise looks the name up in a small
  hash/array structure and returns a `const char *`.
- **Color** candidate: `(this, int groupIndex)`. Body deterministically derives an RGBA-ish 32-bit value from
  `groupIndex` using an HSV→RGB-style conversion (`hue = groupIndex * 360.0 / count`), caches the generated
  colors in a growable array, and returns the cached 32-bit color for `groupIndex`.

### 4. Resolve Each VTable Slot

For each of the three confirmed callee addresses, use SKILL `/get-vtable-index` (or manually scan
`vtable_entries` from step 2) to obtain `vfunc_index`/`vfunc_offset = vfunc_index * 8`. They must be three
**consecutive** slots.

> Linux 14168 reference (`CNetworkMessages_vtable` at `0x47aac0`):
>
> | Function | VA | Size | vfunc_index | vfunc_offset |
> |---|---|---|---|---|
> | `GetNetworkGroupCount` | `0x2a4ff0` | `0x68` | 16 | `0x80` |
> | `GetNetworkGroupName`  | `0x2a50a0` | `0xc8` | 17 | `0x88` |
> | `GetNetworkGroupColor` | `0x2abba0` | `0x656`| 18 | `0x90` |

Even though these three getters are physically implemented in the `CNetworkMessages` vtable (there is no
separate `INetworkMessages_vtable` symbol — `INetworkMessages` is a pure-abstract primary base whose vtable slots
are simply the leading entries of `CNetworkMessages`'s own vtable), record `vtable_name: INetworkMessages` for
all three, matching this repo's naming convention for interface-level getters (see the existing
`INetworkMessages_*` entries in `config.yaml`, all of which are physically resolved via the `CNetworkMessages`
vtable/call sites but recorded under the `INetworkMessages` interface name).

### 5. Generate Function Signatures

**ALWAYS** Use SKILL `/generate-signature-for-function` with `addr=<GetNetworkGroupCount_func_addr>` (repeat for
`GetNetworkGroupName` and `GetNetworkGroupColor`) to generate a robust and unique `vfunc_sig` for each.

### 6. Write IDA Analysis Output as YAML

**ALWAYS** Use SKILL `/write-vfunc-as-yaml` three times, once per function.

For `INetworkMessages_GetNetworkGroupCount`:
- `func_name`: `INetworkMessages_GetNetworkGroupCount`
- `func_addr`: `<GetNetworkGroupCount_func_addr>`
- `vfunc_sig`: The validated signature from step 5
- VTable parameters: `vtable_name: INetworkMessages`, `vfunc_offset: <offset>`, `vfunc_index: <index>`

For `INetworkMessages_GetNetworkGroupName`:
- `func_name`: `INetworkMessages_GetNetworkGroupName`
- `func_addr`: `<GetNetworkGroupName_func_addr>`
- `vfunc_sig`: The validated signature from step 5
- VTable parameters: `vtable_name: INetworkMessages`, `vfunc_offset: <offset>`, `vfunc_index: <index>`

For `INetworkMessages_GetNetworkGroupColor`:
- `func_name`: `INetworkMessages_GetNetworkGroupColor`
- `func_addr`: `<GetNetworkGroupColor_func_addr>`
- `vfunc_sig`: The validated signature from step 5
- VTable parameters: `vtable_name: INetworkMessages`, `vfunc_offset: <offset>`, `vfunc_index: <index>`

## Function Characteristics

### INetworkMessages_GetNetworkGroupCount
- **Purpose**: Returns the number of registered network-message groups (categories used for stats/netgraph).
- **Parameters**: `(this)`
- **Return value**: `int` — small positive count.

### INetworkMessages_GetNetworkGroupName
- **Purpose**: Returns the display name of the network-message group at the given index.
- **Parameters**: `(this, int groupIndex)`
- **Return value**: `const char *` — `"Invalid"` if `groupIndex` is out of `[0, GetNetworkGroupCount())`.

### INetworkMessages_GetNetworkGroupColor
- **Purpose**: Returns a stable, deterministically-generated display color for the network-message group at the
  given index (used to color-code the group in stats output / netgraph).
- **Parameters**: `(this, int groupIndex)`
- **Return value**: packed 32-bit color.

All three: **Binary**: `networksystem.dll` / `libnetworksystem.so`; **VTable**: `CNetworkMessages`, recorded as
interface `INetworkMessages`, three consecutive slots.

## Discovery Strategy

1. Resolve `CNetworkSystem_SendNetworkStats` (existing YAML if present, else via the `"Stack depth limit hit
   (%d)"` xref filtered by the `"groupnames"`/`"name"`/`"color"` KV3-field strings, excluding the
   `"Class data is a '%s', not a table\n"` false positives).
2. Decompile it and locate the count→loop(name,color) shape: one devirtualized call taking only `this` used as a
   loop bound, followed in the loop body by two more devirtualized calls taking `(this, i)`, at three consecutive
   8-byte-apart vtable offsets.
3. Confirm each candidate's own body against its distinct signature (count: no index, trivial return; name:
   bounds-checked string lookup with an `"Invalid"` fallback; color: HSV-derived deterministic color generator).
4. Re-derive `vfunc_index`/`vfunc_offset` for each from the `CNetworkMessages_vtable` YAML via `/get-vtable-index`
   rather than hard-coding offsets, so the recipe survives vtable layout drift across game updates.

This is robust because:
- The three getters are always call-adjacent inside `SendNetworkStats`'s group loop and always occupy three
  consecutive vtable slots — even if their absolute addresses or the exact slot numbers shift between builds,
  the *relative* shape (count, then name+8, then color+16) does not.
- Each getter has a distinct, easily-verified body shape (no-arg trivial getter vs. bounds-checked string lookup
  vs. HSV color generator), so a false match is very unlikely even without the anchor.
- The anchor itself (`SendNetworkStats`) is independently pinned by a combination of a common string plus two
  exclusion/inclusion string filters, avoiding reliance on any single non-unique string.

## Output YAML Format

The output YAML filenames depend on the platform:
- `networksystem.dll` -> `INetworkMessages_GetNetworkGroupCount.windows.yaml`, `INetworkMessages_GetNetworkGroupName.windows.yaml`, `INetworkMessages_GetNetworkGroupColor.windows.yaml`
- `libnetworksystem.so` -> `INetworkMessages_GetNetworkGroupCount.linux.yaml`, `INetworkMessages_GetNetworkGroupName.linux.yaml`, `INetworkMessages_GetNetworkGroupColor.linux.yaml`

Fields for each: `func_name`, `vfunc_sig`, `vfunc_offset`, `vfunc_index`, `vtable_name`.
