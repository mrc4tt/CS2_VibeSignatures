---
name: find-CBaseTrigger_StartTouch-AND-CBaseTrigger_EndTouch
description: |
  Find and identify the CBaseTrigger::StartTouch and CBaseTrigger::EndTouch overridden virtual functions in the
  CS2 server binary using IDA Pro MCP. Use this skill when reverse engineering server.dll or libserver.so to
  locate the trigger-volume touch-list add/remove handlers by RTTI-walking CBaseTrigger's and CBaseEntity's
  primary vtables and diffing them slot-by-slot to find CBaseTrigger's overrides, then identifying which two
  overridden slots implement "add pOther to the touching-entities list" (StartTouch) versus "remove pOther from
  the touching-entities list" (EndTouch).
  Trigger: CBaseTrigger_StartTouch, CBaseTrigger_EndTouch
disable-model-invocation: true
---

# Find CBaseTrigger_StartTouch and CBaseTrigger_EndTouch

Locate `CBaseTrigger::StartTouch` and `CBaseTrigger::EndTouch` in CS2 `server.dll` / `libserver.so` using IDA
Pro MCP tools.

**Note**: unlike most sibling skills, there is no known reference signature to validate against for these two
symbols — they are discovered fresh via vtable-diffing plus body-shape confirmation.

## Method

### 1. Resolve CBaseTrigger's and CBaseEntity's Primary VTables

**ALWAYS** Use SKILL `/get-vtable-address` with `class_name=CBaseTrigger` and again with `class_name=CBaseEntity`
(RTTI walk: typeinfo name string `"12CBaseTrigger"` / `"11CBaseEntity"` → typeinfo → primary vtable, the
candidate whose `offset_to_top` qword is `0` and whose first few slots point into executable memory).

> Linux 14168 reference: `CBaseTrigger` primary vtable `0x2396298`, `CBaseEntity` primary vtable `0x23cc9b8`.

### 2. Diff the Two VTables Slot-by-Slot

`CBaseTrigger` derives (indirectly) from `CBaseEntity`, so under the Itanium ABI every virtual function keeps
the **same slot index** across the inheritance chain. Read both vtables' function-pointer qwords at
`vt + 0x10 + n*8` for a generous slot range (e.g. `n` in `0..500`) and collect every `n` where the two addresses
differ — those are exactly the slots `CBaseTrigger` overrides.

```text
mcp__ida-pro-mcp__idalib py_eval code="<loop reading both vtables, diffing qwords>"
```

> Linux 14168 reference: differing slots in range 0..500 were `[125, 127, 147, 149, 150, 156, 194, 197, 198]`
> (9 overrides total — `CBaseTrigger` overrides `Spawn`/`Activate`/touch handlers/damage-related methods, etc.).

### 3. Identify StartTouch and EndTouch Among the Overridden Slots

Decompile every differing slot's `CBaseTrigger`-side function and look for the touch-list add/remove shape.
`CBaseTrigger` maintains an internal growable array of currently-touching entities (count field + pointer field,
a `CUtlVector`-shaped pair a fixed struct-offset apart, e.g. count at `this+2952`/`this+2960` in the 14168
build). The two candidates you want:

- **StartTouch**: searches the array for `pOther`'s handle; if absent, **appends** it (grows the array, bumps
  the count), and — only when the count transitions `0 → 1` — fires an additional "first toucher" callback
  (guarded by a `!= nullsub_*` check against a vtable slot, e.g. `OnStartTouchAll`). Also fires the trigger's
  `m_OnStartTouch`/output-system calls via `sub_2132220`-shaped helpers.
- **EndTouch**: searches the array for `pOther`'s handle; if found, **removes** it (shifts the tail down, shrinks
  the count), then fires the trigger's `m_OnEndTouch`/output-system calls the same way.

Both take `(CBaseTrigger *this, CBaseEntity *pOther)`. Reject any other overridden slot that doesn't touch this
array (e.g. slots that are trivial `return 0;`/`return 1;` stubs, or large functions unrelated to a touch list —
those are unrelated overrides like `ShouldCollide`/network-group helpers picked up by the same slot range scan).

**Cross-check** (do this — strong independent confirmation): decompile the **un-overridden** `CBaseEntity`-side
function at each of these two slots. Both should have the same generic shape — a short "forward the call to
some related singleton object at the *same* vtable slot" stub — which is the expected base-class placeholder
behavior for virtuals that `CBaseTrigger` (and other touch-list-owning classes) meaningfully override, while
`CBaseEntity` itself doesn't maintain a touch list.

> Linux 14168 reference: `CBaseTrigger` overrides slot **147** with `0xd54900` (StartTouch — appends to the
> touch array at `this+2952`/`this+2960`, fires `this+2168`/`this+2176`-guarded callbacks and
> `sub_2132220(this+2784/2760/2928, ...)` output calls) and slot **149** with a thin wrapper `0xd24190`
> (`if (a2) return sub_D23E70();`) that tail-calls `sub_D23E70` — which **removes** `pOther` from the same
> touch array and fires the paired `m_OnEndTouch`-style outputs at `this+2808/2928/2832` — i.e. EndTouch. Both
> un-overridden `CBaseEntity` slots (`0xd1dfa0` for 147, `0xd1e090` for 149) share the identical
> "forward to `sub_16B0920()`'s object at the same vtable offset" placeholder shape, confirming these two slots
> are the touch-list virtuals and that `CBaseTrigger` is the class that gives them real bodies.

### 4. Generate a Fresh Function Signature

Since there is no reference signature for either symbol, generate and simply record what's found:

**ALWAYS** Use SKILL `/generate-signature-for-function` with `addr=<CBaseTrigger_StartTouch_addr>`.

**ALWAYS** Use SKILL `/generate-signature-for-function` with `addr=<CBaseTrigger_EndTouch_addr>`.

> Linux 14168 reference sigs actually generated (no ground truth to compare against — reported as-is):
> - `CBaseTrigger_StartTouch` (`0xd54900`): `55 48 89 E5 41 56 41 55 49 89 F5 41 54 53 48 89 FB 48 83 EC ? 48 8B 07 FF 90 ? ? ? ? 84 C0`
> - `CBaseTrigger_EndTouch` (`0xd24190`): `48 85 F6 74 ? E9 ? ? ? ? 66 0F 1F 44 00 ? C3 CC CC CC CC CC CC CC CC CC CC CC CC CC CC CC 48 8B 07`
>   — note `EndTouch`'s real body is only 0x11 bytes (`test rsi,rsi; jz; jmp sub_D23E70`), so the signature
>   generator had to grow past the function's own `int3` padding into the *next* function's first bytes
>   (`48 8B 07`) to reach uniqueness; this is expected/benign for such a tiny thin-wrapper function and does not
>   indicate a bad signature, but it does mean the sig's tail is technically borrowed from the following symbol.

### 5. Write IDA Analysis Output as YAML

**ALWAYS** Use SKILL `/write-vfunc-as-yaml` twice, once for each symbol:

- `func_name`: `CBaseTrigger_StartTouch`, `func_addr`: `<StartTouch_addr>`, `func_sig`: from step 4,
  `vtable_name`: `CBaseTrigger`, `vfunc_offset`: `0x498` (`147*8`), `vfunc_index`: `147`.
- `func_name`: `CBaseTrigger_EndTouch`, `func_addr`: `<EndTouch_addr>`, `func_sig`: from step 4,
  `vtable_name`: `CBaseTrigger`, `vfunc_offset`: `0x4A8` (`149*8`), `vfunc_index`: `149`.

## Function Characteristics

- **Purpose**: `StartTouch`/`EndTouch` maintain `CBaseTrigger`'s per-instance list of entities currently
  overlapping the trigger volume, and fire the corresponding `m_OnStartTouch`/`m_OnEndTouch` (and
  `...All` variants on first/last toucher) I/O outputs.
- **Binary**: `server.dll` / `libserver.so`
- **Parameters**: `(CBaseTrigger *this, CBaseEntity *pOther)`
- **Return value**: `void`
- **VTable**: `CBaseTrigger`, slots 147 (`StartTouch`) and 149 (`EndTouch`) on the Linux 14168 reference build —
  these slot indices are inherited unchanged from `CBaseEntity::StartTouch`/`EndTouch` (Itanium ABI keeps virtual
  slot indices stable across the inheritance chain), so re-deriving them via `/get-vtable-index` against
  whichever build you're on is safer than hardcoding `147`/`149`.

## Discovery Strategy

1. RTTI-walk both `CBaseTrigger`'s and `CBaseEntity`'s primary vtables — no string/xref anchor is needed for
   either class since Itanium typeinfo name strings (`"12CBaseTrigger"`, `"11CBaseEntity"`) are always present
   even in a stripped binary.
2. Diff the two vtables slot-by-slot; every differing slot is a genuine `CBaseTrigger` override, independent of
   any single function's absolute address.
3. Among the overrides, identify the touch-list add/remove pair by body shape (grows vs. shrinks the same
   internal array, fires the paired Start/End output-event helpers) rather than by hardcoding a slot number —
   this survives the touch-list's own internal struct-offset layout changing across builds, as long as the
   *shape* of "search array, mutate count, conditionally fire paired outputs" stays recognizable.
4. Cross-checking against `CBaseEntity`'s own (un-overridden) placeholder bodies at the same two slots is a
   free, independent sanity check that costs nothing extra since both vtables were already resolved in step 1.

## Output YAML Format

The output YAML filenames depend on the platform:
- `server.dll` -> `CBaseTrigger_StartTouch.windows.yaml`, `CBaseTrigger_EndTouch.windows.yaml`
- `libserver.so` -> `CBaseTrigger_StartTouch.linux.yaml`, `CBaseTrigger_EndTouch.linux.yaml`

Fields (both files): `func_name`, `func_va`, `func_rva`, `func_size`, `func_sig`, `vtable_name`, `vfunc_offset`,
`vfunc_index`.
