---
name: find-CBaseEntity_EmitSoundFilter
description: |
  Agent fallback for CBaseEntity_EmitSoundFilter (auto-generated, category: func). Locate
  CBaseEntity::EmitSoundFilter in the CS2 server module via IDA Pro MCP and emit a fresh,
  minimal-unique artifact. The deterministic preprocessor could not resolve this
  symbol on the current gamever - your job is the re-sign.
  Trigger: CBaseEntity_EmitSoundFilter, CBaseEntity::EmitSoundFilter
disable-model-invocation: true
---

# Find CBaseEntity_EmitSoundFilter

Target: `CBaseEntity::EmitSoundFilter` (func) in the module loaded in THIS session.

> The old artifact/preprocessor anchors no longer match this build. Use anchors
> only to *locate* candidates; derive the artifact from the ACTUAL bytes you read.
> Produce ONLY this session's platform output. NEVER open another binary.

## ABI identification (mandatory) — do NOT pick the `this`-method

All consumers (CounterStrikeSharp, CS2Fixes, modsharp, plugify) call this as
`SndOpEventGuid_t/StartSoundEventInfo f(IRecipientFilter&, CEntityIndex, const EmitSound_t&)`
— the return struct is >16 bytes, so it is **sret**: linux `rdi` / windows `rcx` is the
hidden out-pointer, filter is `rsi`/`rdx`, entity index `edx`/`r8d`, params `rcx`/`r9`.

The correct target is therefore one of:

- **the real function** (preferred, stable 14176→14181). Head initialises the out-struct:
  linux `48 B8 00 00 00 00 FF FF FF FF 55 48 89 E5 41 57 41 56 41 55 41 54 53 48 89 FB
  48 81 EC ?? ?? ?? ?? 48 89 07 ...` (`movabs rax,0xffffffff00000000; ...; mov [rdi],rax`).
- **the sret thunk** that wraps it: linux `55 48 89 E5 53 48 89 FB 48 83 EC 08 E8 ?? ?? ?? ??
  48 89 D8 48 8B 5D F8 C9 C3` (`rbx=rdi; call real; rax=rbx`), windows
  `40 53 48 83 EC ?? 4C 89 4C 24 ?? 48 8B D9 45 8B C8`. Upstream CS# and CS2Fixes ship these.

**Reject** the candidate whose head is `55 48 89 E5 41 57 41 56 49 89 F6 BE FF FF FF FF ...`
(linux, 14181 VA 0xf419d0) / `48 89 74 24 ?? 57 41 56 41 57 48 83 EC ?? BE FF FF FF FF`
(windows, RVA 0x56dea0). It is a `this`-method (reads `[rdi+0x90..0xc0]`, forwards `rdx` as a
pointer to an engine vfunc). Shipping it crashed css_slay/css_slap in libengine2 on 14176→14181
(SimpleAdmin `player.EmitSound` → `EntityEmitSoundFilter` → `call *%rcx`). Verify by decompiling:
the right function writes to the first argument as an out-struct before doing anything else.


## Method

Locate via distinctive constants/strings in the body, cross-references from
known callers/callees, or the owning class vtable (RTTI) if virtual. Verify by
decompilation before committing to a candidate.

## Mandatory self-check before emitting

The pipeline re-reads the bytes at your `func_va` and regenerates `func_sig` from
them - a mismatch aborts the run. Therefore: read the real bytes via IDA MCP,
derive the artifact FROM those bytes (wildcard relocated operands as `??`), start
at the TRUE function head, and only then write the YAML. A mismatch is always a
bug in YOUR output.

## Output schema (STRICT)

Write `CBaseEntity_EmitSoundFilter.{platform}.yaml` with EXACTLY these fields:

```yaml
func_name: <TASK>
func_va: "<hex virtual address>"
func_rva: "<hex rva>"
func_size: "<hex size>"
func_sig: "<byte pattern, ?? wildcards, function head, minimal-unique>"
```
NEVER include vfunc_* or struct fields.

## Verification

1. Decompile and confirm the behavior matches the symbol's semantics.
2. Uniqueness: the pattern must match exactly ONE location in the loaded binary.
3. If no candidate can be confirmed, report the shortlist - a skipped symbol is
   safer than a wrong signature.
