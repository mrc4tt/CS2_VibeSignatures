---
name: find-CAttributeList_SetOrAddAttributeValueByName
description: |
  Find and identify the CAttributeList_SetOrAddAttributeValueByName function in CS2 server binary using
  IDA Pro MCP. Use this skill when reverse engineering CS2 server.dll or libserver.so to locate the econ
  attribute-list workhorse that sets an existing float attribute by name or appends a new one. Resolved
  via a durable caller anchor: the weapon paint-kit/wear/seed/kill-eater applier function, which is itself
  located by the literal econ keyvalue-system strings "set item texture prefab" / "set item texture wear"
  / "set item texture seed". This function backs weaponpaints-style plugins that programmatically set an
  econ item's paint kit / wear / seed / stickers.
  Trigger: CAttributeList_SetOrAddAttributeValueByName, SetOrAddAttributeValueByName
disable-model-invocation: true
---

# Find CAttributeList_SetOrAddAttributeValueByName

Locate `CAttributeList_SetOrAddAttributeValueByName` in CS2 `server.dll` or `libserver.so` using IDA Pro
MCP tools.

This is a **non-virtual, direct-call** member function reached through a tiny `this`-adjustor thunk (no
vtable entry of its own — emit a byte sig, not an offset).

> **Do not** anchor the discovery recipe on the raw byte pattern below — bytes/wildcards shift release to
> release. Use it only to *locate/confirm* the function on the currently loaded binary, then generate a
> fresh signature at the end.

## Method

### 1. Locate the durable anchor strings

`CAttributeList_SetOrAddAttributeValueByName` has no distinctive string of its own (it's a generic
hash-lookup + set/append routine), but its **caller** is the weapon econ-attribute applier used by CS2's
own give/equip-weapon code path, and that caller references several literal econ keyvalue strings:

```
mcp__ida-pro-mcp__find       type="string" targets=["set item texture prefab"]
mcp__ida-pro-mcp__xrefs_to   addrs="<string_va>"
```

`"set item texture prefab"` has exactly one code referencer. That containing function (call it the
**paint-kit applier**) also references the sibling literals `"set item texture wear"`, `"set item texture
seed"`, `"kill eater score type"`, and `"kill eater"` — this combination is a very strong, semantically
durable fingerprint for "the function that programmatically stamps paint-kit/wear/seed/kill-eater
attributes onto a weapon econ item", independent of its address or body shape.

> Linux 14168 reference: the string `"set item texture prefab"` is referenced only from `sub_1A9A070`
> (VA `0x1a9a070`, size `0x394`).

### 2. Read off the call sites inside the paint-kit applier

```
mcp__ida-pro-mcp__decompile addr="<paint_kit_applier_func_va>"
```

Inside, look for (typically) five calls of the shape `helper(pAttributeListView, "<attr-name-literal>",
<float-or-int-value>)`:

```c
helper(v12, "set item texture prefab", (float)*(int *)(a2 + 120));
helper(v12, "set item texture wear",   *(float *)(a2 + 132));
helper(v12, "set item texture seed",   (float)*(int *)(a2 + 136));
helper(v12, "kill eater score type",   *(float *)(a2 + 140));  // only when a flag bit is set
helper(v12, "kill eater",              *(float *)(a2 + 144));  // only when a flag bit is set
```

`helper` is **not** the target itself — on Linux it is a tiny 2-instruction `this`-adjustor thunk:

```
add rdi, 0x70      ; adjust `this` from CEconItemView-ish base to the embedded CAttributeList member
jmp  <real_target>
```

Follow the `jmp` — its destination is `CAttributeList_SetOrAddAttributeValueByName`.

> Linux 14168 reference: `helper` is `sub_1B598E0` (`add rdi, 70h; jmp sub_1B59720`), and the real target
> is `sub_1B59720` (VA `0x1b59720`, size `0x1b5`).

### 3. Confirm the target function's shape

Decompile the jmp target and confirm it matches:

```c
__int64 __fastcall SetOrAddAttributeValueByName(CAttributeList *this, const char *pszAttribName, float flValue)
{
  pAttribDef = LookupAttributeDefinitionBySymbol(pszAttribName); // via a global symbol table
  if (!pAttribDef) return 0;
  for (each existing CEconItemAttribute entry in this->m_Attributes)
    if (entry's attribute-definition-index matches pAttribDef's index)
    {
      if (entry.value != flValue) { OnAttributeChanged(...); entry.value = flValue; }
      return ...;
    }
  // not found: construct a new attribute pair and append it to this->m_Attributes
  ConstructAttribute(&tmp, pAttribDef->index, flValue);
  AppendAttribute(this, &tmp);
  return ...;
}
```

Identification rules:
1. Takes `(this, const char *pszAttribName, float flValue)` — a name string plus a float value.
2. First does a hash/symbol lookup of `pszAttribName` into a global attribute-definition table.
3. Loops over the object's existing attribute array comparing each entry's definition pointer/index; on
   a match, conditionally fires a change callback and overwrites the value in place.
4. If no existing entry matches, constructs a new `(index, value)` pair and appends it to the list,
   growing/reallocating via the engine's memory allocator (`g_pMemAlloc`) if needed.

### 4. Generate function signature

**ALWAYS** use SKILL `/generate-signature-for-function` with `addr=<real_target_func_addr>`. Emit IDA
style verbatim (space hex, `?` wildcards).

Reference sig (Linux 14168 build — sanity check only, regenerate per binary):
`55 48 89 E5 41 57 41 56 49 89 FE 41 55 41 54 53 48 89 F3 48 83 EC ? F3 0F 11 85`

(Last-resort fallback note: if no better anchor is available on some future binary, `find_bytes` with
this reference pattern can locate the function directly one-shot — its prologue is distinctive enough on
its own — but prefer the string/caller anchor above since it survives compiler/prologue changes better.)

### 5. Write func YAML

**ALWAYS** use SKILL `/write-func-as-yaml`:
- `func_name`: `CAttributeList_SetOrAddAttributeValueByName`
- `func_addr`: `<real_target_func_addr>`
- `func_sig`: validated sig from step 4

## Function Characteristics

- **Purpose**: Part of CS2's econ "attribute list" system (`CAttributeList` / `CEconItemAttributeDefinition`-
  adjacent). Sets an existing attribute's value by its string name, or appends a new attribute entry if
  none exists yet. This is the workhorse used by any code that programmatically sets paint-kit/wear/seed/
  kill-eater/etc attributes on an econ item's attribute list — including weaponpaints-style plugins.
- **Linkage**: non-virtual, direct-call (no vtable entry); reached in practice through a `this`-adjustor
  thunk from `CEconItemView`-shaped callers.
- **Binary**: `server.dll` / `libserver.so`
- **Parameters**: `(this /* CAttributeList* */, const char *pszAttribName, float flValue)`
- **Return value**: implementation-defined status/attribute pointer (callers largely ignore it besides
  truthiness checks)

## Discovery Strategy

1. The target itself has no unique string, so anchor on its **caller's** literal econ-keyvalue strings —
   `"set item texture prefab"` has exactly one code referencer in the whole module, and that referencer is
   semantically stable (it is CS2's own paint-kit/wear/seed/kill-eater weapon-attribute applier, a
   first-party gameplay routine unlikely to disappear across updates).
2. From that caller, every call into the attribute-setter helper passes a literal attribute-name string as
   its second argument — a very strong, code-shape-independent fingerprint (`helper(this, "<literal>",
   value)`, repeated for each of the five known econ attribute names).
3. On Linux the immediate call target is a two-instruction `this`-adjustor thunk (`add rdi, N; jmp real`);
   simply follow the unconditional jump to reach the real function.
4. Confirm via body shape (symbol/hash lookup of the name argument, existing-attribute scan-and-update,
   append-if-missing fallback) — this is independent of exact byte offsets and survives reordering/inlining
   changes across builds.
5. Re-generate the byte signature fresh from the resolved function each time, rather than hard-coding one.

This is robust because the anchor strings are first-party gameplay literals (not debug-only strings that
could be stripped in release builds), the caller's "distinctive literal string as 2nd argument" call shape
is compiler-agnostic, and the final signature is always regenerated rather than pinned.

## Output YAML Format

- `server.dll`   -> `CAttributeList_SetOrAddAttributeValueByName.windows.yaml`
- `libserver.so` -> `CAttributeList_SetOrAddAttributeValueByName.linux.yaml`

Fields: `func_name`, `func_va`, `func_rva`, `func_size`, `func_sig`.
