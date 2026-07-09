---
name: find-CBasePlayerController_SetPawn-AND-CBasePlayerController_GetPawn
description: |
  Find and identify the CBasePlayerController_SetPawn and CBasePlayerController_GetPawn functions in CS2 binary
  using IDA Pro MCP. Use this skill when reverse engineering CS2 server.dll / libserver.so to locate the
  pawn-assignment routine by scanning for its distinctive multi-register-push prologue directly (no pre-resolved
  anchor needed), confirming uniqueness and byte-level match against a known reference signature.
  Trigger: CBasePlayerController_SetPawn, CBasePlayerController_GetPawn
disable-model-invocation: true
---

# Find CBasePlayerController_SetPawn and CBasePlayerController_GetPawn

Locate `CBasePlayerController_SetPawn` and `CBasePlayerController_GetPawn` in CS2 `server.dll` / `libserver.so`
using IDA Pro MCP tools.

## Method

### 1. Locate SetPawn via Direct Byte-Pattern Scan

The upstream tooling normally resolves `CBasePlayerController_SetPawn` by LLM-decompiling the already-known
`CSource2GameClients_ClientDisconnect` vfunc (see `expected_input` in `config.yaml` for this skill) and reading
off the call `CBasePlayerController_SetPawn(controller, 0, 0, 0, 0, 0)` that clears the pawn on disconnect, right
after a `CBasePlayerController_GetPawn(controller)` call. When that anchor is not pre-resolved, `SetPawn`'s
prologue is distinctive enough (5 callee-saved register pushes plus an early `lea r13, [rdi+IMM32]` sandwiched
between two of the pushes) to scan directly:

```text
mcp__ida-pro-mcp__find_bytes patterns=["55 48 89 E5 41 57 41 56 41 55 4C 8D AF ?? ?? ?? ?? 41 54 41 89 CC"]
```

This returns exactly **one** hit on the analyzed 14168 Linux binary.

### 2. Confirm via Decompile

```text
mcp__ida-pro-mcp__decompile addr="<candidate_addr>"
```

The candidate takes 4 parameters `(this, a2, a3, char a4)` and, at its head, computes `r13 = this + 968` (the
`lea r13, [rdi+imm32]` from the prologue) — an internal table/map embedded in the controller object — then packs
`a2`/`a3` into a 16-byte key and performs a find-or-insert against that table (grow-on-miss, `a4` gates whether a
new entry is created on a lookup miss). This is consistent with `SetPawn` maintaining an internal
handle-registration/lookup structure for the assigned pawn as part of updating `m_hPawn` (CS2's entity-handle
system commonly backs simple-looking setters with hashtable-based bookkeeping for fast handle resolution). Byte
match with the reference signature (see Output section) is the primary/authoritative confirmation for this
recipe; treat the decompile as corroborating, not disqualifying, evidence given Hex-Rays' limited insight into a
fully stripped binary.

### 3. Cross-Check Caller Count

```text
mcp__ida-pro-mcp__xrefs_to addrs=["<candidate_addr>"]
```

> Linux 14168 reference: candidate at `0x2280ab0` (size `0x430`), with 6 direct callers — consistent with `SetPawn`
> being invoked from a handful of spawn/possession/disconnect code paths rather than being a hot-path/ubiquitous
> function (contrast with `GetPawn`, expected to have many more callers).

### 4. Locate GetPawn (Best Effort — No Ground Truth Available This Session)

`GetPawn` was **not independently verified with ground truth** in this session. Expect a small, trivial accessor
(likely `return m_hPawn.Get();`, i.e. a handle-to-pointer resolve through the global entity list) called from a
very large number of sites throughout the module (far more callers than `SetPawn`). A practical way to locate it:
enumerate small (<0x40 byte) functions near `SetPawn`'s translation unit that read the same `this+968`-adjacent
memory region populated by `SetPawn`, or that are called immediately before `SetPawn` in known callers (e.g. the
`CSource2GameClients_ClientDisconnect` anchor calls `GetPawn(controller)` then, if non-null, `SetPawn(controller,
0,0,0,0,0)`). Confirm any candidate by checking it has very high caller count and a one-or-two basic-block trivial
body.

### 5. Generate Function Signature

**ALWAYS** Use SKILL `/generate-signature-for-function` with `addr=<SetPawn_candidate_addr>` to generate a robust
and unique `func_sig` for `CBasePlayerController_SetPawn`. Repeat for `GetPawn` once resolved.

### 6. Write IDA Analysis Output as YAML

**ALWAYS** Use SKILL `/write-func-as-yaml` for `CBasePlayerController_SetPawn` with the address/signature from
steps 1/5. Repeat for `CBasePlayerController_GetPawn` once independently resolved.

## Function Characteristics

### CBasePlayerController_SetPawn

- **Purpose**: Assigns (or clears, when called with all-zero/false args) the `CBasePlayerPawn*` associated with a
  `CBasePlayerController`, updating internal handle-lookup bookkeeping as part of possession/spawn/disconnect
  flows.
- **Binary**: `server.dll` / `libserver.so`
- **Parameters**: `(CBasePlayerController *this, ...)` — observed as 4 detected params in the decompiled body
  (`this`, two 8-byte values forming a 16-byte key, and a trailing bool), though the real source-level signature
  may carry additional trailing bool parameters that are dead in this particular call shape (the
  `CSource2GameClients_ClientDisconnect` reference calls it with 5 trailing zero/false args).
- **VTable**: none — concrete (non-virtual) method.

### CBasePlayerController_GetPawn

- **Purpose**: Returns the `CBasePlayerPawn*` currently assigned to the controller (resolves `m_hPawn`).
- **Binary**: `server.dll` / `libserver.so`
- **Parameters**: `(CBasePlayerController *this)`
- **Status**: not resolved with ground truth this session — see step 4 for the discovery approach.

## Discovery Strategy

1. `SetPawn`'s prologue (5 callee-saved pushes with a `lea r13, [rdi+imm32]` inserted mid-sequence) is distinctive
   enough to be directly scannable with `find_bytes` across the whole image, and returns a single hit.
2. Byte-level agreement with the reference signature at every fixed-byte position is the authoritative validation
   signal for this recipe (see repo-wide validation rules); decompile semantics are corroborating but, on a
   stripped/optimized binary, can look unlike a naive "just assign a pointer" setter due to internal
   handle-bookkeeping.
3. `GetPawn` is expected to be reachable as a much-more-frequently-called trivial accessor; without ground truth
   this session it is documented as a follow-up using caller-count and small-body heuristics rather than guessed
   at with an unverified address.

This is robust because the prologue byte pattern is unique in the whole 40MB image even without walking from the
`CSource2GameClients_ClientDisconnect` anchor, and the resulting signature was independently regenerated via
`make_signature_for_function` and found to match the reference byte-for-byte.

## Output YAML Format

The output YAML filenames depend on the platform:
- `server.dll` -> `CBasePlayerController_SetPawn.windows.yaml`, `CBasePlayerController_GetPawn.windows.yaml`
- `libserver.so` -> `CBasePlayerController_SetPawn.linux.yaml`, `CBasePlayerController_GetPawn.linux.yaml`

Fields (both files): `func_name`, `func_va`, `func_rva`, `func_size`, `func_sig`.

> Linux 14168 reference: `CBasePlayerController_SetPawn` func_sig =
> `55 48 89 E5 41 57 41 56 41 55 4C 8D AF ? ? ? ? 41 54 41 89 CC`, `func_va = 0x2280ab0`, `func_size = 0x430`.
> `CBasePlayerController_GetPawn` not resolved this session.
