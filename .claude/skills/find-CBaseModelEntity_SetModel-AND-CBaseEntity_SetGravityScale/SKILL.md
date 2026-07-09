---
name: find-CBaseModelEntity_SetModel-AND-CBaseEntity_SetGravityScale
description: |
  Find and identify the CBaseModelEntity_SetModel and CBaseEntity_SetGravityScale functions in CS2 binary using
  IDA Pro MCP. Use this skill when reverse engineering CS2 server.dll / libserver.so to locate the model-assignment
  routine by scanning for its distinctive fixed byte signature directly (two near-identical sibling wrappers exist
  and must be disambiguated by matching the reference signature's exact tail bytes, including the following
  function's leading byte).
  Trigger: CBaseModelEntity_SetModel, CBaseEntity_SetGravityScale
disable-model-invocation: true
---

# Find CBaseModelEntity_SetModel and CBaseEntity_SetGravityScale

Locate `CBaseModelEntity_SetModel` and `CBaseEntity_SetGravityScale` in CS2 `server.dll` / `libserver.so` using
IDA Pro MCP tools.

## Method

### 1. Locate Candidates via Direct Byte-Pattern Scan

Both target functions share an almost byte-identical body shape (thin wrapper: fetch a value via a vcall through
a global singleton, then tail-jump into a shared internal setter). Scan directly:

```text
mcp__ida-pro-mcp__find_bytes patterns=["55 48 89 E5 53 48 89 FB 48 83 EC ?? 48 8D 05 ?? ?? ?? ?? 48 8B 38 48 8B 07 FF 50 ?? 48 89 DF 48 8B 5D ?? C9 48 89 C6 E9"]
```

This returns **two** hits on the 14168 Linux binary, 0x30 bytes apart — `CBaseModelEntity_SetModel` and
`CBaseEntity_SetGravityScale` (or a similarly-shaped sibling wrapper) — which must be disambiguated in step 2.

### 2. Disambiguate via Exact Tail-Byte Match

Fetch ~50-64 raw bytes at both hits:

```text
mcp__ida-pro-mcp__get_bytes regions=[{"addr":"<hit1>","size":64}]
mcp__ida-pro-mcp__get_bytes regions=[{"addr":"<hit2>","size":64}]
```

Both bodies are structurally identical (`push rbp; mov rbp,rsp; push rbx; mov rbx,rdi; sub rsp,8; lea rax,
<global>; mov rdi,[rax]; mov rax,[rdi]; call [rax+imm8]; mov rdi,rbx; mov rbx,[rbp-8]; leave; mov rsi,rax; jmp
<shared_setter>`) and differ only in the RIP-relative `lea` displacement (pointing at slightly different global
slots) and in `4` bytes of padding immediately after the trailing `E9 <rel32>` jmp. The reference signature for
`CBaseModelEntity_SetModel` is long enough to include those 4 padding bytes (`CC CC CC CC`) **plus the first byte
of the next function** (`55`, a fresh `push rbp`). Only the correct candidate has a `push rbp`-prologued function
immediately following its own padding — the sibling candidate's next function starts differently (e.g. `48 8B 47
...`), so its tail byte disagrees with the reference and it is rejected.

> Linux 14168 reference: `CBaseModelEntity_SetModel` at `0x15d94c0` (size `0x2c`) — its padding is immediately
> followed by `55` (a new function's `push rbp`), matching the reference exactly through the last byte.
> `CBaseEntity_SetGravityScale` at `0x15d94f0` (size `0x2c`, adjacent) — its padding is followed by `48 8B 47 10
> ...`, which disagrees with the reference's trailing `55` and correctly disqualifies it as the `SetModel` match.

### 3. Confirm via Decompile

```text
mcp__ida-pro-mcp__decompile addr="<SetModel_candidate_addr>"
```

Both candidates decompile to the same shape:

```c
__int64 __fastcall sub(__int64 a1)
{
  __int64 v1 = (*(__int64 (__fastcall **)(__int64))(*(_QWORD *)g_pSomeSingleton + 0x68))(g_pSomeSingleton);
  return sub_SharedSetter(a1, v1);
}
```

i.e. each fetches a value from a global engine-singleton via a fixed vtable slot, then forwards `(this, fetched
value)` into one shared internal setter (`sub_15D90F0` on this build) used by both. This matches "internally
precaches/loads a resource and calls a dispatch through the resource's own interface" for `SetModel` (fetching a
default/error-model index or pointer via the model-manager singleton, then delegating to the internal
model-assignment routine also used by other model-setting overloads). Both siblings being structurally identical
thin forwarders is consistent with `SetModel()` (zero-argument overload defaulting to an error/default model) and
`SetGravityScale()` sharing a similar "fetch-default-then-delegate" code-generation pattern purely by coincidence
of compiler output shape — the byte-level disambiguation in step 2 is what actually separates them, not the
decompile shape (which is inconclusive on its own).

### 4. Generate Function Signature

**ALWAYS** Use SKILL `/generate-signature-for-function` with `addr=<SetModel_candidate_addr>` to generate a robust
and unique `func_sig` for `CBaseModelEntity_SetModel`. Repeat for `CBaseEntity_SetGravityScale` once independently
confirmed (best-effort; no ground truth signature was available for it this session).

### 5. Write IDA Analysis Output as YAML

**ALWAYS** Use SKILL `/write-func-as-yaml` for `CBaseModelEntity_SetModel` with the address/signature from
steps 1-4. Repeat for `CBaseEntity_SetGravityScale`.

## Function Characteristics

### CBaseModelEntity_SetModel

- **Purpose**: Sets an entity's render model, `CBaseModelEntity::SetModel()` — the observed overload takes no
  meaningful model-name argument on this build's compiled body (the sole detected parameter is `this`); it fetches
  a value (likely a default/error model index) via a global model-manager singleton vcall and forwards to a shared
  internal model-assignment routine.
- **Binary**: `server.dll` / `libserver.so`
- **Parameters**: `(CBaseModelEntity *this)` as decompiled on this build (the string-taking overload, if a
  separate one exists, was not located this session — this is the zero/default-argument shape matching the
  reference signature).
- **VTable**: none — concrete method; internally performs one vcall through a global singleton at a fixed offset
  (`+0x68` on this build).

### CBaseEntity_SetGravityScale

- **Purpose**: Presumed to set an entity's gravity scale multiplier; **not independently confirmed with ground
  truth this session** — identified only as the byte-adjacent sibling wrapper with the same code shape as
  `SetModel`, rejected as the `SetModel` match specifically because its trailing bytes disagree with the reference
  signature (see step 2).
- **Binary**: `server.dll` / `libserver.so`
- **Status**: best-effort location only (`0x15d94f0` on the Linux 14168 reference build); treat as unverified.

## Discovery Strategy

1. The shared wrapper shape (`push rbp; mov rbp,rsp; push rbx; mov rbx,rdi; sub rsp,imm8; lea rax,<global>; ...;
   jmp <shared_setter>`) is distinctive enough to scan directly with `find_bytes`, but is **not unique** — it
   returns 2 hits since the compiler reuses this exact forwarding shape for at least one other setter.
2. Disambiguation relies on matching the reference signature's *tail*, deliberately including 4 bytes of
   inter-function padding plus the first byte of whatever function follows — this turns an otherwise-ambiguous
   26-instruction match into a fully unique one, since only one of the two candidates happens to be immediately
   followed by a `push rbp`-prologued function.
3. Decompiling both is useful for understanding *what* the function does but does **not** by itself distinguish
   `SetModel` from `SetGravityScale` on this build, since both compile to structurally identical forwarding
   bodies — byte-level tail matching against the reference is the load-bearing step here.

This is robust because the reference signature was deliberately generated long enough (by
`make_signature_for_function`'s natural growth-to-uniqueness behavior) to include the next function's leading
byte, which is exactly the minimum information needed to break the tie between the two candidates.

## Output YAML Format

The output YAML filenames depend on the platform:
- `server.dll` -> `CBaseModelEntity_SetModel.windows.yaml`, `CBaseEntity_SetGravityScale.windows.yaml`
- `libserver.so` -> `CBaseModelEntity_SetModel.linux.yaml`, `CBaseEntity_SetGravityScale.linux.yaml`

Fields (both files): `func_name`, `func_va`, `func_rva`, `func_size`, `func_sig`.

> Linux 14168 reference: `CBaseModelEntity_SetModel` func_sig =
> `55 48 89 E5 53 48 89 FB 48 83 EC ? 48 8D 05 ? ? ? ? 48 8B 38 48 8B 07 FF 50 ? 48 89 DF 48 8B 5D ? C9 48 89 C6 E9 ? ? ? ? CC CC CC CC 55`,
> `func_va = 0x15d94c0`, `func_size = 0x2c`. `CBaseEntity_SetGravityScale` (unverified) `func_va = 0x15d94f0`,
> `func_size = 0x2c`.
