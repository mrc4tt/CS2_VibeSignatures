---
name: find-CCSPlayer_MovementServices_WalkMove
description: |
  Agent fallback for CCSPlayer_MovementServices_WalkMove (auto-generated, category: func). Locate
  CCSPlayer_MovementServices::WalkMove in the CS2 server module via IDA Pro MCP and emit a fresh,
  minimal-unique artifact. The deterministic preprocessor could not resolve this
  symbol on the current gamever - your job is the re-sign.
  Trigger: CCSPlayer_MovementServices_WalkMove, CCSPlayer_MovementServices::WalkMove
disable-model-invocation: true
---

# Find CCSPlayer_MovementServices_WalkMove

Target: `CCSPlayer_MovementServices::WalkMove` (func) in the module loaded in THIS session.

> The old artifact/preprocessor anchors no longer match this build. Use anchors
> only to *locate* candidates; derive the artifact from the ACTUAL bytes you read.
> Produce ONLY this session's platform output. NEVER open another binary.

## ABI identification (mandatory)

`CCSPlayer_MovementServices::WalkMove(CMoveData*)` is the ~4 KB SIMD body (14181: linux 0x15b69a0,
windows RVA 0xab4820), head linux `48 B8 ?? ?? ?? ?? ?? ?? ?? ?? 55 66 0F EF C0 48 89 E5 41 57 41 56`,
windows `48 8B C4 48 89 70 ?? 48 89 78 ?? 55 41 54 41 55 41 56 41 57`. swiftlys2, cs2kz and modsharp all
agree. **Reject** the small 3-argument helper that references "PlayerMove_PostMove" (14181 linux
0x15b61d0 / windows RVA 0xaa6cd0) - the old xref_strings anchor selected it. Note: the pipeline
previously shipped this body under FullWalkMove; FullWalkMove is the small `(CMoveData*, bool)`
function (14181 linux 0x15b7e30 / windows RVA 0xaa6ba0). `uv run abi_guard.py` enforces both.

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

Write `CCSPlayer_MovementServices_WalkMove.{platform}.yaml` with EXACTLY these fields:

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
