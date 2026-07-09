---
name: find-GetCSWeaponDataFromKey
description: |
  Find and identify the GetCSWeaponDataFromKey free function in CS2 binary using IDA Pro MCP. Use this skill when
  reverse engineering CS2 server.dll / libserver.so to locate the weapon-schema lookup-by-string-key helper by
  scanning for its long, highly-fixed byte signature directly and confirming via decompile that it hashes a
  string key, looks it up in a global table, and validates the result against an item-definition index.
  Trigger: GetCSWeaponDataFromKey
disable-model-invocation: true
---

# Find GetCSWeaponDataFromKey

Locate `GetCSWeaponDataFromKey` in CS2 `server.dll` / `libserver.so` using IDA Pro MCP tools.

## Method

### 1. Locate via Direct Byte-Pattern Scan

This function's reference signature is long and highly fixed, making a direct whole-image scan practical without
a resolved anchor:

```text
mcp__ida-pro-mcp__find_bytes patterns=["48 85 F6 0F 84 ?? ?? ?? ?? 55 48 89 E5 41 57 41 56 41 55 49 89 F5 41 54 53 48 81 EC ?? ?? ?? ?? 80 3E ?? 75 ?? 31 C0 48 81 C4 ?? ?? ?? ?? 5B 41 5C 41 5D 41 5E 41 5F 5D C3"]
```

This returns **two** hits on the 14168 Linux binary — a sibling overload with a near-identical body needs to be
disambiguated (step 2).

### 2. Disambiguate the Two Candidates

Fetch raw bytes for both hits and diff them, then decompile both:

```text
mcp__ida-pro-mcp__get_bytes regions=[{"addr":"<hit1>","size":80}]
mcp__ida-pro-mcp__get_bytes regions=[{"addr":"<hit2>","size":80}]
mcp__ida-pro-mcp__decompile addr="<hit1>"
mcp__ida-pro-mcp__decompile addr="<hit2>"
```

Both candidates hash a string key (`a2`) via a MurmurHash2-style routine and look up the hash in a table via a
shared helper (`sub_EADAA0`-equivalent on this build), but they differ meaningfully:
- The **correct** candidate takes `(int a1, byte *a2)`, looks up the hash in a **global static table**
  (`unk_2727648`/`qword_2727650`-equivalent — a schema-wide data array, not per-object), and validates the match
  by comparing `a1` (an econ/item-definition index) against a field at `result+8` before returning the matched
  entry pointer (a `CCSWeaponBaseVData*`-shaped record). This matches "looks up a weapon-data entry from an
  item-schema key, validated against an econ item definition."
- The other candidate takes `(this, byte *a2)`, looks up in a table rooted at **`this+104`** (a per-object
  member, not a global), and returns a `const char *` (a string field at `matched_entry+24`) rather than a data
  record pointer — this is a different, unrelated string-lookup helper and must be rejected.

Confirm the fixed reference-signature bytes agree with the correct candidate at every position, including the
distinctive tail `4C 8D A5 ? ? ? ? 89 FB` (the rejected candidate has an extra REX prefix byte here — `48 89 FB`
instead of `89 FB` — because its `this` argument is 64-bit rather than the correct candidate's 32-bit `a1`, so the
tail bytes diverge and disqualify it immediately).

> Linux 14168 reference: correct candidate at `0xec4c40` (size `0x259`); rejected sibling at `0xec5b00`.

### 3. Confirm Function-Chunk Boundary

The reference signature's leading bytes (`48 85 F6 0F 84 ...`, a `test rsi,rsi; jz` check) come *before* the
`push rbp` prologue at +9. Verify this is not a cross-function-boundary artifact:

```text
mcp__ida-pro-mcp__py_eval code="import idaapi; f = idaapi.get_func(0xec4c40); print(hex(f.start_ea), hex(f.end_ea))"
```

On this build, `idaapi.get_func()` reports the **same** function (`start_ea = 0xec4c40`) for both the `test/jz`
address and the `push rbp` address at +9 — IDA's function boundary genuinely starts at the `test rsi,rsi`
instruction, not at `push rbp`. The entire reference signature (including the tail past the `5D C3` return, which
is unreachable padding/cold-path code still inside the same function, ending well before `f.end_ea`) fits inside
this single function. **`func_sig_allow_across_function_boundary` is NOT needed** for this entry on this build —
`make_signature_for_function` naturally reproduces the full reference signature byte-for-byte from this one
function.

### 4. Generate Function Signature

**ALWAYS** Use SKILL `/generate-signature-for-function` with `addr=0xec4c40` (or the equivalent resolved address
on your build) to generate a robust and unique `func_sig`.

### 5. Write IDA Analysis Output as YAML

**ALWAYS** Use SKILL `/write-func-as-yaml`.

Required parameters:
- `func_name`: `GetCSWeaponDataFromKey`
- `func_addr`: `<candidate_addr>`
- `func_sig`: The validated signature from step 4

## Function Characteristics

- **Purpose**: Free function that looks up a `CCSWeaponBaseVData`/weapon-data schema entry given a string key
  (e.g. an econ item's weapon-class key), hashing the key and validating the resulting table entry against an
  item-definition index before returning it.
- **Binary**: `server.dll` / `libserver.so`
- **Parameters**: `(int itemDefIndex, const char *pszKey)`
- **Return value**: pointer to the matched weapon-data record, or `0`/`nullptr` on hash-miss, empty-string input,
  null input, or item-definition-index mismatch.
- **Callees**: an internal MurmurHash2-style string-hash routine, plus a shared hashtable-lookup helper also used
  by a sibling (rejected) per-object string-lookup function.

## Discovery Strategy

1. The reference signature is unusually long and almost entirely fixed (few wildcard bytes), so a direct
   `find_bytes` whole-image scan is both fast and effective without needing an anchor function.
2. Two near-identical candidates exist because the sibling function shares the same hash/lookup helper pattern;
   they are disambiguated by (a) the lookup table being global vs. per-object, (b) the return type being a data
   record vs. a bare string, and (c) — most simply and mechanically — an exact byte diff against the reference
   signature's tail, which the wrong candidate fails due to a differing REX-prefix byte from its different `this`
   argument width.
3. Checking `idaapi.get_func()` on both ends of the apparent boundary (the `test/jz` head vs. the `push rbp` at
   +9) confirms the whole reference signature lives inside one function on this build, avoiding an incorrect
   assumption that `func_sig_allow_across_function_boundary` is required.

This is robust because the signature's fixed-byte density is high enough that even a large, stripped 40MB binary
produces only two candidates, and those two are cheaply and unambiguously distinguished by a short tail-byte
diff plus a global-vs-per-object table check.

## Output YAML Format

The output YAML filename depends on the platform:
- `server.dll` -> `GetCSWeaponDataFromKey.windows.yaml`
- `libserver.so` -> `GetCSWeaponDataFromKey.linux.yaml`

Fields: `func_name`, `func_va`, `func_rva`, `func_size`, `func_sig`.

> Linux 14168 reference: func_sig =
> `48 85 F6 0F 84 ? ? ? ? 55 48 89 E5 41 57 41 56 41 55 49 89 F5 41 54 53 48 81 EC ? ? ? ? 80 3E ? 75 ? 31 C0 48 81 C4 ? ? ? ? 5B 41 5C 41 5D 41 5E 41 5F 5D C3 0F 1F 80 ? ? ? ? 4C 8D A5 ? ? ? ? 89 FB`,
> `func_va = 0xec4c40`, `func_size = 0x259`. `func_sig_allow_across_function_boundary` not required (see step 3).
