---
name: find-LoggingSystem_LogDirect
description: |
  Find and identify the internal LoggingSystem_LogDirect worker function in CS2 tier0.dll / libtier0.so
  using IDA Pro MCP. Use this skill when reverse engineering CS2 tier0 to locate the single non-exported
  log worker that every exported LoggingSystem_LogDirect variadic wrapper forwards to (CleanerCS2 and
  similar console-filter plugins hook this worker). Resolved by intersecting the direct call targets of the
  exported LoggingSystem_LogDirect* wrappers: the dominant common callee is the worker. This anchor
  survives prologue churn between CS2 updates.
  Trigger: LoggingSystem_LogDirect, LogDirect
disable-model-invocation: true
---

# Find LoggingSystem_LogDirect (internal worker)

Locate the internal `LoggingSystem_LogDirect` worker in CS2 `tier0.dll` / `libtier0.so` using IDA Pro MCP
tools.

This is a **non-virtual, direct-call**, **non-exported** worker (no vtable entry — emit a byte sig, not an
offset). The exported `LoggingSystem_LogDirect*` symbols are thin variadic wrappers that all forward to
this one worker.

> **Do not** anchor the discovery recipe on the raw byte pattern below — bytes/wildcards shift release to
> release. Use it only to *locate/confirm* the function on the currently loaded binary, then generate a
> fresh signature at the end.

## Method

### 1. List the exported LoggingSystem_LogDirect wrappers

The wrappers are exported (present in the dynamic symbol table) and mangled
`_Z23LoggingSystem_LogDirect...`. There are several (≈8) — different arities / channel-id vs. severity
overloads.

```text
mcp__ida-pro-mcp__imports_query   name_contains="LoggingSystem_LogDirect"
# or, for exports specifically:
mcp__ida-pro-mcp__list_globals    name_contains="LoggingSystem_LogDirect"
```

If IDA lookup is unreliable on a stripped binary, read the ELF/PE export table directly (Linux):

```bash
nm -D libtier0.so | grep LoggingSystem_LogDirect
```

### 2. Collect each wrapper's direct call targets

Decompile or disassemble each wrapper and record every `call <target>` (direct calls only — ignore
`call [reg]` indirects).

```text
mcp__ida-pro-mcp__decompile   addr="<wrapper_va>"
```

### 3. Intersect — the dominant callee is the worker

Tally the call targets across all wrappers. The address that (nearly) every wrapper calls is the internal
`LoggingSystem_LogDirect` worker. It takes a channel/severity id in an integer argument and a message
pointer, and does the actual channel-enabled check + sink dispatch.

> Linux (repo libtier0.so) reference: worker at `0x212920` — dominant call target across the exported
> wrappers. Prologue on that build:
> `push rbp; mov eax,edx; mov r10,rdi; mov edi,esi; mov rbp,rsp; push r15; push r14`.

### 4. Generate function signature

**ALWAYS** Use SKILL `/generate-signature-for-function` with `addr=<worker_va>` to generate a robust and
unique `func_sig`. Mask 4-byte RIP-relative / rel32 displacements.

> Linux reference: `55 89 D0 49 89 FA 89 F7 48 89 E5 41 57 41` — unique across `.text` at this length
> (no wildcards needed on this build).

### 5. Write func YAML

**ALWAYS** Use SKILL `/write-func-as-yaml` to write the analysis results.

Required parameters:
- `func_name`: `LoggingSystem_LogDirect`
- `func_addr`: `<worker_va>`
- `func_sig`: The validated signature from step 4

## Function Characteristics

- **Purpose**: The single internal log worker behind every exported `LoggingSystem_LogDirect*` variadic
  wrapper — performs the channel-enabled check and dispatches the formatted message to the logging sinks.
- **Binary**: `tier0.dll` / `libtier0.so`.
- **Linkage**: non-virtual, direct-call, **not exported**.
- **Consumers**: console-output filter plugins (e.g. CleanerCS2) detour this worker to suppress/reroute
  server console spam.

## Discovery Strategy

1. Enumerate the exported `LoggingSystem_LogDirect*` wrappers (dynamic symbol table — survives stripping).
2. Intersect their direct `call` targets; the dominant shared callee is the worker.
3. This anchor is structural (the wrapper→worker fan-in), so it survives prologue churn even when a
   hardcoded byte sig breaks after a CS2 update.

## Output YAML Format

```yaml
func_name: LoggingSystem_LogDirect
func_va: '0x<va>'
func_rva: '0x<rva>'
func_size: '0x<size>'
func_sig: <space-separated byte pattern from step 4>
```
