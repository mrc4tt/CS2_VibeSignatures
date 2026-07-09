---
name: find-CNetworkMessages_FindNetworkMessagePartial
description: |
  Find and identify the CNetworkMessages_FindNetworkMessagePartial virtual function in CS2 binary using IDA Pro MCP.
  Use this skill when reverse engineering CS2 networksystem.dll or libnetworksystem.so to locate the
  FindNetworkMessagePartial vfunc by decompiling the already-resolved CNetChan_ParseNetMessageShowFilter function
  and reading the devirtualized call it makes into the CNetworkMessages singleton, then confirming the slot
  against the CNetworkMessages vtable.
  Trigger: CNetworkMessages_FindNetworkMessagePartial
disable-model-invocation: true
---

# Find CNetworkMessages_FindNetworkMessagePartial

Locate `CNetworkMessages_FindNetworkMessagePartial` vfunc in CS2 `networksystem.dll` or `libnetworksystem.so`
using IDA Pro MCP tools.

## Method

### 1. Load CNetChan_ParseNetMessageShowFilter from YAML

**ALWAYS** Use SKILL `/get-func-from-yaml` with `func_name=CNetChan_ParseNetMessageShowFilter`.

If the skill returns an error, **STOP** and report to user (this skill depends on the sibling skill
`find-CNetChan_ParseNetMessageShowFilter-AND-g_pLoggingChannel` having already run).

Otherwise, extract:
- `func_va` of `CNetChan_ParseNetMessageShowFilter`

### 2. Load CNetworkMessages VTable from YAML

**ALWAYS** Use SKILL `/get-vtable-from-yaml` with `class_name=CNetworkMessages`.

If the skill returns an error, **STOP** and report to user.

Otherwise, extract:
- `vtable_va`
- `vtable_numvfunc`
- `vtable_entries`

### 3. Decompile CNetChan_ParseNetMessageShowFilter and Find the Call Site

```text
mcp__ida-pro-mcp__decompile addr="<CNetChan_ParseNetMessageShowFilter_func_va>"
```

`ParseNetMessageShowFilter` tokenizes its input filter string and, for every token, calls exactly one callee
with the shape `(pNetworkMessagesSingleton, pszPartialName)`, e.g.:

```c
v19 = sub_2A9F80(off_492B60, v18);
```

This call is **devirtualized** — it is a direct `call`, not an indirect `call qword ptr [reg+offset]` — because
the compiler knows the concrete type of the `CNetworkMessages` singleton (`off_492B60`/`g_NetworkMessages`) in
this translation unit. Record the callee address (`sub_2A9F80` / `0x2a9f80` on the Linux 14168 reference).

Confirm the callee's own body matches `FindNetworkMessagePartial` semantics: it takes `(this, const char
*pszPartialName)`, walks a hash-bucket chain of registered messages, and for each candidate resolves its name and
compares it against `pszPartialName` with a **partial/prefix** string-compare helper (not an exact-match compare),
returning the first match or `0`/`nullptr`.

### 4. Resolve the VTable Slot

Use SKILL `/get-vtable-index` with the callee address found in step 3 and `class_name=CNetworkMessages` (or
manually scan `vtable_entries` from step 2 for the matching address). This yields `vfunc_index` and
`vfunc_offset = vfunc_index * 8`.

> Linux 14168 reference: `CNetworkMessages_vtable` is at `0x47aac0`. The callee `0x2a9f80` is entry **14**
> (`vtable_va + 0x10 + 14*8 = 0x47ab40`), i.e. `vfunc_offset = 0x70`.

### 5. Generate Function Signature

**ALWAYS** Use SKILL `/generate-signature-for-function` with `addr=<FindNetworkMessagePartial_func_addr>` to
generate a robust and unique `func_sig`. Because Hex-Rays may split/merge basic blocks differently across builds
and this function is invoked from a devirtualized call site (so its prologue/epilogue can be shared or reordered
by the optimizer), pass `func_sig_allow_across_function_boundary=true` if the sub-skill supports it — this
mirrors the existing `find-CNetworkMessages_FindNetworkMessagePartial` preprocessor recipe, which sets
`func_sig_allow_across_function_boundary: true` on this entry.

### 6. Write IDA Analysis Output as YAML

**ALWAYS** Use SKILL `/write-vfunc-as-yaml` to write the analysis results.

Required parameters:
- `func_name`: `CNetworkMessages_FindNetworkMessagePartial`
- `func_addr`: `<FindNetworkMessagePartial_func_addr>`
- `func_sig`: The validated signature from step 5
- `vfunc_sig`: `None`

VTable parameters:
- `vtable_name`: `CNetworkMessages`
- `vfunc_offset`: `<vfunc_offset>` in hex
- `vfunc_index`: `<vfunc_index>`

Also set `func_sig_allow_across_function_boundary: true` in the emitted YAML.

## Function Characteristics

- **Purpose**: Given a partial/prefix network-message name, finds the first registered `CNetMessage` whose full
  name starts with (or otherwise partially matches) the given string. Used by the show-filter parser to resolve
  user-supplied short names (e.g. from `net_showmsg`) to concrete messages so their network-group id can be read.
- **Binary**: `networksystem.dll` / `libnetworksystem.so`
- **Parameters**: `(this, const char *pszPartialName)`
- **Return value**: pointer to the matched message's info/binding, or `0`/`nullptr` if no partial match exists.
- **VTable**: `CNetworkMessages` (also conceptually part of the `INetworkMessages` interface), slot 14
  (`vfunc_offset = 0x70`) on the Linux 14168 reference build.

## Discovery Strategy

1. Reuse the already-resolved `CNetChan_ParseNetMessageShowFilter` YAML (from the sibling skill) as the anchor —
   it is known to call `FindNetworkMessagePartial` exactly once per filter token.
2. Decompile the anchor and read off the devirtualized call target passed `(pNetworkMessagesSingleton,
   pszPartialName)`.
3. Confirm the callee's body performs a hash-bucket walk plus **partial** (not exact) name comparison.
4. Resolve the callee's position in the `CNetworkMessages` vtable via `/get-vtable-index` to obtain a portable
   `vfunc_index`/`vfunc_offset` that survives the callee's own address moving between builds.

This is robust because:
- The call-site shape `(singleton, pszPartialName) -> devirtualized call` is unambiguous — it is the only
  externally-typed call `ParseNetMessageShowFilter` makes per loop iteration.
- Confirming via the partial-match string-compare body (as opposed to an exact-match compare) distinguishes this
  vfunc from the sibling `CNetworkMessages_FindNetworkMessage` (exact match) and `CNetworkMessages_FindNetworkGroup`.
- Re-deriving `vfunc_index`/`vfunc_offset` from the resolved `CNetworkMessages_vtable` (rather than hard-coding
  it) keeps the recipe correct even if the vtable layout shifts between game updates.

## Output YAML Format

The output YAML filename depends on the platform:
- `networksystem.dll` -> `CNetworkMessages_FindNetworkMessagePartial.windows.yaml`
- `libnetworksystem.so` -> `CNetworkMessages_FindNetworkMessagePartial.linux.yaml`

Fields: `func_name`, `func_va`, `func_rva`, `func_size`, `func_sig`, `vtable_name`, `vfunc_offset`, `vfunc_index`,
`func_sig_allow_across_function_boundary: true`.
