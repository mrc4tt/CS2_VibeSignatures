---
name: find-CHEGrenadeProjectile_Create
description: |
  Find and identify the CHEGrenadeProjectile_Create factory in CS2 server binary using IDA Pro MCP.
  Use this skill when reverse engineering CS2 server.dll or libserver.so to locate the HE-grenade
  projectile spawn factory. It is a non-virtual, direct-call static factory found via the entity
  classname string "hegrenade_projectile" it references (excluding the RTTI class string
  "CHEGrenadeProjectile"). Emits a unique IDA-style byte signature and a func YAML. Mirrors the
  find-CHEGrenadeProjectile_Create.py preprocessor (xref_strings FULLMATCH:hegrenade_projectile).
  Trigger: CHEGrenadeProjectile_Create, CHEGrenadeProjectile::Create, HE projectile Create
disable-model-invocation: true
---

# Find CHEGrenadeProjectile_Create

Locate `CHEGrenadeProjectile_Create` in CS2 `server.dll` or `libserver.so` using IDA Pro MCP tools.

This is a **non-virtual, direct-call static factory** (no vtable slot - emit a byte sig, not an
offset). It is found via the entity classname string `"hegrenade_projectile"` it references
(passed to the entity-create path when spawning the projectile). The RTTI/class string
`"CHEGrenadeProjectile"` is a **different** referencer and must be excluded.

## Method

### 1. Reuse previous signature (fast path)

If a prior `CHEGrenadeProjectile_Create.{platform}.yaml` exists, try its `func_sig` via
`mcp__ida-pro-mcp__find_bytes`. Single match -> resolve to function start, skip to Step 4. Else continue.

### 2. Anchor on the classname string

Locate the exact string `"hegrenade_projectile"` (FULLMATCH - not the longer
`"CHEGrenadeProjectile"` RTTI string). Take its cross-references (`mcp__ida-pro-mcp__xrefs_to`).

### 3. Identify Create among the referencers

`Create` is the referencer that spawns the projectile entity: it creates the entity by classname,
then initializes the HE-projectile fields (velocity/owner/params) and returns the new object.
Exclude any referencer reached via the `"CHEGrenadeProjectile"` RTTI string. Confirm the candidate
is the compact factory wrapper (not a large think/update routine). Record `func_addr`.

### 4. Generate signature

**ALWAYS** use SKILL `/generate-signature-for-function` with `addr=<func_addr>`. Emit IDA style
verbatim (space hex, `?` wildcards) - do NOT convert to CSS `\x2A` unless a `gamedata.json`
entry is explicitly requested.

Reference sig (sanity check only, regenerate per binary):
- linux:   `55 4C 89 C1 48 89 E5 41 57 49 89 FF 41 56 49 89 D6`
- windows: `48 89 5C 24 08 48 89 6C 24 10 48 89 74 24 18 57 48 83 EC 50 48 8B AC 24 80 00 00 00 49 8B F8`

### 5. Write func YAML

**ALWAYS** use SKILL `/write-func-as-yaml`:
- `func_name`: `CHEGrenadeProjectile_Create`
- `func_addr`: `<func_addr>`
- `func_sig`: validated sig from step 4

## Function Characteristics

- **Linkage**: non-virtual, direct-call static factory (no vtable entry)
- **Binary**: `server.dll` / `libserver.so`
- **Distinguishing trait**: references the `"hegrenade_projectile"` entity classname string;
  NOT the `"CHEGrenadeProjectile"` RTTI string

## Preprocessor pipeline equivalent

```
find-CHEGrenadeProjectile_Create   [xref_strings FULLMATCH:hegrenade_projectile,
                                     exclude_strings CHEGrenadeProjectile]
```

## Output YAML Format

- `server.dll`   -> `CHEGrenadeProjectile_Create.windows.yaml`
- `libserver.so` -> `CHEGrenadeProjectile_Create.linux.yaml`
