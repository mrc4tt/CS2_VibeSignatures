---
name: find-CDecoyProjectile_Create
description: |
  Find and identify the CDecoyProjectile_Create factory in CS2 server binary using IDA Pro MCP.
  Use this skill when reverse engineering CS2 server.dll or libserver.so to locate the decoy
  projectile spawn factory. It is a non-virtual, direct-call static factory found via the entity
  classname string "decoy_projectile" it references (excluding the RTTI class string
  "CDecoyProjectile"). Emits a unique IDA-style byte signature and a func YAML. Mirrors the
  find-CDecoyProjectile_Create.py preprocessor (xref_strings FULLMATCH:decoy_projectile).
  Trigger: CDecoyProjectile_Create, CDecoyProjectile::Create, decoy projectile Create
disable-model-invocation: true
---

# Find CDecoyProjectile_Create

Locate `CDecoyProjectile_Create` in CS2 `server.dll` or `libserver.so` using IDA Pro MCP tools.

This is a **non-virtual, direct-call static factory** (no vtable slot - emit a byte sig, not an
offset). It is found via the entity classname string `"decoy_projectile"` it references
(passed to the entity-create path when spawning the projectile). The RTTI/class string
`"CDecoyProjectile"` is a **different** referencer and must be excluded.

## Method

### 1. Reuse previous signature (fast path)

If a prior `CDecoyProjectile_Create.{platform}.yaml` exists, try its `func_sig` via
`mcp__ida-pro-mcp__find_bytes`. Single match -> resolve to function start, skip to Step 4. Else continue.

### 2. Anchor on the classname string

Locate the exact string `"decoy_projectile"` (FULLMATCH - not the longer
`"CDecoyProjectile"` RTTI string). Take its cross-references (`mcp__ida-pro-mcp__xrefs_to`).

### 3. Identify Create among the referencers

`Create` is the referencer that spawns the projectile entity: it creates the entity by classname,
then initializes the decoy-projectile fields (velocity/owner/params) and returns the new object.
Exclude any referencer reached via the `"CDecoyProjectile"` RTTI string. Confirm the candidate
is the compact factory wrapper (not a large think/update routine). Record `func_addr`.

### 4. Generate signature

**ALWAYS** use SKILL `/generate-signature-for-function` with `addr=<func_addr>`. Emit IDA style
verbatim (space hex, `?` wildcards) - do NOT convert to CSS `\x2A` unless a `gamedata.json`
entry is explicitly requested.

Reference sig (sanity check only, regenerate per binary):
- linux:   `55 4C 89 C1 48 89 E5 41 57 45 89 CF 41 56 49 89 FE 41 55 49 89 D5 48 89 F2 48 89 FE 41 54 48 8D 3D ? ? ? ? 4D 89 C4 53 48 83 EC ? E8 ? ? ? ? 45 31 C0`
- windows: `48 8B C4 55 56 48 81 EC 68 01 00 00`

### 5. Write func YAML

**ALWAYS** use SKILL `/write-func-as-yaml`:
- `func_name`: `CDecoyProjectile_Create`
- `func_addr`: `<func_addr>`
- `func_sig`: validated sig from step 4

## Function Characteristics

- **Linkage**: non-virtual, direct-call static factory (no vtable entry)
- **Binary**: `server.dll` / `libserver.so`
- **Distinguishing trait**: references the `"decoy_projectile"` entity classname string;
  NOT the `"CDecoyProjectile"` RTTI string

## Preprocessor pipeline equivalent

```
find-CDecoyProjectile_Create   [xref_strings FULLMATCH:decoy_projectile,
                                exclude_strings CDecoyProjectile]
```

## Output YAML Format

- `server.dll`   -> `CDecoyProjectile_Create.windows.yaml`
- `libserver.so` -> `CDecoyProjectile_Create.linux.yaml`
