---
name: find-CMolotovProjectile_Create
description: |
  Find and identify the CMolotovProjectile_Create factory in CS2 server binary using IDA Pro MCP.
  Use this skill when reverse engineering CS2 server.dll or libserver.so to locate the molotov
  projectile spawn factory. It is a non-virtual, direct-call static factory found via the entity
  classname string "molotov_projectile" it references (excluding the RTTI class string
  "CMolotovProjectile"). Emits a unique IDA-style byte signature and a func YAML. Mirrors the
  find-CMolotovProjectile_Create.py preprocessor (xref_strings FULLMATCH:molotov_projectile).
  Trigger: CMolotovProjectile_Create, CMolotovProjectile::Create, molotov projectile Create
disable-model-invocation: true
---

# Find CMolotovProjectile_Create

Locate `CMolotovProjectile_Create` in CS2 `server.dll` or `libserver.so` using IDA Pro MCP tools.

This is a **non-virtual, direct-call static factory** (no vtable slot - emit a byte sig, not an
offset). It is found via the entity classname string `"molotov_projectile"` it references
(passed to the entity-create path when spawning the projectile). The RTTI/class string
`"CMolotovProjectile"` is a **different** referencer and must be excluded.

## Method

### 1. Reuse previous signature (fast path)

If a prior `CMolotovProjectile_Create.{platform}.yaml` exists, try its `func_sig` via
`mcp__ida-pro-mcp__find_bytes`. Single match -> resolve to function start, skip to Step 4. Else continue.

### 2. Anchor on the classname string

Locate the exact string `"molotov_projectile"` (FULLMATCH - not the longer
`"CMolotovProjectile"` RTTI string). Take its cross-references (`mcp__ida-pro-mcp__xrefs_to`).

### 3. Identify Create among the referencers

`Create` is the referencer that spawns the projectile entity: it creates the entity by classname,
then initializes the molotov-projectile fields (velocity/owner/params) and returns the new object.
Exclude any referencer reached via the `"CMolotovProjectile"` RTTI string. Confirm the candidate
is the compact factory wrapper (not a large think/update routine). Record `func_addr`.

Note: molotov and incendiary share projectile machinery - make sure the anchor string is exactly
`"molotov_projectile"` and the resolved factory returns a `CMolotovProjectile`.

### 4. Generate signature

**ALWAYS** use SKILL `/generate-signature-for-function` with `addr=<func_addr>`. Emit IDA style
verbatim (space hex, `?` wildcards) - do NOT convert to CSS `\x2A` unless a `gamedata.json`
entry is explicitly requested.

Reference sig (sanity check only, regenerate per binary):
- linux:   `55 48 8D 05 ? ? ? ? 48 89 E5 41 57 41 56 41 55 41 54 49 89 FC 53 48 81 EC ? ? ? ? 4C 8D 35 ? ? ? ?`
- windows: `48 8B C4 48 89 58 10 4C 89 40 18 48 89 48 08`

### 5. Write func YAML

**ALWAYS** use SKILL `/write-func-as-yaml`:
- `func_name`: `CMolotovProjectile_Create`
- `func_addr`: `<func_addr>`
- `func_sig`: validated sig from step 4

## Function Characteristics

- **Linkage**: non-virtual, direct-call static factory (no vtable entry)
- **Binary**: `server.dll` / `libserver.so`
- **Distinguishing trait**: references the `"molotov_projectile"` entity classname string;
  NOT the `"CMolotovProjectile"` RTTI string

## Preprocessor pipeline equivalent

```
find-CMolotovProjectile_Create   [xref_strings FULLMATCH:molotov_projectile,
                                   exclude_strings CMolotovProjectile]
```

## Output YAML Format

- `server.dll`   -> `CMolotovProjectile_Create.windows.yaml`
- `libserver.so` -> `CMolotovProjectile_Create.linux.yaml`
