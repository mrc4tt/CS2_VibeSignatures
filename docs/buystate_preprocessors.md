# BuyState preprocessors — implementation and verification status

Three callable preprocessors now use `preprocess_common_skill`:

| Script | Target kind | Implemented lookup |
|---|---|---|
| `find-BuyState_OnUpdate.py` | func | Prior function signature relocation |
| `find-BuyState_DoneBuying.py` | structmember | Prior member-access signature relocation |
| `find-BuyState_InitialDelay.py` | structmember | Prior member-access signature relocation |

These are real shared-engine entrypoints, but **signature reuse only**, not complete
independent discovery implementations. An absent or unsuccessful reusable locator
leaves the existing agent fallback in place. No current addresses, offsets or
signatures are hardcoded into the scripts. The caller supplies prior artifacts.

`configs/14178b.yaml` already registers all three exact filenames and correct
symbol categories. No configuration change is needed. The two member preprocessors
use their own prior signatures and have no established dependency on OnUpdate.
A future decompilation-based chain must verify that OnUpdate is the right source,
produce annotated references, then declare `expected_input` for both members.
Inventing that chain now would not supply the missing evidence.

The member fallback skills previously described virtual functions. They now agree
with the configured structmember schema. All three SKILL.md files remain available.
No conversion-complete statistics or tracked binary artifacts have been changed.

## What was tested

`uv run python -m unittest tests.test_buystate_preprocessors` tests both platform
arguments, typed shared-engine dispatch, failure propagation, isolated output paths,
config registration and retained skill schemas. The engine is mocked: this does
not verify any binary addresses or prove that signatures are unique.

## Remaining live verification

The current Codex tool list exposes no IDA MCP calls. The configured endpoint is
`http://127.0.0.1:13337/mcp`, but a local connection attempt was denied by the session
sandbox (`PermissionError: [Errno 1] Operation not permitted`). This does not establish
whether the server itself is running. The repository Python environment also has
no importable `idalib` module. Both game binaries and IDBs exist locally.

Required to finish independent finders and runtime verification:

1. Allow this working session to reach an IDA MCP endpoint and verify binary identity.
2. Verify BuyState_OnUpdate in each binary and establish a unique semantic locator.
3. Verify the exact flag accesses and distinguish them from other BuyState fields.
4. Capture real annotated references if using LLM_DECOMPILE; add dependencies then.
5. Rebuild all three in an isolated artifact root and pass runtime finalization.

A same-version source artifact is not automatically trustworthy: the local Linux
OnUpdate payload shares its address/signature with several unrelated named artifacts
seen during this investigation. Semantic identity must be checked before treating
it as a reference. Unique byte matching alone cannot resolve a mislabeled function.

Do not count a fallback-agent success as preprocessor success. Require the analyzer
log to show `Pre-processed: find-BuyState_... OK`, followed by successful finalization.
No commit or push was performed.
