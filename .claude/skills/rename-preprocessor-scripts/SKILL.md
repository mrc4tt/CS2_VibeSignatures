---
name: rename-preprocessor-scripts
description: |
  Rename a symbol (function, vfunc, vtable, struct member, global variable) across all
  preprocessor scripts, config.yaml entries, and existing YAML output files.
  Use when a symbol's name changes (class rename, naming-convention fix, etc.), or when
  splitting a single finder into an inline/noinline fallback chain because a helper
  de-inlined and the target's YAML stopped being produced on some gamever/platform.
disable-model-invocation: true
---

# Rename Preprocessor Scripts

Rename a symbol from `OldName` to `NewName` across all files in the preprocessor pipeline:
the Python script, `config.yaml`, and every per-gamever YAML output file under `bin/`.

## When to Use

- A symbol's name changes (e.g. class renamed from `ILoopType` to `CLoopTypeBase`)
- A naming-convention fix applies to one or more existing preprocessor scripts
- **Deinline-fix:** a single `find-X` finder must be split into an inline/noinline chain
  because a helper that used to be inlined became a separate function (de-inlined) on some
  build → see [Deinline-Fix Variant](#deinline-fix-variant-split-a-finder-into-an-inlinenoinline-chain)
  at the end of this document (it reuses the `git mv` rename mechanics below for its
  `-inlined` step)

## Inputs

| Field | Description | Example |
|-------|-------------|---------|
| **Old name** | Current symbol name to replace | `ILoopType_EngineLoop` |
| **New name** | New symbol name | `CLoopTypeBase_EngineLoop` |
| **Old class** (optional) | Old vtable class name, if applicable | `ILoopType` |
| **New class** (optional) | New vtable class name, if applicable | `CLoopTypeBase` |

> If only the symbol suffix changes (e.g. `Foo_Bar` → `Foo_Baz`) and the vtable class stays
> the same, skip the class rename steps below.

> **Multiple renames at once:** run all steps for every symbol in a single pass — batch the
> `sed` calls with multiple `-e` flags rather than doing separate passes per symbol.

---

## Step 1: Find All Affected Files

Search for every occurrence of the old name across the entire repo:

```bash
grep -r "OldName" --include="*.py" --include="*.yaml" -l
```

Expected hits fall into these categories:

| File type | Path pattern | What changes |
|-----------|-------------|--------------|
| Preprocessor script | `ida_preprocessor_scripts/find-OldName.py` | File renamed + content updated |
| config.yaml | `config.yaml` | Skill name, `expected_output`, `skip_if_exists`, symbol `name` + `alias` |
| Output YAMLs | `bin/*/client\|engine/OldName.{platform}.yaml` | File renamed + `func_name` / `vtable_name` fields |
| Reference YAMLs | `ida_preprocessor_scripts/references/**/*.yaml` | File renamed (if named after symbol) or comment strings updated |
| Test files | `tests/*.py` | Fixture data, assertions, class/method names updated |

Also check whether any **other** scripts list `OldName.{platform}.yaml` as an `expected_input`
(i.e. downstream dependents). If found, those scripts' `INHERIT_VFUNCS` / `LLM_DECOMPILE` /
`FUNC_XREFS` constants and their `config.yaml` `expected_input` entries must be updated too.

---

## Step 2: Rename the Preprocessor Script

Use `git mv` to preserve history:

```bash
git mv ida_preprocessor_scripts/find-OldName.py \
        ida_preprocessor_scripts/find-NewName.py
```

> **Compound script names:** scripts may bundle multiple symbols with `-AND-` separators
> (e.g. `find-IGameSystemFactory_Allocate-AND-IGameSystemFactory_DoesGameSystemReallocate-AND-IGameSystem_SetName.py`)
> or have an `-impl` suffix. Only rename the part that changed — leave unrelated symbol names
> and suffixes intact.

---

## Step 3: Update the Script Contents

In the renamed `.py` file, replace every occurrence of the old symbol name and old class name:

| Location | Old value | New value |
|----------|-----------|-----------|
| Module docstring | `find-OldName skill` | `find-NewName skill` |
| `INHERIT_VFUNCS` tuple (1st element) | `"OldName"` | `"NewName"` |
| `INHERIT_VFUNCS` tuple (2nd element, vtable class) | `"OldClass"` | `"NewClass"` |
| `GENERATE_YAML_DESIRED_FIELDS` key | `"OldName"` | `"NewName"` |
| `FUNC_XREFS` `func_name` field | `"OldName"` | `"NewName"` |
| `FUNC_VTABLE_RELATIONS` tuple (1st element) | `"OldName"` | `"NewName"` |
| `FUNC_VTABLE_RELATIONS` tuple (2nd element, vtable class) | `"OldClass"` | `"NewClass"` |
| `LLM_DECOMPILE` target `name` field | `"OldName"` | `"NewName"` |
| `TARGET_FUNCTION_NAMES` / `TARGET_STRUCT_MEMBER_NAMES` | `"OldName"` | `"NewName"` |

Only touch fields that are actually present in the script; skip inapplicable rows.

---

## Step 4: Update config.yaml

Four locations may need editing. Use a single `sed` invocation with multiple `-e` flags to
handle both the `_` symbol name and the `::` alias form in one pass:

```bash
sed -i \
  -e 's/OldName/NewName/g' \
  -e 's/OldClass::OldMethodSuffix/NewClass::NewMethodSuffix/g' \
  config.yaml
```

> The `alias` field uses `::` notation (`IGameSystemFactory::Allocate`), which a plain
> `s/OldName/NewName/` will **not** match because the symbol name uses `_` separators.
> Always add a separate `-e` expression for the alias form when the method suffix changes.

### 4a. Skill entry (under `skills:`)

```yaml
# Before
      - name: find-OldName
        expected_output:
          - OldName.{platform}.yaml

# After
      - name: find-NewName
        expected_output:
          - NewName.{platform}.yaml
```

`expected_input` entries are only changed if they reference `OldName.{platform}.yaml` directly.

### 4b. Symbol entry (under `symbols:`)

```yaml
# Before
      - name: OldName
        category: vfunc          # (or func / structmember / vtable / gv)
        alias:
          - OldClass::OldMethodSuffix

# After
      - name: NewName
        category: vfunc
        alias:
          - NewClass::NewMethodSuffix
```

### 4c. Downstream `expected_input` entries (if any)

If any other skill lists `OldName.{platform}.yaml` as an `expected_input`, update those entries
to `NewName.{platform}.yaml`.

### 4d. `skip_if_exists` entries (if any)

If any skill has `skip_if_exists: - OldName.{platform}.yaml`, update to `NewName.{platform}.yaml`.

---

## Step 5: Rename and Update Output YAML Files

The output YAMLs under `bin/` are **not tracked by git**, so use regular `mv`.
Adjust the subdirectory (`client` or `engine`) to match the module:

```bash
for dir in bin/*/client; do          # or bin/*/engine — check Step 1 grep output
  for platform in windows linux; do
    old="${dir}/OldName.${platform}.yaml"
    new="${dir}/NewName.${platform}.yaml"
    [ -f "$old" ] || continue
    mv "$old" "$new"
    sed -i "s/func_name: OldName/func_name: NewName/" "$new"
    sed -i "s/vtable_name: OldClass/vtable_name: NewClass/" "$new"
  done
done
```

> Other YAML fields (`vfunc_offset`, `vfunc_index`, `func_sig`, `func_va`, etc.) are
> binary-derived values and must **not** be changed.

---

## Step 6: Update Reference YAMLs (if any)

Reference YAMLs under `ida_preprocessor_scripts/references/` may need two kinds of treatment:

**A. Reference YAML named after the symbol** (e.g. `references/client/OldName.windows.yaml`):
rename the file and update its contents:

```bash
mv ida_preprocessor_scripts/references/client/OldName.windows.yaml \
   ida_preprocessor_scripts/references/client/NewName.windows.yaml
mv ida_preprocessor_scripts/references/client/OldName.linux.yaml \
   ida_preprocessor_scripts/references/client/NewName.linux.yaml
sed -i "s/OldName/NewName/g" \
  ida_preprocessor_scripts/references/client/NewName.windows.yaml \
  ida_preprocessor_scripts/references/client/NewName.linux.yaml
```

**B. Reference YAML named after a different symbol** (e.g. `references/client/IGameSystem_AddByName.windows.yaml`
contains inline comments referencing `OldName`): update contents only:

```bash
sed -i "s/OldName/NewName/g" \
  ida_preprocessor_scripts/references/client/SomeFile.windows.yaml \
  ida_preprocessor_scripts/references/client/SomeFile.linux.yaml
```

---

## Step 7: Update Test Files (if any)

Test files under `tests/` may reference `OldName` in fixture data, skill-name strings,
file-name strings, `func_vtable_relations` assertions, and test class / method names.

If the Step 1 grep found any test files, do a bulk replace first:

```bash
sed -i "s/OldName/NewName/g" tests/test_ida_analyze_bin.py tests/test_ida_preprocessor_scripts.py
```

Then check for remaining stale vtable-class references in `func_vtable_relations` assertions
(the bulk replace will have renamed the symbol but not the class):

```bash
grep -n "func_vtable_relations.*OldClass" tests/test_ida_preprocessor_scripts.py
```

Fix any hits manually: `("NewName", "OldClass")` → `("NewName", "NewClass")`.

---

## Step 8: Update Downstream Script Contents (if any)

If any other preprocessor scripts reference `OldName` (e.g. in `INHERIT_VFUNCS` as the
`base_vfunc_name`, or in `LLM_DECOMPILE` as a predecessor), update those references to
`NewName` in their `.py` source and in their `config.yaml` `expected_input` entries.

> **`INHERIT_VFUNCS` `base_vfunc_name` gotcha:** the 3rd element of the tuple is a path like
> `"../client/OldName"` (without `.yaml`). A grep on the full symbol name will find it, but
> a sed that only matches `OldName.{platform}.yaml` will not. Make sure the plain
> `s/OldName/NewName/g` pass covers it.

---

## Step 9: Verify

Run a final grep to confirm no stale references remain:

```bash
grep -r "OldName" --include="*.py" --include="*.yaml"
```

The only acceptable remaining hits are comments or documentation that explicitly reference
the old name for historical context.

---

## Step 10: Commit

Stage all tracked changes and commit:

```bash
git add <all modified/renamed tracked files>
git commit -m "Rename OldName to NewName across preprocessor scripts"
```

> The `bin/` output YAMLs are untracked — they will not appear in the commit, which is expected.

---

## Checklist

- [ ] Old Python file removed / renamed via `git mv`
- [ ] New Python file has all `OldName` / `OldClass` occurrences replaced
- [ ] `config.yaml` skill `name` and `expected_output` updated
- [ ] `config.yaml` symbol `name` and `alias` updated (alias uses `::` — needs separate sed expression)
- [ ] `config.yaml` downstream `expected_input` entries updated (if any)
- [ ] `config.yaml` `skip_if_exists` entries updated (if any)
- [ ] All `bin/*/OldName.*.yaml` files renamed to `NewName.*.yaml`
- [ ] `func_name` (and `vtable_name`) fields inside output YAMLs updated
- [ ] Reference YAMLs in `ida_preprocessor_scripts/references/` renamed and/or updated (if any)
- [ ] Test files in `tests/` bulk-replaced; vtable class in assertions corrected (if any)
- [ ] Downstream preprocessor script `.py` and `config.yaml` entries updated (if any)
- [ ] Final grep shows zero stale references
- [ ] All changes committed to git

---

## Real-World Examples

### Simple (no reference YAMLs or tests)

**User says:** Rename `ILoopType_EngineLoop` to `CLoopTypeBase_EngineLoop`.

**Affected files found:**
- `ida_preprocessor_scripts/find-ILoopType_EngineLoop.py`
- `config.yaml` (skill entry, symbol entry)
- `bin/14141c/engine/ILoopType_EngineLoop.{windows,linux}.yaml`
- `bin/14150d/engine/ILoopType_EngineLoop.{windows,linux}.yaml`
- `bin/14151/engine/ILoopType_EngineLoop.{windows,linux}.yaml`
- `bin/14152/engine/ILoopType_EngineLoop.{windows,linux}.yaml`

No downstream dependents, no reference YAMLs, no test files hit.

**Changes made:**

1. `git mv find-ILoopType_EngineLoop.py find-CLoopTypeBase_EngineLoop.py`
2. In the renamed script:
   - Docstring: `find-ILoopType_EngineLoop` → `find-CLoopTypeBase_EngineLoop`
   - `INHERIT_VFUNCS`: `("ILoopType_EngineLoop", "ILoopType", ...)` → `("CLoopTypeBase_EngineLoop", "CLoopTypeBase", ...)`
   - `GENERATE_YAML_DESIRED_FIELDS` key: `"ILoopType_EngineLoop"` → `"CLoopTypeBase_EngineLoop"`
3. `config.yaml` skill: `find-ILoopType_EngineLoop` / `ILoopType_EngineLoop.{platform}.yaml` → new names
4. `config.yaml` symbol: `name: ILoopType_EngineLoop`, `alias: ILoopType::EngineLoop` → new names
5. `mv` all 8 YAML files; `sed -i` updated `func_name` and `vtable_name` in each

---

### Complex (reference YAMLs, test files, skip_if_exists)

**User says:** Rename `ILoopType_DeallocateLoopMode` to `CLoopTypeBase_DeallocateLoopMode`.

**Affected files found:**
- `ida_preprocessor_scripts/find-ILoopType_DeallocateLoopMode.py`
- `config.yaml` (`skip_if_exists` in `find-CEngineServiceMgr_DeactivateLoop`, skill entry, symbol entry)
- `bin/14141c/engine/ILoopType_DeallocateLoopMode.{windows,linux}.yaml` (and 3 more gamevers)
- `ida_preprocessor_scripts/references/engine/CEngineServiceMgr_DeactivateLoop.{windows,linux}.yaml`
- `tests/test_ida_analyze_bin.py`
- `tests/test_ida_preprocessor_scripts.py`

**Changes made:**

1. `git mv find-ILoopType_DeallocateLoopMode.py find-CLoopTypeBase_DeallocateLoopMode.py`
2. In the renamed script (bulk replace then fix vtable class):
   - All `ILoopType_DeallocateLoopMode` → `CLoopTypeBase_DeallocateLoopMode`
   - `FUNC_VTABLE_RELATIONS`: `("CLoopTypeBase_DeallocateLoopMode", "ILoopType")` → `(..., "CLoopTypeBase")`
3. `config.yaml`: `skip_if_exists` entry + skill entry + symbol entry all updated
4. `mv` all 8 YAML files; `sed -i` updated `func_name` and `vtable_name` in each
5. `sed -i` on both reference YAML files (comments in IDA disassembly snippets)
6. `sed -i` bulk replace across both test files; then manually fixed `func_vtable_relations`
   assertion: `("CLoopTypeBase_DeallocateLoopMode", "ILoopType")` → `(..., "CLoopTypeBase")`

---

### Batch (two renames at once, compound script name, downstream INHERIT_VFUNCS, reference YAML rename)

**User says:** Rename `IGameSystemFactory_Allocate` → `IGameSystemFactory_CreateGameSystem`
and `IGameSystemFactory_Deallocate` → `IGameSystemFactory_DestroyGameSystem`.

**Affected files found (both symbols combined):**
- `ida_preprocessor_scripts/find-IGameSystemFactory_Allocate-AND-IGameSystemFactory_DoesGameSystemReallocate-AND-IGameSystem_SetName.py`
- `ida_preprocessor_scripts/find-IGameSystem_GetName-AND-IGameSystemFactory_Deallocate.py`
- `config.yaml` (2 skill entries, 2 symbol entries, 1 downstream `expected_input`)
- `bin/*/client/IGameSystemFactory_Allocate.{platform}.yaml` (34 files)
- `bin/*/client/IGameSystemFactory_Deallocate.{platform}.yaml` (34 files)
- `ida_preprocessor_scripts/references/client/IGameSystem_AddByName.{windows,linux}.yaml` (content only)
- `ida_preprocessor_scripts/references/client/IGameSystem_DestroyAllGameSystems.{windows,linux}.yaml` (content only)
- `ida_preprocessor_scripts/find-CGameSystemReallocatingFactory_CSpawnGroupMgrGameSystem_DestroyGameSystem-impl.py`
  (downstream: `INHERIT_VFUNCS` `base_vfunc_name` = `"../client/IGameSystemFactory_Deallocate"`)
- `tests/test_ida_preprocessor_scripts.py`

**Key observations:**

- The Allocate script name is compound (`-AND-`): only `IGameSystemFactory_Allocate` changes in
  the filename, the rest stays.
- `config.yaml` aliases are `IGameSystemFactory::Allocate` / `IGameSystemFactory::Deallocate` —
  a plain `s/IGameSystemFactory_Allocate/...` sed will not touch them; need separate `-e` clauses:
  ```bash
  sed -i \
    -e 's/IGameSystemFactory_Allocate/IGameSystemFactory_CreateGameSystem/g' \
    -e 's/IGameSystemFactory::Allocate/IGameSystemFactory::CreateGameSystem/g' \
    -e 's/IGameSystemFactory_Deallocate/IGameSystemFactory_DestroyGameSystem/g' \
    -e 's/IGameSystemFactory::Deallocate/IGameSystemFactory::DestroyGameSystem/g' \
    config.yaml
  ```
- The downstream script's `INHERIT_VFUNCS` has `base_vfunc_name = "../client/IGameSystemFactory_Deallocate"` —
  a plain `s/IGameSystemFactory_Deallocate/IGameSystemFactory_DestroyGameSystem/g` on that file catches it.
- Reference YAMLs for these symbols are named after a different symbol (AddByName, DestroyAllGameSystems) —
  content-only update, no file rename needed.
- Both renames were batched in a single commit.

---

## Deinline-Fix Variant: Split a Finder into an Inline/Noinline Chain

A helper function that CS2 **inlines into its caller on some builds but compiles as a
separate function on others** (the compiler flips this across gamevers/platforms) breaks a
single-skill finder. Once the helper de-inlines, the anchor it carried — the debug string
it owns, or the call the target made into it — moves out of the target, so `find-X` stops
producing `X.{platform}.yaml` on that build. Because `ida_analyze_bin.py` is fail-fast, the
rest of that module then aborts.

**Symptom:** `X.{platform}.yaml` is present for older gamevers / one platform but missing
for the newest gamever / other platform, and the module run aborts partway through.

**Fix:** replace the single `find-X` skill with a **3-skill fallback chain**. The original
finder is renamed to `find-X-inlined` — use the Step 1–3 `git mv` + content-update mechanics
above for that part — and two new skills are added around it. (Reference chains: ChangeLevel,
CLoopTypeClientServer_DeactivateLoop, CMsgSource2NetworkFlowQuality_PrintStats.)

### The 3-skill chain

| Skill | Role | `func_xrefs` positive source | config.yaml fields |
|-------|------|------------------------------|--------------------|
| `find-Helper` | resolve the de-inlined helper | `xref_strings` on the helper's own debug string (or `xref_funcs` on a stable callee) | `optional_output: Helper` + `skip_if_exists: X` — **no** `expected_input` |
| `find-X-noinline` | resolve X as the helper's caller | `xref_funcs: [Helper]` (+ `func_vtable_relations` if X is a vfunc) | `optional_output: X` + `expected_input: <vtable>` (if vfunc) + `prerequisite: [find-Helper]` |
| `find-X-inlined` | the ORIGINAL finder, renamed | unchanged from the original (`xref_strings`/`xref_funcs` on the anchor) | `expected_output: X` + `expected_input: <vtable>` + `skip_if_exists: X` + `prerequisite: [find-X-noinline]` |

Order the three entries in `config.yaml` exactly as above (Helper → -noinline → -inlined).
The vanilla chain is **cross-platform** — no `platform:` field. (The inverted variant below
may need one.)

### How each build resolves

- **De-inlined build:** `find-Helper` finds the standalone helper by its anchor;
  `find-X-noinline` finds X as the (vtable-filtered) caller of that helper. `find-X-inlined`
  skips (`X` already exists).
- **Inlined build:** the anchor lives inside X, so `find-Helper` resolves to **X's own
  address** (harmless — see rules); `find-X-noinline` finds no callers but re-selects X via
  the **vtable-self fallback** (`func_xrefs` uses the callee itself when it has no callers but
  its address is in the target vtable). `find-X-inlined` skips.
- **Ambiguous inlined anchor** (the inlined string has >1 xref): `find-Helper` and
  `find-X-noinline` both soft-skip, and `find-X-inlined`'s string∩vtable intersection is the
  load-bearing path — which is exactly why the original finder must stay in the chain.

### Key rules

- **`optional_output`, not `expected_output`, on Helper and -noinline.** They must *soft-skip*
  (not hard-fail) when their path doesn't apply, so control falls through to the next skill.
  Only `find-X-inlined` carries `expected_output`.
- **Depend on the helper via `prerequisite`, never `expected_input`.** The helper is optional
  and may be absent; a missing `expected_input` hard-fails. Put the *vtable* in `expected_input`.
- **Do NOT register `Helper` as a gamedata `symbol`.** In the inlined case its YAML points at
  X's own address, which would be a wrong gamedata entry. It is an intermediate only.
- **`func_sig` keep/drop** (apply the same choice to **both** -noinline and -inlined so X's
  output shape does not flip per build):
  - vfunc with a **substantial** de-inlined body → **keep** `func_sig` (it signs uniquely;
    e.g. ChangeLevel, DirectUpdate).
  - vfunc that de-inlines to a **tiny forwarding thunk** → **drop** `func_sig` on both paths
    (the head bytes aren't unique; the vtable slot `vfunc_offset`/`vfunc_index` is the stable
    locator; e.g. DeactivateLoop, RegisterEventMap). Keep `func_name, func_va, func_rva,
    func_size, vtable_name, vfunc_offset, vfunc_index`.
  - regular func (no vtable) → **keep** `func_sig` on all three (it is the only stable locator).

### Validate on BOTH inline states

`bin/*.yaml` are gitignored, so regenerating is free. Validate in isolation with a scratch
config and `-oldgamever none` (forces the xref paths; version reuse would short-circuit
-noinline):

```bash
# _scratch.yaml = just this module (real path_windows/path_linux) + the 3 new skills + X's symbol entry
rm -f bin/<inlined_ver>/<mod>/X.*.yaml bin/<deinlined_ver>/<mod>/X.*.yaml   # force the chain to run
uv run ida_analyze_bin.py -configyaml=_scratch.yaml -gamever <deinlined_ver> -modules=<mod> -oldgamever none -maxretry 1 -debug
uv run ida_analyze_bin.py -configyaml=_scratch.yaml -gamever <inlined_ver>  -modules=<mod> -oldgamever none -maxretry 1 -debug
```

Confirm **both** gamevers × **both** platforms resolve X to the same vtable slot (or
`func_sig`) with `Failed 0`. Delete `_scratch.yaml` before committing.

### Worked example: `CNetworkGameServer_DirectUpdate` (engine, 14168)

`CNetworkStringTableContainer::DirectUpdate` (owns the `"CNetworkStringTableContainer::DirectUpdate"`
VProf string) de-inlined out of the `CNetworkGameServer::DirectUpdate` vfunc on Linux at
14168, so the string left the vfunc and `CNetworkGameServer_DirectUpdate.linux.yaml` stopped
building.

1. `git mv find-CNetworkGameServer_DirectUpdate.py find-CNetworkGameServer_DirectUpdate-inlined.py`
   (original = `xref_strings` on the VProf string + `CNetworkGameServer_vtable`); update its docstring.
2. New `find-CNetworkStringTableContainer_DirectUpdate.py`: `xref_strings` on the same string;
   fields `func_name/func_sig/func_va/func_rva/func_size`.
3. New `find-CNetworkGameServer_DirectUpdate-noinline.py`:
   `xref_funcs: ["CNetworkStringTableContainer_DirectUpdate"]` +
   `func_vtable_relations: [(…, "CNetworkGameServer_vtable")]`; **kept** `func_sig` (substantial body).
4. `config.yaml`: replaced the one skill entry with the 3-skill chain; left the
   `CNetworkGameServer_DirectUpdate` symbol entry as-is; did NOT add a helper symbol.
5. Validated 14167 (inlined) + 14168 (Linux de-inlined) × win/linux, `-oldgamever none`: all
   four → vtable index 59 / offset 0x1d8, `Failed 0` (14168 Linux de-inlined body signs at 7
   bytes `83 7F ?? ?? 76 ?? 55` = the `m_nMaxClients > 1` guard).

### Inverted topology (string-LESS guard wrapper)

If the de-inline instead splits a thin **string-less guard wrapper** off a string-heavy body
(the public function is the wrapper; the body keeps the string — e.g.
`CMsgSource2NetworkFlowQuality_PrintStats`), the vanilla recipe mis-resolves: skill 1 finds
the body on *both* builds and the -noinline target has no anchor but the body as its only
named callee, so it collides with structurally-identical vtable-mates. Extra handling:
`find-Helper` is `platform:`-scoped and unregistered; `find-X-noinline` adds a guard-thunk
`xref_signatures` (a positive identity unique to the extracted wrapper) plus
`exclude_funcs`/`exclude_callees` for the colliders. Treat this as a special case and diff
against the `PrintStats` chain before writing it.

### Deinline-fix checklist (in addition to the rename checklist)

- [ ] Original finder `git mv`'d to `find-X-inlined` + docstring updated
- [ ] `find-Helper` created (`optional_output`, `skip_if_exists: X`, no `expected_input`, unregistered symbol)
- [ ] `find-X-noinline` created (`xref_funcs: [Helper]` + vtable if vfunc; `optional_output`, `prerequisite: [find-Helper]`)
- [ ] `find-X-inlined` config = `expected_output` + `skip_if_exists` + `prerequisite: [find-X-noinline]`
- [ ] `func_sig` kept/dropped consistently on both -noinline and -inlined per the rule above
- [ ] Helper NOT added as a gamedata `symbol`
- [ ] `config.yaml` entries ordered Helper → -noinline → -inlined
- [ ] Validated on an inlined AND a de-inlined gamever, both platforms, `-oldgamever none`, `Failed 0`
- [ ] Scratch config deleted; only the 3 skill files + `config.yaml` committed
