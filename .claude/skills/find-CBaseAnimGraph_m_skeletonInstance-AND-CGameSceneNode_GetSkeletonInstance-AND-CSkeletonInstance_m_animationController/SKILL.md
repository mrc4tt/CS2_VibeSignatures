---
name: find-CBaseAnimGraph_m_skeletonInstance-AND-CGameSceneNode_GetSkeletonInstance-AND-CSkeletonInstance_m_animationController
description: |
  Find and identify the CGameSceneNode::GetSkeletonInstance virtual function's vtable slot, plus the
  CBaseAnimGraph::m_skeletonInstance and CSkeletonInstance::m_animationController struct member offsets, in the
  CS2 server binary using IDA Pro MCP. Use this skill when reverse engineering server.dll or libserver.so to
  locate the scene-node accessor that returns a node's CSkeletonInstance* (or null if the node isn't a skinned
  model), and the two related struct-member offsets used by CounterStrikeSharp's animation-graph memory patches.
  Trigger: CBaseAnimGraph_m_skeletonInstance, CGameSceneNode_GetSkeletonInstance, CSkeletonInstance_m_animationController
disable-model-invocation: true
---

# Find CBaseAnimGraph_m_skeletonInstance, CGameSceneNode_GetSkeletonInstance, CSkeletonInstance_m_animationController

Locate `CGameSceneNode::GetSkeletonInstance` (vtable slot), `CBaseAnimGraph::m_skeletonInstance` (struct
offset), and `CSkeletonInstance::m_animationController` (struct offset) in CS2 `server.dll` / `libserver.so`
using IDA Pro MCP tools.

## Method

### 1. Resolve CGameSceneNode_GetSkeletonInstance (vtable-slot output)

**ALWAYS** Use SKILL `/get-vtable-address` with `class_name=CGameSceneNode` (RTTI walk via the Itanium typeinfo
name string `"14CGameSceneNode"`; primary vtable = the candidate whose `offset_to_top` qword is `0` and whose
first few slots point into executable memory).

> Linux 14168 reference: `CGameSceneNode` primary vtable `0x23e6930`.

Read slot **13** directly (`FUNC_VTABLE_RELATIONS = [("CGameSceneNode_GetSkeletonInstance", "CGameSceneNode")]`
— the class/slot pair is already known from the preprocessor config; no additional discovery is required for the
index itself):

```text
mcp__ida-pro-mcp__idalib get_int queries=[{"addr":"<vtable_va + 0x10 + 13*8>","ty":"u64"}]
```

Decompile the resulting address and confirm it matches `GetSkeletonInstance`'s expected shape: `CGameSceneNode`
itself is not a skinned/animated node, so its **own** (base-class) implementation of this virtual is expected to
be a trivial stub that unconditionally returns null/0 — only overriding classes further down the hierarchy
(e.g. `CSkeletonInstance` itself, or classes that own one) return a real pointer.

> Linux 14168 reference: slot 13 resolves to `0xa60770`, a 3-byte function whose entire body is `return 0;`
> (`xor eax,eax; retn` — i.e. `mov eax, 0; ret`) — confirming the "returns null unless this is actually a
> skinned node" pattern and matching ground truth slot index **13**.

**ALWAYS** Use SKILL `/get-vtable-index` to double check the resolved function occupies exactly slot 13 if you
re-derive it by any other means (e.g. from a caller that devirtualizes the call).

**ALWAYS** Use SKILL `/generate-signature-for-vfuncoffset` if a call-site signature (rather than just the raw
slot index) is also desired for a patch/hook use-case — most CounterStrikeSharp consumers only need the plain
`vfunc_index`/`vfunc_offset`, emitted via `/write-vfunc-as-yaml` below.

### 2. Resolve CBaseAnimGraph_m_skeletonInstance (struct-offset output)

This is a plain data-member offset, not a vtable slot: the byte offset of the embedded `CSkeletonInstance`
sub-object within `CBaseAnimGraph`. Locate a `CBaseAnimGraph`-owning class's constructor or an accessor that
reads/writes this member with a fixed, small immediate displacement off `this` (e.g. `CBaseModelEntity`'s or
`CBaseAnimGraph`'s own `GetSkeletonInstance`-equivalent accessor, or the constructor that placement-news the
`CSkeletonInstance` into the object).

**ALWAYS** Use SKILL `/generate-signature-for-structoffset` on the anchor instruction that references
`this + <m_skeletonInstance offset>` (e.g. a `lea reg, [rdi+OFF]` or `add rdi, OFF` feeding a
`CSkeletonInstance`-constructor-shaped call) once you've located a suitable instruction — this both confirms the
offset and produces a version-resilient signature for it.

**ALWAYS** Use SKILL `/write-structoffset-as-yaml` to persist the result, with `struct_name=CBaseAnimGraph`,
`member_name=m_skeletonInstance`, and the offset + signature from the previous step.

> This offset was **not** independently re-derived/validated in this pass (only `CGameSceneNode_GetSkeletonInstance`'s
> vtable slot was in scope for validation here) — follow the pattern above on a fresh run to resolve and confirm
> a concrete value before relying on it.

### 3. Resolve CSkeletonInstance_m_animationController (struct-offset output)

Same shape as step 2, but for the offset of the embedded/owned `CAnimationController` (or pointer to one) within
`CSkeletonInstance`. Look for an accessor on `CSkeletonInstance` (commonly named something like
`GetAnimationController` if it's virtual, or a direct field read if not) that references `this + OFF` with a
small fixed displacement, feeding calls into animation-graph update code.

**ALWAYS** Use SKILL `/generate-signature-for-structoffset` on the anchor instruction, then **ALWAYS** Use SKILL
`/write-structoffset-as-yaml` with `struct_name=CSkeletonInstance`, `member_name=m_animationController`, and the
resolved offset + signature.

> This offset was **not** independently re-derived/validated in this pass either — same caveat as step 2.

## Function/Member Characteristics

### CGameSceneNode_GetSkeletonInstance

- **Purpose**: Returns the `CSkeletonInstance*` associated with a scene node, or `nullptr` if the node has no
  skeleton (e.g. a plain, non-animated `CGameSceneNode`). Used throughout the animation/bone-access code paths
  to safely down-cast a generic scene node to its skeleton data.
- **Binary**: `server.dll` / `libserver.so`
- **Parameters**: `(CGameSceneNode *this)`
- **Return value**: `CSkeletonInstance*` or `nullptr`
- **VTable**: `CGameSceneNode`, slot **13** (`vfunc_offset = 0x68`) — matches ground truth.

### CBaseAnimGraph_m_skeletonInstance

- **Purpose**: Byte offset of the embedded `CSkeletonInstance` sub-object within `CBaseAnimGraph`-derived
  entities, used by patches/hooks that need direct field access without going through the virtual accessor.
- **Binary**: `server.dll` / `libserver.so`
- **Type**: struct member offset (not a pointer necessarily — may be an embedded value sub-object).

### CSkeletonInstance_m_animationController

- **Purpose**: Byte offset of the `CAnimationController` member within `CSkeletonInstance`, used by patches/hooks
  that manipulate animation playback state directly.
- **Binary**: `server.dll` / `libserver.so`
- **Type**: struct member offset.

## Discovery Strategy

1. `CGameSceneNode_GetSkeletonInstance`'s slot index (13) is already known from
   `FUNC_VTABLE_RELATIONS = [("CGameSceneNode_GetSkeletonInstance", "CGameSceneNode")]`, so the only work is an
   RTTI walk to the class's primary vtable plus a slot read — no anchor/xref search needed. The resulting stub
   (`return 0;`) is a strong behavioral confirmation independent of the address, since a null-returning base
   implementation is exactly what's expected for a scene-node accessor that only concrete skinned-node
   subclasses meaningfully override.
2. The two struct-offset siblings are data-member offsets rather than functions, so they're located via
   `/generate-signature-for-structoffset` on a concrete instruction that references `this + OFF` with the
   expected member semantics — this keeps the recipe consistent with how CounterStrikeSharp's gamedata consumes
   struct offsets (as a signature anchoring a fixed immediate, not as a bare number that could drift silently).

## Output YAML Format

The output YAML filenames depend on the platform and output kind:
- `server.dll` -> `CGameSceneNode_GetSkeletonInstance.windows.yaml`,
  `CBaseAnimGraph_m_skeletonInstance.windows.yaml`, `CSkeletonInstance_m_animationController.windows.yaml`
- `libserver.so` -> `CGameSceneNode_GetSkeletonInstance.linux.yaml`,
  `CBaseAnimGraph_m_skeletonInstance.linux.yaml`, `CSkeletonInstance_m_animationController.linux.yaml`

`CGameSceneNode_GetSkeletonInstance.{platform}.yaml` fields: `func_name`, `func_va`, `func_rva`, `func_size`,
`vtable_name`, `vfunc_offset`, `vfunc_index`.

`CBaseAnimGraph_m_skeletonInstance.{platform}.yaml` / `CSkeletonInstance_m_animationController.{platform}.yaml`
fields: `struct_name`, `member_name`, `member_offset`, `sig`, `sig_va`, `inst_offset`, `inst_length`, `inst_disp`.
