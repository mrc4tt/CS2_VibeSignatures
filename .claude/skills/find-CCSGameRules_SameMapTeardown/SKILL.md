---
name: find-CCSGameRules_SameMapTeardown
description: |
  Locate CCSGameRules::SameMapTeardown in CS2 server.dll / libserver.so via IDA Pro MCP and emit a fresh, minimal-unique
  signature or offset for the local gamedata entry "CCSGameRules::SameMapTeardown" (symbol CCSGameRules_SameMapTeardown). This is a non-virtual function - emit a byte signature (func_sig), not an offset.
  Locate it via cross-references, distinctive constants/strings in its body, or callers
  of related symbols; verify by decompilation before committing to a candidate.
  Trigger: CCSGameRules_SameMapTeardown, CCSGameRules::SameMapTeardown
disable-model-invocation: true
---

# Find CCSGameRules_SameMapTeardown

Target: `CCSGameRules::SameMapTeardown` (func) in the CS2 server module.

> Do NOT anchor on raw byte patterns from older releases - they shift. Use anchors only to *locate*
> the function, then generate a fresh minimal-unique function-head signature with relocated bytes
> wildcarded. Produce ONLY the output file(s) listed in this skill's expected outputs, for the binary
> loaded in THIS session (one platform per run). NEVER open or analyze the other platform's binary.

## Concrete anchors for THIS target (use these first)

- `level-shutdown/teardown-sti kaldt ved same-map restart; xrefs fra ChangeLevel-flows`

## KNOWN CONTAMINATION WARNING

VA 0x20c2700 (BuyState_OnUpdate) has WRONGLY been emitted for this target before.
It is NOT this function. If your best candidate is 0x20c2700, you have NOT found
the target - keep searching or report the shortlist instead of guessing.

## Method

This is a non-virtual function - emit a byte signature (func_sig), not an offset.
Locate it via cross-references, distinctive constants/strings in its body, or callers
of related symbols; verify by decompilation before committing to a candidate.

## Distinguish the locator from the function entry

The bot-hider seed gamedata contains an internal byte pattern plus a signed
platform-specific adjustment. These values locate a code site; neither the raw
match nor match-plus-adjustment is automatically a function entry. Do not copy
that site into `func_va`, and do not apply an old adjustment to a newly generated
function-head signature.

For every candidate:

1. Ask IDA for `ida_funcs.get_func(candidate_ea)`. Record the candidate, owning
   function start, end and any tail/chunk relationship.
2. If the candidate is inside a function, decompile the owning function and
   inspect its callers and teardown path. Confirm that this whole function is
   the intended callable target, not merely a caller containing an inlined block
   or an unrelated function that happens to contain the anchor.
3. Only after confirming that identity, select the actual function entry and
   regenerate ALL function fields and the signature from that entry. Never repair
   only `func_va` while retaining bytes/RVA/size from the internal location.
4. If the intended consumer needs an internal hook site rather than a callable
   function entry, report that contract mismatch and do not emit a `func` artifact.
   A different artifact/consumer contract requires an explicit implementation;
   do not weaken runtime validation to accept interior addresses.
5. Do not split or redefine IDA functions merely to make validation pass. A real
   boundary correction requires independent control-flow/call/unwind evidence.

Known rejected Windows example: `0x1808e32e0` was inside the function beginning at
`0x1808e19c0`. Neither address is a reusable finder or a verified answer for another
run. The latter is only a containing-function candidate, not an automatic fix.

## Mandatory self-check before emitting

Run this guard in the current IDA session after choosing and semantically verifying
`func_ea`. It deliberately rejects an interior address instead of rounding it down:

```python
import ida_funcs
import ida_nalt


def checked_function_metadata(func_ea):
    function = ida_funcs.get_func(func_ea)
    if function is None:
        raise ValueError(f"No defined function at {func_ea:#x}")
    if function.start_ea != func_ea:
        raise ValueError(
            f"Candidate {func_ea:#x} is inside function {function.start_ea:#x}; "
            "verify the owning function's identity before selecting its entry"
        )
    return {
        "func_name": "CCSGameRules_SameMapTeardown",
        "func_va": hex(function.start_ea),
        "func_rva": hex(function.start_ea - ida_nalt.get_imagebase()),
        "func_size": hex(function.size()),
    }
```

Read actual bytes at the checked `func_va`, then generate a fresh minimal unique
`func_sig` starting at exactly that address. Verify both its bytes and its unique
match address, not just its match count. Add it to the checked metadata and replace
the complete expected YAML payload under the caller's artifact directory. Run the
boundary guard again immediately before writing. A failed guard means no output.

The pipeline independently checks the entry and regenerates the signature; retain
those checks. If a retry sees an existing invalid YAML, treat it as failed output,
not completed work. Do not assume a file left by a timed-out attempt is valid.

## Output schema (STRICT)

Write the YAML file `<symbol>.{platform}.yaml` with EXACTLY these fields:
```yaml
func_name: <SYMBOL_NAME>
func_va: "<hex virtual address>"
func_rva: "<hex rva>"
func_size: "<hex size>"
func_sig: "<byte pattern, ?? wildcards, function head, minimal-unique>"
```
NEVER include vfunc_index, vfunc_offset, vfunc_sig or vtable_name.

## Verification

1. Decompile the candidate and confirm the behavior matches the purpose above (not a caller or callee).
2. Confirm uniqueness: the generated pattern must match exactly one location in the loaded binary.
3. If a candidate cannot be confirmed, report the shortlist instead of guessing - a skipped symbol is
   safer than a wrong signature.
