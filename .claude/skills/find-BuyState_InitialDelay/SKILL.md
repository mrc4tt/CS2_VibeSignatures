---
name: find-BuyState_InitialDelay
description: |
  Locate BuyState::m_isInitialDelay, exposed as BuyState::InitialDelay, in the loaded CS2
  server binary. Emit a structmember offset, never a function or vtable slot.
  Trigger: BuyState_InitialDelay, BuyState::InitialDelay
disable-model-invocation: true
---

# Find BuyState_InitialDelay

Target: the one-byte BuyState member `m_isInitialDelay`. The configured category is
`structmember`. Keep this skill as fallback until the preprocessor is verified
in the actual Windows/Linux binaries.

Inspect verified BuyState behavior code and trace the relevant member accesses
back to the BuyState object. `BuyState_OnUpdate` is a candidate inspection point,
not a proven dependency: verify its identity and the member's behavioral role
before using it. Do not assume an old offset or infer identity from a byte-sized
comparison alone. Distinguish this flag from the other BuyState flags and timers.

Read the actual displacement and verify its base object, access size and control
flow. Generate a unique instruction signature for this access; for an anchor
before the access include `offset_sig_disp`. Check the match in the loaded binary.
Only analyze and write the requested platform. If identity or uniqueness cannot
be established, report failure without guessed output.

Replace the complete expected `BuyState_InitialDelay.{platform}.yaml` under the
caller-provided artifact directory with:

```yaml
struct_name: BuyState
member_name: m_isInitialDelay
offset: '<verified byte offset in hex>'
size: 1
offset_sig: '<unique signature of the verified member access>'
```

Optional: `offset_sig_disp` for a backward-expanded anchor. Never emit `func_*`,
`vfunc_*` or `vtable_*`. Central runtime validation/canonicalization is mandatory.
