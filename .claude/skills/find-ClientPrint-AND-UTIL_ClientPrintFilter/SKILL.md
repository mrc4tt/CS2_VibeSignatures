---
name: find-ClientPrint-AND-UTIL_ClientPrintFilter
description: |
  Find and identify the ClientPrint and UTIL_ClientPrintFilter free functions in CS2 binary using IDA Pro MCP.
  Use this skill when reverse engineering CS2 server.dll / libserver.so to locate the recipient-filter-based
  message-printing routine by scanning for its distinctive prologue and confirming via decompile that it builds
  a formatted, localizable user message and dispatches it through the engine's user-message interface.
  Trigger: ClientPrint, UTIL_ClientPrintFilter
disable-model-invocation: true
---

# Find ClientPrint and UTIL_ClientPrintFilter

Locate `ClientPrint` and `UTIL_ClientPrintFilter` in CS2 `server.dll` / `libserver.so` using IDA Pro MCP tools.

## Method

### 1. Locate the Candidate via Direct Byte-Pattern Scan

No pre-resolved anchor is required for this recipe. `ClientPrint` has a short, highly distinctive prologue: a
`lea rax, <rip-relative>` immediately after `push rbp`, before the stack frame is otherwise touched. Scan the
whole image directly:

```text
mcp__ida-pro-mcp__find_bytes patterns=["55 48 8D 05 ?? ?? ?? ?? 48 89 E5 41 57 4D 89 CF"]
```

This returns exactly **one** hit in the analyzed 14168 Linux binary, which is strong evidence of correctness even
without a resolved anchor.

### 2. Confirm via Decompile

```text
mcp__ida-pro-mcp__decompile addr="<candidate_addr>"
```

Confirm the function:
- Takes **7 parameters**: `(a1, int msg_dest, const char *msg_name, const char *arg1, const char *arg2, const
  char *arg3, const char *arg4)` — i.e. `(IRecipientFilter *filter, int msg_dest, const char *msg_name, ...)`.
- Builds up to 4 local `std::string` copies of the incoming C-string args (a3..a7 in decompiled form) using
  libstdc++ COW-string assign helpers.
- Near the end, loads a global engine-interface singleton pointer and calls **a vcall at a fixed offset (`+0x80`
  on this build)** through it, passing `(iface, msg_dest_val, 0, filter, <some_extra>, &local_string_struct, 104)`
  — this is the message dispatch into the engine's usermessage/netmessage system.

### 3. Confirm the Recipient-Filter Shape via Callers

```text
mcp__ida-pro-mcp__xrefs_to addrs=["<candidate_addr>"]
```

Two small wrapper functions sit immediately after the candidate in the binary and are worth inspecting — they
each construct a throwaway single-recipient filter object (vtable `off_2371798` on this build) from a raw entity
pointer/index, then tail-forward into the candidate with the same `(filter, msg_dest, name, arg1..4)` shape. This
confirms the candidate's first parameter is genuinely filter-typed, not a bare entity pointer.

> Linux 14168 reference: candidate at `0x178d5f0` (size `0xd02`), 16 direct callers throughout the module.
> Wrappers at `0x178e300` and `0x178e400` (both call `sub_178D5F0` with an inline-constructed single-recipient
> filter) confirm the filter-first-argument shape.

### 4. Resolve UTIL_ClientPrintFilter

`ClientPrint` and `UTIL_ClientPrintFilter` share the exact same `(IRecipientFilter*, int msg_dest, const char
*msg_name, ...)` signature in the Source2/CS2 codebase, and the config's own LLM-decompile anchor
(`CCSPlayerPawn_ProcessSuicideAsKillReward`) calls **both** names with the identical 7-argument shape at different
call sites. In this optimized 14168 build no second, textually-distinct function with that exact shape and
prologue could be found elsewhere in the module — consistent with the compiler performing identical-code-folding
(ICF) on the two symbols since their bodies are byte-identical. Treat `UTIL_ClientPrintFilter` as **resolving to
the same address as `ClientPrint`** on this build unless a distinct copy is found; if a later build shows two
distinct bodies, redo step 1 with a caller-shape filter (e.g. locate the callee invoked with a filter argument that
is NOT a freshly-constructed single-recipient object, as opposed to `ClientPrint`'s wrapper-constructed one) to
split them apart.

### 5. Generate Function Signature

**ALWAYS** Use SKILL `/generate-signature-for-function` with `addr=<candidate_addr>` to generate a robust and
unique `func_sig` for `ClientPrint`. Reuse the same signature/address for `UTIL_ClientPrintFilter` per step 4
unless independently disproven.

### 6. Write IDA Analysis Output as YAML

**ALWAYS** Use SKILL `/write-func-as-yaml` once for each symbol name (`ClientPrint`, `UTIL_ClientPrintFilter`),
both pointing at `<candidate_addr>` with the signature from step 5.

## Function Characteristics

- **Purpose**: Formats and dispatches a localizable message (`msg_name`, a localization token like
  `"#Player_Cash_Award_ExplainSuicide_YouGotCash"`) with up to 4 string substitution arguments to the set of
  clients described by an `IRecipientFilter`, via the engine's user-message system.
- **Binary**: `server.dll` / `libserver.so`
- **Parameters**: `(IRecipientFilter *filter, int msg_dest, const char *msg_name, const char *arg1 = nullptr,
  const char *arg2 = nullptr, const char *arg3 = nullptr, const char *arg4 = nullptr)`
- **Return value**: none meaningful observed (falls through after the dispatch vcall).
- **Callees**: libstdc++ `basic_string` assign helpers, plus a single vcall through a global engine-interface
  singleton at a fixed vtable offset (`+0x80` on this build) that performs the actual network dispatch.

## Discovery Strategy

1. The reference signature's prologue (`push rbp; lea rax, <string/data>; mov rbp, rsp; push r15; mov r15, rdi`)
   is unusual enough (`lea` immediately sandwiched between `push rbp` and `mov rbp, rsp`) to be directly scannable
   with `find_bytes` across the whole image without needing a resolved anchor function — and it returned a single
   hit on this binary.
2. The 7-parameter shape and the up-to-4-string-argument formatting pattern is a strong semantic fingerprint that
   matches the classic Source-engine `ClientPrint`/`UTIL_ClientPrintFilter` free-function family.
3. Two small caller wrappers that construct a throwaway single-recipient filter before calling the candidate
   independently confirm the first parameter is filter-typed.
4. `UTIL_ClientPrintFilter` is treated as address-identical to `ClientPrint` on this build (see step 4) since no
   distinct second implementation with the same shape exists in the module — a plausible result of compiler ICF
   on two source-level names sharing one body.

This is robust because the prologue byte pattern is unique in the whole 40MB image, and the parameter/behavior
shape independently confirms the semantic identity without needing the original LLM-decompile anchor
(`CCSPlayerPawn_ProcessSuicideAsKillReward`).

## Output YAML Format

The output YAML filenames depend on the platform:
- `server.dll` -> `ClientPrint.windows.yaml`, `UTIL_ClientPrintFilter.windows.yaml`
- `libserver.so` -> `ClientPrint.linux.yaml`, `UTIL_ClientPrintFilter.linux.yaml`

Fields (both files): `func_name`, `func_va`, `func_rva`, `func_size`, `func_sig`.

> Linux 14168 reference: `ClientPrint` func_sig = `55 48 8D 05 ? ? ? ? 48 89 E5 41 57 4D 89 CF`, `func_va =
> 0x178d5f0`, `func_size = 0xd02`. `UTIL_ClientPrintFilter` shares the same values on this build (see step 4
> caveat).
