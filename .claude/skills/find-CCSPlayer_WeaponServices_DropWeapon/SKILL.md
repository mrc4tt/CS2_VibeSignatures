---
name: find-CCSPlayer_WeaponServices_DropWeapon
description: |
  Locate CCSPlayer_WeaponServices::DropWeapon in CS2 server.dll / libserver.so via IDA Pro MCP and emit a fresh, minimal-unique
  signature or offset for the WeaponPaints gamedata entry "CCSPlayer_WeaponServices::DropWeapon" (symbol CCSPlayer_WeaponServices_DropWeapon). This is a VIRTUAL function — emit the vtable slot, NOT a byte signature. Resolve the CCSPlayer_WeaponServices vtable via RTTI and identify the DropWeapon slot: the body takes a CBasePlayerWeapon handle/pointer, detaches it from the player, spawns the dropped weapon entity and transfers ownership. Verify by xrefs from weapon-drop commands (!!drop) and pickup logic. vtable slots commonly differ between platforms — never assume identical indices.
  Trigger: CCSPlayer_WeaponServices_DropWeapon, CCSPlayer_WeaponServices::DropWeapon
disable-model-invocation: true
---

# Find CCSPlayer_WeaponServices_DropWeapon

Target: `CCSPlayer_WeaponServices::DropWeapon` (vfunc) in the CS2 server module, both `server.dll` (windows) and `libserver.so` (linux).

> Do NOT anchor on raw byte patterns from older releases — they shift. Use anchors only to *locate* the
> function, then generate a fresh minimal-unique function-head signature with relocated bytes wildcarded.

## Method

This is a VIRTUAL function — emit the vtable slot, NOT a byte signature. Resolve the CCSPlayer_WeaponServices vtable via RTTI and identify the DropWeapon slot: the body takes a CBasePlayerWeapon handle/pointer, detaches it from the player, spawns the dropped weapon entity and transfers ownership. Verify by xrefs from weapon-drop commands (!!drop) and pickup logic. vtable slots commonly differ between platforms — never assume identical indices.

## Mandatory self-check before emitting (func artifacts)

The pipeline re-reads the bytes at your \`func_va\` and deterministically regenerates \`func_sig\` from
them — if your \`func_sig\` does not match those bytes EXACTLY (with \`??\` matching anything), the run
aborts. Therefore:

1. After picking the function, read the actual bytes at \`func_va\` via the IDA MCP (get-bytes/disasm).
2. Derive \`func_sig\` FROM those bytes: keep stable opcode bytes literally, wildcard relocated/
   variable operands (displacements, immediates, stack sizes) as \`??\`.
3. \`func_sig\` MUST start at \`func_va\` (the true function head — verify with IDA's function start).
4. Only then write the YAML. A mismatch is always a bug in YOUR output, never in the pipeline.

## Output schema (STRICT)

Write the YAML file `CCSPlayer_WeaponServices_DropWeapon.{platform}.yaml` with EXACTLY these fields — no more, no fewer.
Unknown extra fields make the output invalid and abort the run.

```yaml
func_name: <SYMBOL_NAME>
func_va: "<hex virtual address>"
func_rva: "<hex rva>"
func_size: "<hex size>"
vtable_name: <owning class RTTI name>
vfunc_offset: "<hex vtable byte offset, e.g. 0x7f0>"
vfunc_index: <decimal slot index>
```
NEVER include func_sig — this is a vtable-slot (vfunc) artifact.

## Verification

1. Decompile the candidate and confirm the behavior matches the purpose above (not a caller or callee).
2. Confirm uniqueness: the generated pattern must match exactly one location in the loaded binary.
3. Produce ONLY the output file(s) listed in this skill's expected outputs, for the binary
   loaded in THIS session (one platform per run). NEVER open or analyze the other platform's
   binary — each platform is produced in its own dedicated run.

Prefer deterministic anchors first (RTTI / vtable / schema-network offsets); fall back to string anchors,
then caller/callee cross-checks. If a candidate cannot be confirmed, report the shortlist instead of
guessing — a skipped symbol is safer than a wrong signature.
