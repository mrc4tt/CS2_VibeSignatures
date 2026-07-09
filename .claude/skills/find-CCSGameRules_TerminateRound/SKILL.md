---
name: find-CCSGameRules_TerminateRound
description: |
  Find and identify the CCSGameRules::TerminateRound function in the CS2 server binary using IDA Pro MCP.
  Use this skill when reverse engineering CS2 server.dll or libserver.so to locate the round-end-processing
  function by finding the code that references both the bare "TerminateRound" debug tag string and the
  "TerminateRound: unknown round end ID %i\n" warning-format string — both are referenced from the same function.
  Trigger: CCSGameRules_TerminateRound
disable-model-invocation: true
---

# Find CCSGameRules_TerminateRound

Locate `CCSGameRules::TerminateRound` in CS2 `server.dll` / `libserver.so` using IDA Pro MCP tools.

## Method

### 1. Find the TerminateRound Strings

```text
mcp__ida-pro-mcp__find_regex pattern="TerminateRound"
```

There are exactly two hits:
- A bare `"TerminateRound"` string (a debug/log tag, e.g. used in a `Msg`/`net_showmsg`-style trace of the
  function name).
- `"TerminateRound: unknown round end ID %i\n"` — a warning format string printed when an invalid round-end
  reason id is passed in.

### 2. Get the Referencing Function for Both Strings

```text
mcp__ida-pro-mcp__xrefs_to addr="<bare_TerminateRound_string_addr>"
mcp__ida-pro-mcp__xrefs_to addr="<unknown_round_end_ID_string_addr>"
```

Both strings are referenced from the exact same function — this agreement is the primary confirmation signal
(two independent strings converging on one function is very unlikely to be a coincidence).

> Linux 14168 reference: bare `"TerminateRound"` is at `0x8edd6c`, referenced from `0x138538b`;
> `"TerminateRound: unknown round end ID %i\n"` is at `0x989d78`, referenced from `0x1386f93`. Both xrefs land
> inside the same function starting at `0x1385380` (size `0x2063`).

### 3. Sanity-Check the Candidate

```text
mcp__ida-pro-mcp__decompile addr="0x1385380"
```

Confirm the decompilation is consistent with `TerminateRound(int iReason, float flDelay = ...)`: takes `this` +
an integer round-end-reason parameter (used in a large `switch`/if-chain that sets round-end state, awards money,
updates score, fires round-end events, etc.), plus additional float/optional parameters. The function is large
(hundreds of instructions) since it drives most of the end-of-round bookkeeping.

### 4. Generate Function Signature

**ALWAYS** Use SKILL `/generate-signature-for-function` with `addr=0x1385380` to generate a robust and unique
`func_sig`.

> Linux 14168 reference: generated signature is `55 48 89 E5 41 57 41 89 F7 41 56 48 8D 35` — already unique
> across the binary at this length (no wildcards needed in the head).

### 5. Write IDA Analysis Output as YAML

**ALWAYS** Use SKILL `/write-func-as-yaml` to write the analysis results.

Required parameters:
- `func_name`: `CCSGameRules_TerminateRound`
- `func_addr`: `0x1385380`
- `func_sig`: The validated signature from step 4

## Function Characteristics

- **Purpose**: Ends the current round for a given reason id (e.g. bomb defused, T/CT wiped, time expired),
  driving score updates, money awards, round-end event broadcast, and round-restart scheduling.
- **Binary**: `server.dll` / `libserver.so`
- **Parameters**: `(this, unsigned int reason, ...)` — additional trailing parameters (observed as `__int64`,
  `float`) control timing/延迟 of the subsequent round restart.
- **Return value**: not consumed by callers of interest (bookkeeping side-effects only).

## Discovery Strategy

1. `TerminateRound` has two distinct, independently-placed string literals in the binary: a bare debug tag and a
   full warning-format string for the invalid-reason-id error path.
2. Both strings are referenced from exactly one function each, and — critically — from the **same** function.
   This double-string agreement is a strong, code-shape-independent fingerprint that survives compiler
   refactoring/inlining changes far better than a fixed byte pattern alone would.
3. The candidate's parameter shape (integer round-end reason + optional delay) and its size (large, since it
   drives most round-end bookkeeping) are consistent with `TerminateRound`'s known role.

This is robust because two unrelated strings (a log tag and an error message) both trace back to the same
function, which is very unlikely to happen by chance for any other function in the binary.

## Output YAML Format

The output YAML filename depends on the platform:
- `server.dll` -> `CCSGameRules_TerminateRound.windows.yaml`
- `libserver.so` -> `CCSGameRules_TerminateRound.linux.yaml`

Fields: `func_name`, `func_va`, `func_rva`, `func_size`, `func_sig`.
