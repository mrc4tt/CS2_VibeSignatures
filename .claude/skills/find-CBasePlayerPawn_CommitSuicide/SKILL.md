---
name: find-CBasePlayerPawn_CommitSuicide
description: |
  Find and identify the CBasePlayerPawn::CommitSuicide virtual function's vtable slot in the CS2 server binary
  using IDA Pro MCP. Use this skill when reverse engineering server.dll or libserver.so to locate the
  self-inflicted-death handler (used by the "kill"/bot_kill console commands and related gameplay code) by
  RTTI-walking CBasePlayerPawn's primary vtable and reading its known slot index directly, then confirming the
  body matches CommitSuicide(bool bExplode, bool bForce) semantics.
  Trigger: CBasePlayerPawn_CommitSuicide
disable-model-invocation: true
---

# Find CBasePlayerPawn_CommitSuicide

Locate `CBasePlayerPawn::CommitSuicide` in CS2 `server.dll` / `libserver.so` using IDA Pro MCP tools.

## Method

### 1. Resolve CBasePlayerPawn's Primary VTable

**ALWAYS** Use SKILL `/get-vtable-address` with `class_name=CBasePlayerPawn` (RTTI walk via the Itanium typeinfo
name string `"15CBasePlayerPawn"`; primary vtable = the candidate whose `offset_to_top` qword is `0` and whose
first few slots point into executable memory).

> Linux 14168 reference: `CBasePlayerPawn` primary vtable `0x23d01c8`. Note this class's typeinfo string has an
> unusually large number (21 on the 14168 build) of raw data xrefs to its typeinfo struct compared to most other
> classes — most of those hits are **not** real vtable pointers (they land on non-8-byte-aligned addresses inside
> `.text`, which are false positives from IDA's own operand/immediate analysis on this stripped binary). Always
> filter candidates down to the one whose `offset_to_top` qword is exactly `0` **and** whose first 2-3 slots
> disassemble as executable code before trusting it as the primary vtable — don't just take the first or only
> "clean-looking" hit.

### 2. Read Slot 384 Directly

`FUNC_VTABLE_RELATIONS = [("CBasePlayerPawn_CommitSuicide", "CBasePlayerPawn")]` and the slot index (384) is
already known ground truth, so no additional discovery/anchor search is needed for the index itself:

```text
mcp__ida-pro-mcp__idalib get_int queries=[{"addr":"<vtable_va + 0x10 + 384*8>","ty":"u64"}]
```

> Linux 14168 reference: slot 384 resolves to `0x17d99a0` (size `0x108`).

### 3. Confirm the Body Matches CommitSuicide Semantics

Decompile the resolved address and confirm the shape: `(CBasePlayerPawn *this, bool bExplode, bool bForce)` —
i.e. 3 total parameters including `this`. Expected body:

1. A "god mode"/"buddha mode" bypass check near the top: reads a vtable slot (e.g. offset `0x538`/index 167 on
   the 14168 build) that's compared against a known "default/no override" stub function; if it *is* the default
   stub, fall back to checking a plain boolean field on `this` instead, otherwise call the (overridden) vtable
   slot directly. If this check indicates the bypass is active, return early without killing the pawn.
2. A rate-limit/cooldown check: compares the current game time against a stored "next allowed suicide time"
   field on `this`; skips the cooldown check entirely if `bForce` is set.
3. On passing both checks: updates the cooldown field to `now + 5.0`, constructs a damage-info object (via a
   helper resembling `CTakeDamageInfo`'s constructor) with a damage-type bit derived from `bExplode` (selects
   between two different damage-type flag values depending on whether the death should look like an explosion),
   applies it to `this` via a `TakeDamage`-shaped call, then destroys the temporary damage-info object.

> Linux 14168 reference: `sub_17D99A0`'s body matches this exactly — the god-mode check reads `*this`'s vtable
> at offset `1336` (`0x538`, slot 167) and compares it against `sub_A28320`; the cooldown field lives at
> `this+3712`, set to `now + 5.0` on a successful call; the damage-type selector is `(bExplode ? 64 : 32) | 0x116`
> feeding into `sub_1AA3160` (damage-info constructor) followed by `sub_D4CFA0` (apply-damage) and
> `sub_1A848C0` (damage-info destructor).

**Cross-check** (optional but recommended — do this if you have time budget): find the `bot_kill`/`kill` console
command handler via `find_regex` for the literal command-name string, trace its call graph, and confirm it
ultimately calls the same address through the pawn's `CommitSuicide` vtable slot (devirtualized or indirect —
either is fine as corroboration).

### 4. Generate Function Signature

**ALWAYS** Use SKILL `/generate-signature-for-function` with `addr=<CommitSuicide_addr>` to generate a robust and
unique `func_sig`.

### 5. Write IDA Analysis Output as YAML

**ALWAYS** Use SKILL `/write-vfunc-as-yaml`.

Required parameters:
- `func_name`: `CBasePlayerPawn_CommitSuicide`
- `func_addr`: `<CommitSuicide_addr>`
- `func_sig`: The validated signature from step 4

VTable parameters:
- `vtable_name`: `CBasePlayerPawn`
- `vfunc_offset`: `0xC00` (`384*8`)
- `vfunc_index`: `384`

## Function Characteristics

- **Purpose**: Kills the player pawn via self-inflicted damage (used by the `kill`/`bot_kill`-family console
  commands and any gameplay code that needs to force a player's death). Respects a god-mode/buddha-mode bypass
  and a short cooldown between successive calls, unless force-overridden.
- **Binary**: `server.dll` / `libserver.so`
- **Parameters**: `(CBasePlayerPawn *this, bool bExplode, bool bForce)`
- **Return value**: `void`
- **VTable**: `CBasePlayerPawn`, slot **384** (`vfunc_offset = 0xC00`) — matches ground truth.

## Discovery Strategy

1. The slot index (384) is already known ground truth from `FUNC_VTABLE_RELATIONS`, so the only real discovery
   work is resolving `CBasePlayerPawn`'s primary vtable correctly — which, on this binary, required filtering out
   a substantial amount of false-positive xref noise to the class's typeinfo struct (see the callout in step 1).
   The `offset_to_top == 0` + "first slots are executable code" filter is what makes this reliable rather than
   accidentally picking a garbage candidate.
2. Body-shape confirmation (god-mode bypass, cooldown timer, explode-vs-normal damage-type selection, then a
   construct/apply/destroy damage-info sequence) is a strong independent signal that doesn't depend on the
   function's address, so it survives the function moving around between builds — only the *slot index* needs to
   stay stable, which the Itanium ABI guarantees for as long as `CommitSuicide`'s position in the class's
   declared-virtuals list doesn't change.

## Output YAML Format

The output YAML filename depends on the platform:
- `server.dll` -> `CBasePlayerPawn_CommitSuicide.windows.yaml`
- `libserver.so` -> `CBasePlayerPawn_CommitSuicide.linux.yaml`

Fields: `func_name`, `func_va`, `func_rva`, `func_size`, `func_sig`, `vtable_name`, `vfunc_offset`, `vfunc_index`.
