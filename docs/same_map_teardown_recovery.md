# SameMapTeardown: interior address rejected during finalization

The reported `func_va=0x1808e32e0` is inside IDA's function at `0x1808e19c0`.
Runtime validation is correctly rejecting it. This does not prove that the owning
function is the desired target. Do not change the address mechanically or retain
an interior signature after selecting a different start address.

The finder skill now distinguishes internal locator matches from callable entries,
requires semantic confirmation of the owning function, and includes an executable
IDA guard that rejects interior addresses. Its YAML frontmatter indentation is
also corrected. Regression tests cover the exact reported addresses, metadata
recalculation and the unchanged strict runtime validator.

## Consumer caveat

The local bot-hider seed uses internal signatures with signed adjustments (-43 on
Windows, 22 on Linux). Its generator can replace a function signature while leaving
those adjustments intact. Therefore, a new function-head signature is not enough
to establish that the generated hook target is correct. Verify the consumer's
signature-plus-adjustment semantics before publishing gamedata. If this is an
internal hook site, a separate artifact/consumer contract is needed; it must not be
misrepresented as a function entry. This change does not modify those offsets or
claim the upstream hook target has been verified.

## Server retry

Wait for the current analysis to finish, or stop it cleanly before updating and
opening the same IDA database again. Pull the source correction and start a fresh
analysis process/session. An already running agent may retain earlier instructions.
Use a fresh output root so an invalid existing YAML is not skipped as completed:

```sh
teardown_output=$(mktemp -d /tmp/same-map-teardown.XXXXXX)
uv run ida_analyze_bin.py \
  -gamever 14178b \
  -modules server \
  -platform windows \
  -skill find-CCSGameRules_SameMapTeardown \
  -agent opencode \
  -oldgamever none \
  -artifactdir "$teardown_output"
```

Retain your normal model/environment settings. Output is under
`$teardown_output/14178b/server/`. Adopt it only after successful runtime
finalization and verification of target identity and downstream hook semantics.
Do not run this concurrently with the old process on the same binary/database.

The Windows artifact from the log is not available locally, and no live IDA
session was available for this repair. Actual addresses/signatures were not
regenerated. The 1200-second timeout is a separate event; its cause is not proven
by the provided log and timeout/retry behavior is unchanged.
