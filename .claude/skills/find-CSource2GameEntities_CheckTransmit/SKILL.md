---
name: find-CSource2GameEntities_CheckTransmit
description: |
  Find and identify the CSource2GameEntities::CheckTransmit virtual function in the CS2 server binary using
  IDA Pro MCP. Use this skill when reverse engineering CS2 server.dll or libserver.so to locate the transmit-list
  decision function by scanning the `./gameinterface.cpp` compile-unit string fragments for a code xref, then
  confirming via the mangled `CheckTransmit` symbol left over from a parallel-job lambda and the
  `CSource2GameEntities` vtable slot.
  Trigger: CSource2GameEntities_CheckTransmit
disable-model-invocation: true
---

# Find CSource2GameEntities_CheckTransmit

Locate `CSource2GameEntities::CheckTransmit` in CS2 `server.dll` / `libserver.so` using IDA Pro MCP tools.

## Method

### 1. Find the gameinterface.cpp Compile-Unit String Fragments

```text
mcp__ida-pro-mcp__find_regex pattern="gameinterface\.cpp"
```

`server.so` is compiled with `assert`/debug-string fragments that embed the source file path, e.g.
`"./gameinterface.cpp"` and `"./gameinterface.cpp:<line>"`. `CheckTransmit` lives in `gameinterface.cpp`, so any
function referencing one of these fragments is a candidate for functions defined in that file.

> Linux 14168 reference: two hits — `"./gameinterface.cpp"` at `0x8e4cc1` (referenced by unrelated functions
> `sub_18D1AC0`/`sub_18DCDE0`) and `"./gameinterface.cpp:3135"` at `0x8e78be` (referenced by exactly one function).

### 2. Get the Referencing Function

```text
mcp__ida-pro-mcp__xrefs_to addr="<gameinterface_cpp_line_string_addr>"
```

The line-numbered fragment `"./gameinterface.cpp:3135"` is referenced from inside one function only. That
function's start address is the `CheckTransmit` candidate.

> Linux 14168 reference: `"./gameinterface.cpp:3135"` (`0x8e78be`) is referenced from `0x18f0f74`, inside the
> function starting at `0x18f03a0` (size `0x1167`).

### 3. Confirm via the Mangled Lambda-Job Symbol

```text
mcp__ida-pro-mcp__find_regex pattern="CSource2GameEntities"
```

Among the hits is a mangled Itanium name for a `CParallelLambdaJob` used inside `CheckTransmit`'s parallel
worker: it contains the substring `20CSource2GameEntities13CheckTransmitEPP18CCheckTransmitInfoiR7CBitVec...`,
i.e. `CSource2GameEntities::CheckTransmit(CCheckTransmitInfo**, int, CBitVec<16384>&, CBitVec<16384>&,
Entity2Networkable_t const**, unsigned short const*, int)`. This independently confirms the method name/binding
without needing to decompile the candidate's full body.

> Linux 14168 reference: the mangled lambda-job string is at `0x83dc60`; the `CSource2GameEntities` typeinfo name
> string `"20CSource2GameEntities"` is at `0x83d950`.

### 4. Decompile and Sanity-Check the Candidate

```text
mcp__ida-pro-mcp__decompile addr="0x18f03a0"
```

Confirm the decompilation is consistent with `CheckTransmit`'s signature: 8 parameters (`this` +
`CCheckTransmitInfo**` array + `int count` + two `CBitVec<16384>&` + `Entity2Networkable_t const**` +
`unsigned short const*` + `int`), a large body (hundreds of instructions), and logic that iterates the entity
list and mutates per-client transmit bit vectors.

### 5. Confirm the VTable Slot

**ALWAYS** Use SKILL `/get-vtable-index` with the candidate address and `class_name=CSource2GameEntities` (or
RTTI-walk manually: find typeinfo name `"20CSource2GameEntities"` -> typeinfo -> primary vtable (`offset_to_top ==
0`) -> scan slots for the candidate address).

> Linux 14168 reference: `CSource2GameEntities` typeinfo is at `0x24c7160` (name ptr `0x24c7168` ->
> `0x83d950 - 8`... i.e. name string ref at `0x83d950`, xref `0x24c7168`, typeinfo `0x24c7160`). Primary vtable
> (`offset_to_top == 0`) is at `0x24c91d0` (a secondary base-subobject vtable with `offset_to_top == -0x28` also
> exists at `0x24c9288` and should be ignored). `CheckTransmit` occupies **slot 13** (`vtable + 0x10 + 13*8 =
> 0x24c9240`) in the primary vtable.

### 6. Generate Function Signature

**ALWAYS** Use SKILL `/generate-signature-for-function` with `addr=0x18f03a0` to generate a robust and unique
`func_sig`.

> Linux 14168 reference: generated signature is
> `55 48 89 E5 41 57 49 89 FF 41 56 48 8D 3D ? ? ? ? 41 55 4C 63 EA` (16 fixed head bytes plus a wildcarded
> 4-byte RIP-relative displacement, then more fixed bytes) — already unique across the binary at this length.

### 7. Write IDA Analysis Output as YAML

**ALWAYS** Use SKILL `/write-vfunc-as-yaml` to write the analysis results.

Required parameters:
- `func_name`: `CSource2GameEntities_CheckTransmit`
- `func_addr`: `0x18f03a0`
- `func_sig`: The validated signature from step 6
- `vfunc_sig`: `None`

VTable parameters:
- `vtable_name`: `CSource2GameEntities`
- `vfunc_offset`: `0x68` (`13 * 8`)
- `vfunc_index`: `13`

## Function Characteristics

- **Purpose**: Decides which entities are network-visible ("transmitted") to which clients this tick; called from
  the engine's transmit-list build path once per frame per recipient group.
- **Binary**: `server.dll` / `libserver.so`
- **Parameters**: `(this, CCheckTransmitInfo **ppInfoList, int nInfoCount, CBitVec<16384> &, CBitVec<16384> &,
  Entity2Networkable_t const **pNetworkables, unsigned short const *pEntityIndicesToConsider, int nEdictCount)`
  (per the demangled lambda-job symbol found in step 3).
- **Return value**: `void`/unused (writes results into the passed-in bit vectors).
- **VTable**: `CSource2GameEntities`, slot 13 (`vfunc_offset = 0x68`) on the Linux 14168 reference build.

## Discovery Strategy

1. `gameinterface.cpp` compile-unit debug-string fragments (`__FILE__`-style, embedded by `assert`/log macros)
   are a reliable, version-agnostic anchor for functions defined in that translation unit — `CheckTransmit` is one
   of them.
2. The line-numbered fragment (`"./gameinterface.cpp:3135"`) has exactly one xref, pinpointing the containing
   function unambiguously.
3. The demangled Itanium symbol for `CheckTransmit`'s internal parallel-job lambda (left in the binary as a
   `CParallelLambdaJob<...>` template instantiation's typeinfo name) independently corroborates both the method
   name and its full parameter signature — this does not depend on the string-fragment path at all, so it's a
   strong cross-check.
4. The `CSource2GameEntities` primary vtable slot is re-derived via RTTI rather than hardcoded, so it survives
   vtable layout drift across builds.

This is robust because two independent discovery paths (compile-unit string xref, and mangled lambda-job symbol)
converge on the same function, and the vtable slot is confirmed via RTTI rather than assumed.

## Output YAML Format

The output YAML filename depends on the platform:
- `server.dll` -> `CSource2GameEntities_CheckTransmit.windows.yaml`
- `libserver.so` -> `CSource2GameEntities_CheckTransmit.linux.yaml`

Fields: `func_name`, `func_va`, `func_rva`, `func_size`, `func_sig`, `vtable_name`, `vfunc_offset`, `vfunc_index`.
