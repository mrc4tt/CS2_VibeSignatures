---
name: find-CEnvHudHint_API_ShowHudHint-binding
description: |
  Agent fallback for CEnvHudHint_API_ShowHudHint-binding (auto-generated, category: func). Locate
  CEnvHudHint_API::ShowHudHint in the CS2 server module via IDA Pro MCP and emit a fresh,
  minimal-unique artifact. The deterministic preprocessor could not resolve this
  symbol on the current gamever - your job is the re-sign.
  Trigger: CEnvHudHint_API_ShowHudHint-binding, CEnvHudHint_API::ShowHudHint
disable-model-invocation: true
---

# Find CEnvHudHint_API_ShowHudHint-binding

Target: `CEnvHudHint_API::ShowHudHint` (func) in the module loaded in THIS session.

> The old artifact/preprocessor anchors no longer match this build. Use anchors
> only to *locate* candidates; derive the artifact from the ACTUAL bytes you read.
> Produce ONLY this session's platform output. NEVER open another binary.

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

Write `CEnvHudHint_API_ShowHudHint.{platform}.yaml` with EXACTLY these fields:

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
