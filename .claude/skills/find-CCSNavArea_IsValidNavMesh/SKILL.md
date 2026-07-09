---
name: find-CCSNavArea_IsValidNavMesh
description: |
  Find and identify the CCSNavArea_IsValidNavMesh function in CS2 server binary using IDA Pro MCP.
  Use this skill when reverse engineering CS2 server.dll or libserver.so to locate the nav-mesh
  validity predicate. It is a tiny non-virtual-looking helper that returns `g_pNavMesh != nullptr`
  (15 bytes), referenced only from a vtable slot, with no debug string of its own. Emits a unique
  IDA-style byte signature and a func YAML. Mirrors the find-CCSNavArea_IsValidNavMesh.py
  preprocessor (xref_gvs g_pNavMesh intersected with the tail signature `48 83 38 ? 0F 95 C0 C3`).
  Trigger: CCSNavArea_IsValidNavMesh, IsValidNavMesh, g_pNavMesh predicate
disable-model-invocation: true
---

# Find CCSNavArea_IsValidNavMesh

Locate `CCSNavArea_IsValidNavMesh` in CS2 `server.dll` or `libserver.so` using IDA Pro MCP tools.

This is a **direct-call** predicate (emit a byte sig, not an offset). The whole body is 15 bytes:

```
lea     rax, g_pNavMesh
cmp     qword ptr [rax], 0
setnz   al
retn
```

i.e. `return g_pNavMesh != nullptr`. It has **no debug string**, and `g_pNavMesh` has 200+
referencers, so neither anchors it alone.

**Primary resolution = the tail byte pattern** `48 83 38 ? 0F 95 C0 C3`
(`cmp [rax],0 ; setnz al ; retn`), which is **unique in `.text`**. Intersecting it with a
`g_pNavMesh` reference keeps it robust if the tail ever recurs after an update.

## Method

### 1. Reuse previous signature (fast path)

If a prior `CCSNavArea_IsValidNavMesh.{platform}.yaml` exists, try its `func_sig` via
`mcp__ida-pro-mcp__find_bytes`. Single match → resolve to function start, skip to Step 4. Else continue.

### 2. Locate via the unique tail pattern

```
mcp__ida-pro-mcp__find_bytes      patterns="48 83 38 ?? 0F 95 C0 C3"
```

Exactly one match. Resolve the containing function start (`mcp__ida-pro-mcp__lookup_funcs`) —
that function is `CCSNavArea_IsValidNavMesh`. Optionally rename it.

### 3. Confirm (optional)

Decompile and confirm the body is `return g_pNavMesh != 0;` — a single `lea` to the `g_pNavMesh`
global, a `cmp [rax], 0`, `setnz al`, `retn`.

### 4. Generate signature

**ALWAYS** use SKILL `/generate-signature-for-function` with `addr=<func_addr>`. Emit IDA style
verbatim (space hex, `?` wildcards).

Reference sig (build 14165 — sanity check only, regenerate per binary):
- linux: `48 8D 05 ? ? ? ? 48 83 38 ? 0F 95 C0 C3`

### 5. Write func YAML

**ALWAYS** use SKILL `/write-func-as-yaml`:
- `func_name`: `CCSNavArea_IsValidNavMesh`
- `func_addr`: `<func_addr>`
- `func_sig`: validated sig from step 4

## Function Characteristics

- **Linkage**: direct-call predicate, referenced from a vtable slot (no string referencer)
- **Binary**: `server.dll` / `libserver.so`
- **Distinguishing trait**: unique tail `48 83 38 ? 0F 95 C0 C3`; reads the `g_pNavMesh` global

## Discovery Strategy (why this is stable across updates)

The body is the minimal "global non-null" predicate, so its byte sig is the whole function and
self-heals once re-resolved. The tail `cmp [rax],0 ; setnz al ; retn` is unique in `.text`;
intersecting with a `g_pNavMesh` reference disambiguates if the tail ever recurs.

## Preprocessor pipeline equivalent

```
find-CCSNavArea_IsValidNavMesh   [xref_gvs g_pNavMesh ∩ xref_signatures "48 83 38 ? 0F 95 C0 C3"]
```

## Output YAML Format

- `server.dll`   -> `CCSNavArea_IsValidNavMesh.windows.yaml`
- `libserver.so` -> `CCSNavArea_IsValidNavMesh.linux.yaml`
