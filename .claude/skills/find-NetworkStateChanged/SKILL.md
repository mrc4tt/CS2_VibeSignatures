---
name: find-NetworkStateChanged
description: |
  Find and identify the bare NetworkStateChanged helper function (NOT CBaseEntity_NetworkStateChanged) in the
  CS2 server binary using IDA Pro MCP. Use this skill when reverse engineering CS2 server.dll or libserver.so to
  locate this schema-property "compare old/new value, mark dirty, notify" helper via its distinctive, globally
  unique function-head byte pattern, after ruling out the light_capsule/light_omni classname-detection function
  as an indirect (non-matching) lead.
  Trigger: NetworkStateChanged
disable-model-invocation: true
---

# Find NetworkStateChanged

Locate the bare `NetworkStateChanged` helper (distinct from `CBaseEntity_NetworkStateChanged`, which has its own
config-skill/yaml) in CS2 `server.dll` / `libserver.so` using IDA Pro MCP tools.

## Method

### 1. Explore the light_capsule / light_omni Lead (string path — informative but does not directly resolve the target)

```text
mcp__ida-pro-mcp__find_regex pattern="light_capsule"
mcp__ida-pro-mcp__find_regex pattern="light_omni"
mcp__ida-pro-mcp__xrefs_to addr="<light_capsule_string_addr>"
mcp__ida-pro-mcp__xrefs_to addr="<light_omni_string_addr>"
```

Both `"light_capsule"` and `"light_omni"` (light-entity classnames) are referenced from the **same** function — a
classname-detection dispatcher that sets a light-type enum field and, under certain conditions, calls a small
setter. Decompiling this chain (dispatcher -> setter) shows a compare-old-value/store-new-value/conditionally-call
pattern, but its function-head bytes do **not** match the reference signature below, and it does not itself call
any function whose head matches either. Treat this as useful context confirming "NetworkStateChanged-style
dirty-flag helpers exist in this area of the binary", but not as the direct discovery path for this symbol.

> Linux 14168 reference: `"light_capsule"` (`0x919eec`) and `"light_omni"` (`0x9052d9`) are both referenced from
> `0xa7e260` (the classname dispatcher, size `0x156`), which conditionally calls `0xa7e160` (a per-field
> compare/store/notify setter hardcoded to byte-offset `413`). Neither of these matches the reference sig's fixed
> head bytes.

### 2. Locate the Target Directly via its Unique Function-Head Byte Pattern

Since the target is a "dirty-flag setter" template instantiation, the most reliable anchor is its distinctive
function prologue, which reads a byte from a second argument at a fixed displacement right after the standard
callee-saved-register push sequence:

```text
mcp__ida-pro-mcp__find_bytes patterns=["55 48 89 E5 41 55 41 54 53 48 89 FB 48 83 EC ?? 0F B6 7E"]
```

This pattern (`push rbp; mov rbp,rsp; push r13; push r12; push rbx; mov rbx,rdi; sub rsp,<imm8>; movzx edi, byte
ptr [rsi+<disp8>]`) is globally unique in this binary — exactly one match.

> Linux 14168 reference: unique match at `0xcd8b00` (size `0x24f`). Full head bytes:
> `55 48 89 E5 41 55 41 54 53 48 89 FB 48 83 EC 58 0F B6 7E 18 ...` (the `imm8` is `0x58`, the displacement is
> `0x18`).

### 3. Sanity-Check the Candidate

```text
mcp__ida-pro-mcp__decompile addr="0xcd8b00"
```

The candidate takes `(this, pVariantOrKeyValue)`, reads a discriminant/type-tag byte, converts the input into a
comparable value (with a dedicated fallback path logging `"No free conversion of %s variant to Color right
now\n"` for unsupported types), compares the converted value against the entity's existing stored value at a
hardcoded field offset, and — only if different — calls the entity's own vfunc at offset `0xE8` (`232`, the
schema/network dirty-state notification slot) before overwriting the stored value. This compare-then-notify shape
is exactly the "NetworkStateChanged" pattern: skip the notify call unless the value actually changed. Its sole
caller (`0xcd8d60`, string-referenced as `"SetColor"`) is a KeyValues/input-handler entry point, consistent with
a schema/property "set + mark dirty" template instantiated per networked property.

### 4. Generate Function Signature

**ALWAYS** Use SKILL `/generate-signature-for-function` with `addr=0xcd8b00` to generate a robust and unique
`func_sig`.

> Linux 14168 reference: generated signature is `55 48 89 E5 41 55 41 54 53 48 89 FB 48 83 EC ? 0F B6 7E` —
> already unique across the binary at this length (matches the `find_bytes` anchor from step 2 exactly).

### 5. Write IDA Analysis Output as YAML

**ALWAYS** Use SKILL `/write-func-as-yaml` to write the analysis results.

Required parameters:
- `func_name`: `NetworkStateChanged`
- `func_addr`: `0xcd8b00`
- `func_sig`: The validated signature from step 4

## Function Characteristics

- **Purpose**: A property-setter helper that converts an incoming variant/KeyValue to the property's native type,
  compares it against the entity's currently-stored value, and — only when the value actually changed — invokes
  the entity's dirty-state/network-notification vfunc before storing the new value. Functionally this is the
  compare-and-notify half of the "networked property changed" pattern (hence the bare `NetworkStateChanged` name,
  as opposed to `CBaseEntity_NetworkStateChanged`, which is the entity's own dirty-flag-setting virtual method
  that this helper calls into).
- **Binary**: `server.dll` / `libserver.so`
- **Parameters**: `(this, void **pVariantOrKeyValue)`.
- **Return value**: not meaningfully consumed (side-effect function).
- **Do not confuse with**: `CBaseEntity_NetworkStateChanged` (a different symbol/config-skill/yaml, the raw
  per-entity dirty-bit setter that this function calls via vtable slot `0xE8`).

## Discovery Strategy

1. The `light_capsule`/`light_omni` string lead is explored first per the source config, but it only reaches a
   classname-detection dispatcher and an unrelated per-field setter — neither matches the reference signature, so
   it is documented as a dead end rather than trusted blindly.
2. The reference signature's fixed head bytes (`push rbp/r13/r12/rbx; mov rbx,rdi; sub rsp,imm8; movzx edi, byte
   ptr [rsi+disp8]`) are distinctive enough to be searched directly as a wildcarded byte pattern and turn out to
   be globally unique in the ~40MB binary — a single `find_bytes` call resolves the target unambiguously without
   needing the string path at all.
3. Decompiling the unique hit confirms a compare-old-vs-new-then-conditionally-notify body shape consistent with
   the "NetworkStateChanged" semantic, and its only caller is a `SetColor`-style KeyValues input handler,
   consistent with this being a per-property template instantiation of a generic networked-property setter.

This is robust because the function-head byte pattern is verified globally unique on this exact binary before
being trusted, and the resulting candidate's decompiled behavior independently matches the expected
compare-then-notify semantics.

## Output YAML Format

The output YAML filename depends on the platform:
- `server.dll` -> `NetworkStateChanged.windows.yaml`
- `libserver.so` -> `NetworkStateChanged.linux.yaml`

Fields: `func_name`, `func_va`, `func_rva`, `func_size`, `func_sig`.
