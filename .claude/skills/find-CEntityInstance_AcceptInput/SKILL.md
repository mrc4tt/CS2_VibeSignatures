---
name: find-CEntityInstance_AcceptInput
description: |
  Find and identify the CEntityInstance_AcceptInput function in CS2 binary using IDA Pro MCP. Use this skill when
  reverse engineering CS2 server.dll / libserver.so to locate the generic Source2 entity I/O input dispatcher by
  scanning for its distinctive short prologue directly and confirming via decompile that it forwards through the
  entity's identity pointer into an internal AcceptInputInternal-style dispatcher.
  Trigger: CEntityInstance_AcceptInput
disable-model-invocation: true
---

# Find CEntityInstance_AcceptInput

Locate `CEntityInstance_AcceptInput` in CS2 `server.dll` / `libserver.so` using IDA Pro MCP tools.

## Method

### 1. Locate via Direct Byte-Pattern Scan

`CEntityInstance::AcceptInput`'s prologue is short and distinctive (`push rbp; mov rbp, rsp; push r14; mov r14,
rdi; push r13; lea r13, [rbp+...]`), scannable directly across the whole image:

```text
mcp__ida-pro-mcp__find_bytes patterns=["55 48 89 E5 41 56 49 89 FE 41 55 48 8D 7D"]
```

This returns exactly **one** hit on the 14168 Linux binary.

### 2. Confirm via Decompile

```text
mcp__ida-pro-mcp__decompile addr="<candidate_addr>"
```

Confirm the function:
- Takes 5 parameters: `(CEntityInstance *this, const char *inputName, int a3, int a4, int a5)` — i.e.
  `(this, pszInputName, activator, caller, outputId/value)`.
- First builds a wrapped/hashed representation of `inputName` via a small helper (a `CUtlSymbol`/string-hash
  construction).
- Reads a pointer at `this + 0x10` (this build's `CEntityInstance::m_pEntity`, the owning `CEntityIdentity*`) and
  **tail-calls** into an internal dispatcher with `(identity, &wrappedInputName, activator, caller, value, 0, 0)`.
  The internal dispatcher is the sibling `CEntityIdentity_AcceptInputInternal`-family function — do **not**
  confuse the two; `CEntityInstance_AcceptInput` is the thin, 1-basic-block, 5-parameter forwarding wrapper on
  `CEntityInstance`, not the identity-level or script-level dispatcher.

> Linux 14168 reference: candidate at `0x2105860` (size `0x68`, single basic block, 27 direct callers — consistent
> with a generic per-entity-class I/O forwarding wrapper called from many places across the module).

### 3. Reject Similarly-Named Symbols

Do not accept a candidate if decompile shows any of the following shapes instead:
- **`CEntityIdentity_AcceptInput`** — takes a `CEntityIdentity*` directly as `this` rather than forwarding through
  a `+0x10` field read.
- **`CEntityIdentity_AcceptInputInternal`** — the larger callee this function tail-calls into; it does the actual
  named-input hash-table lookup and handler invocation, and is a separate, larger function.
- **`CEntityInstance_ScriptAcceptInput`** — a VScript-facing variant with a different parameter shape (typically
  script-value-boxed arguments rather than raw `int`s).

### 4. Generate Function Signature

**ALWAYS** Use SKILL `/generate-signature-for-function` with `addr=<candidate_addr>` to generate a robust and
unique `func_sig`.

### 5. Write IDA Analysis Output as YAML

**ALWAYS** Use SKILL `/write-func-as-yaml`.

Required parameters:
- `func_name`: `CEntityInstance_AcceptInput`
- `func_addr`: `<candidate_addr>`
- `func_sig`: The validated signature from step 4

## Function Characteristics

- **Purpose**: Generic Source2 entity I/O input dispatcher on `CEntityInstance` — receives a named input (e.g.
  `"Kill"`, `"Use"`), wraps it, and forwards to the owning `CEntityIdentity`'s internal input-handler lookup/
  invocation routine.
- **Binary**: `server.dll` / `libserver.so`
- **Parameters**: `(CEntityInstance *this, const char *pszInputName, CEntityInstance *activator, CEntityInstance
  *caller, int value)` (approximate; exact activator/caller/value typing not fully recovered from the stripped
  decompile).
- **Return value**: forwarded from the internal dispatcher (not independently observed).
- **VTable**: none — concrete (non-virtual) forwarding wrapper; the real dispatch/handler-lookup logic lives in
  the internal callee it tail-calls into.

## Discovery Strategy

1. The prologue (`push rbp; mov rbp,rsp; push r14; mov r14,rdi; push r13; lea r13,[rbp+...]`) is distinctive
   enough to scan directly with `find_bytes` across the whole image and returns a single hit without needing a
   resolved anchor.
2. The 5-parameter shape and the `this+0x10` field read into a tail-call are a strong semantic fingerprint for a
   thin `CEntityInstance`-level forwarding wrapper, as opposed to the identity-level/script-level siblings with
   the same "AcceptInput" root name.
3. The high caller count (27 on this build) is consistent with a generic, widely-used I/O entry point invoked
   from many different entity classes' logic, further supporting the identification.

This is robust because the prologue byte pattern is unique in the whole 40MB image, and the forwarding shape
(read `this+0x10`, tail-call with the same arguments plus two trailing zero constants) cleanly distinguishes this
function from its three same-family siblings.

## Output YAML Format

The output YAML filename depends on the platform:
- `server.dll` -> `CEntityInstance_AcceptInput.windows.yaml`
- `libserver.so` -> `CEntityInstance_AcceptInput.linux.yaml`

Fields: `func_name`, `func_va`, `func_rva`, `func_size`, `func_sig`.

> Linux 14168 reference: func_sig = `55 48 89 E5 41 56 49 89 FE 41 55 48 8D 7D`, `func_va = 0x2105860`,
> `func_size = 0x68`.
