# Issue: historical C++ ABI validation needs a versioned CS2 SDK branch

## Summary

PR self-runner validation currently selects the accepted base snapshot version as
its validation `GAMEVER`. For PR #571, the release version is `14170`, but the
selected base snapshot is `14167`, so the workflow validates with:

```text
GAMEVER=14167
HEAD_CONFIG=configs/14167.yaml
HEAD_SNAPSHOT=gamesymbols/14167.yaml
```

The repository has one `hl2sdk_cs2` submodule revision, tracked on the current
`cs2_vibe` SDK line. It contains declarations for newer game builds. Its C++
headers cannot be compared against the `14167` binary ABI references. The
`Run C++ tests` step therefore fails even though the PR did not alter the SDK
submodule, C++ tests, or their analysis configuration.

The correct fix is to maintain a versioned SDK branch when a historical ABI
requires one. CI should temporarily detached-checkout `cs2-<GAMEVER>` only for
the C++ ABI layout test when that branch exists. If no branch exists, CI must
continue using the submodule revision pinned by the VibeSignatures commit.

## Failing Run

The failure first appeared after Python unit-test failures were repaired and
the C++ validation gate could run to completion:

<https://github.com/HLND2T/CS2_VibeSignatures/actions/runs/29499061700/job/87623077740>

All preceding validation stages passed:

- Formatting
- Python unit tests
- Binary analysis
- Candidate snapshot build and comparison
- Gamedata update

The failure is exclusively from `run_cpp_tests.py`.

## ABI Mismatches

### `IGameSystem_MSVC`

`gamesymbols/14167.yaml` expects a 64-entry vtable (`0x200`). The current SDK
header produces 65 entries (`0x208`).

The `14167` ABI requires `OnServerBeginAsyncPostTickWork` at index 41. Later
builds added an entry before it. The current SDK declaration has an additional
slot at index 41, placing `OnServerBeginAsyncPostTickWork` at index 42.

The later `14168` analysis explicitly documented this insertion in commit
`63f01913f51e205ff72401dcf1e39df70ea96e8b`:

```text
OnServerPreBeginAsyncPostTickWork was inserted at vtable index 41,
pushing OnServerBeginAsyncPostTickWork to index 42.
```

That declaration is correct for newer binaries but is not correct for `14167`.

Relevant files:

- `hl2sdk_cs2/game/shared/igamesystem.h`
- `configs/14167.yaml`
- `gamesymbols/14167.yaml`

### `IVEngineServer2_MSVC`

The `14167` reference contains `CEngineServer_LightStyle` at index 47. The
current `IVEngineServer2` declaration lacks that virtual method, so all
following slots are one position too early:

```text
YAML index 47: LightStyle
Header index 47: ClientPrintf
```

The result is 122 compiler entries (`0x3d0`) rather than the 123 entries
(`0x3d8`) required by the historical reference.

Relevant files:

- `hl2sdk_cs2/public/eiface.h`
- `configs/14167.yaml`
- `gamesymbols/14167.yaml`

### `CNetworkGameServerBase_MSVC`

The current `INetworkGameServer` base declaration includes
`BroadcastEntityVoice` before `CNetworkGameServerBase` begins. `14167` does
not have that base-class vtable entry. Consequently, the derived class's
`SetMaxClients` slot is 62 in the compiler output but 61 in the historical
reference, and all affected later offsets are shifted.

```text
YAML index 61: SetMaxClients
Header index 61: BroadcastEntityVoice
Header index 62: SetMaxClients
```

Relevant files:

- `hl2sdk_cs2/public/iserver.h`
- `configs/14167.yaml`
- `gamesymbols/14167.yaml`

## Why the Current SDK Cannot Be Labeled `14167`

`5f891c9026230cce0fc0a3fc4b5fef1c467a1385` (`Update INetworkGameServer
(#397)`) is a convenient historical starting point because it is an ancestor
of the current `cs2_vibe` SDK line. It must not be labeled or treated as the
`14167` ABI revision, however.

That commit still has all three incompatible declarations:

- The extra `IGameSystem` slot before `ServerBeginAsyncPostTickWork`.
- No `IVEngineServer2::LightStyle` slot at index 47.
- `INetworkGameServer::BroadcastEntityVoice`, which shifts the derived server
  vtable.

A `cs2-14167` branch must repair those declarations against the `14167` YAML
references before CI starts using it.

## Proposed Fix

### SDK Branch Policy

Create the following branch in `HLND2T/hl2sdk`:

```text
cs2-14167
```

Create it from `5f891c9026230cce0fc0a3fc4b5fef1c467a1385`, then repair the
declarations until they match `14167` references exactly. The branch is a
maintained compatibility line, not a new default SDK branch. `cs2_vibe`
remains the default/current CS2 SDK line.

The initial branch repair must:

1. Restore the `IGameSystem` 14167 vtable shape, with
   `OnServerBeginAsyncPostTickWork` at index 41 and no later insertion before
   it.
2. Add `IVEngineServer2::LightStyle` at index 47, with a declaration compatible
   with the 14167 binary interface.
3. Restore the 14167 `INetworkGameServer` base vtable shape so
   `CNetworkGameServerBase::SetMaxClients` remains at index 61. In particular,
   the newer `BroadcastEntityVoice` entry must not precede the derived class.
4. Run the complete VibeSignatures C++ ABI validation using `14167` binary
   references before merging any branch update.

The branch must be protected against force-push and deletion. It may advance
only through reviewed ABI repairs that pass the corresponding C++ layout gate.

No tag is required for this policy. The branch intentionally represents the
latest corrected declaration set for that historical game version. Each CI run
will log the resolved SDK commit SHA so the exact declaration version remains
auditable.

### Workflow Selection Rule

Both self-runner workflows must use the effective validation `GAMEVER`:

- `build-on-self-runner.yml`: the release build's `$env:GAMEVER`.
- `pr-self-runner.yml`: the selected validation `$env:GAMEVER`, which can be
  the base snapshot version rather than `$env:PR_GAMEVER`.

The SDK branch candidate is:

```text
cs2-<GAMEVER>
```

Examples:

```text
GAMEVER=14167  -> cs2-14167
GAMEVER=14170  -> cs2-14170
```

The selector must follow this algorithm:

1. Record the submodule's pinned `HEAD` commit after normal submodule
   initialization.
2. Query the fixed `HLND2T/hl2sdk` remote for `refs/heads/cs2-<GAMEVER>`.
3. If the branch is absent, retain the pinned submodule revision and log that
   no versioned SDK branch exists.
4. If the branch exists, fetch its exact remote commit and detached-checkout
   that commit in `hl2sdk_cs2`.
5. Log the selected branch, resolved commit SHA, and whether the pinned or
   versioned SDK revision was used.
6. Run C++ ABI tests using the selected headers.
7. Restore the original pinned submodule commit in an `if: always()` cleanup
   step so a reused Windows runner cannot retain the historical SDK checkout.

The selector must use a literal trusted SDK remote URL or verify that the
configured `origin` is `https://github.com/HLND2T/hl2sdk.git` before fetching.
It must not accept an SDK remote supplied by an untrusted pull-request change.

### Workflow Placement

The SDK checkout is required only for header-based C++ ABI validation. It is
not required by Python unit tests, binary analysis, candidate construction, or
gamedata generation.

Add the selection step immediately before the `run_cpp_tests.py` invocation:

- `.github/workflows/build-on-self-runner.yml`: after candidate gamedata
  validation and before its C++ test command.
- `.github/workflows/pr-self-runner.yml`: after candidate gamedata validation
  and before its `Run C++ tests` step.

This narrow scope avoids changing the headers seen by unrelated steps and
keeps all symbol-production inputs tied to the source commit's normal pinned
submodule revision.

## Reference PowerShell Flow

The production implementation can be inline in each workflow, but both copies
must preserve the same behavior:

```powershell
$sdkPath = Join-Path $env:WORKSPACE "hl2sdk_cs2"
$sdkRef = "cs2-$env:GAMEVER"
$pinnedSha = (git -C $sdkPath rev-parse HEAD).Trim()
$sdkRemote = "https://github.com/HLND2T/hl2sdk.git"

if ((git -C $sdkPath remote get-url origin).Trim() -ne $sdkRemote) {
  throw "Unexpected hl2sdk_cs2 origin remote."
}

$remoteBranch = git -C $sdkPath ls-remote --heads origin "refs/heads/$sdkRef"
if ($LASTEXITCODE -ne 0) { throw "Unable to query $sdkRef from hl2sdk." }

if ([string]::IsNullOrWhiteSpace($remoteBranch)) {
  "SDK_ABI_REF=pinned-submodule" | Out-File $env:GITHUB_ENV -Encoding utf8 -Append
  "SDK_ABI_SHA=$pinnedSha" | Out-File $env:GITHUB_ENV -Encoding utf8 -Append
  "SDK_ABI_SWITCHED=false" | Out-File $env:GITHUB_ENV -Encoding utf8 -Append
} else {
  git -C $sdkPath fetch origin "refs/heads/$sdkRef`:refs/remotes/origin/$sdkRef"
  if ($LASTEXITCODE -ne 0) { throw "Unable to fetch $sdkRef from hl2sdk." }
  git -C $sdkPath checkout --detach "refs/remotes/origin/$sdkRef"
  if ($LASTEXITCODE -ne 0) { throw "Unable to checkout $sdkRef." }
  $selectedSha = (git -C $sdkPath rev-parse HEAD).Trim()
  "SDK_ABI_REF=$sdkRef" | Out-File $env:GITHUB_ENV -Encoding utf8 -Append
  "SDK_ABI_SHA=$selectedSha" | Out-File $env:GITHUB_ENV -Encoding utf8 -Append
  "SDK_ABI_SWITCHED=true" | Out-File $env:GITHUB_ENV -Encoding utf8 -Append
}
```

The cleanup step should checkout `SDK_PINNED_SHA` only when
`SDK_ABI_SWITCHED=true`. The implementation must export `SDK_PINNED_SHA` before
the optional checkout and must not use an unqualified branch name for restore.

## Required Tests

Add workflow-source unit tests in:

- `tests/test_build_self_runner_workflow.py`
- `tests/test_pr_self_runner_workflow.py`

They should verify:

1. The SDK selector derives `cs2-$env:GAMEVER`, not a hard-coded version.
2. The PR workflow does not derive the SDK branch from `$env:PR_GAMEVER` after
   the validation version was selected.
3. The selector occurs after normal submodule initialization and before
   `run_cpp_tests.py`.
4. An absent remote branch leaves the pinned submodule revision in use.
5. A present remote branch is fetched and checked out detached.
6. The exact selected SDK SHA is written to the job log or summary.
7. The cleanup path restores the pinned SHA even when C++ tests fail.

The `cs2-14167` branch itself must pass:

```powershell
uv run run_cpp_tests.py `
  -gamever 14167 `
  -snapshot gamesymbols/14167.yaml `
  -configyaml configs/14167.yaml `
  -debug
```

## Acceptance Criteria

- `cs2_vibe` remains unchanged by the historical ABI repair.
- `cs2-14167` passes all configured C++ layout tests against the 14167 snapshot.
- PR validation with `GAMEVER=14167` chooses `cs2-14167` and passes the three
  currently failing ABI tests.
- A release or PR validation for a version without `cs2-<GAMEVER>` still uses
  the source commit's pinned SDK revision and retains current behavior.
- The SDK selection log identifies `GAMEVER`, selected ref, selected SHA, and
  pinned SHA.
- Reused Windows runners do not retain a historical SDK checkout after a job.
- The branch choice affects only C++ ABI validation, not binary analysis or
  generated candidate output.

## Non-Goals

- Do not move the `hl2sdk_cs2` gitlink in the VibeSignatures superproject for
  historical validation.
- Do not make `cs2-14167` the SDK default branch.
- Do not infer ABI compatibility from a commit date or use an arbitrary SDK
  ancestor as a version marker.
- Do not skip historical C++ ABI validation merely because a newer SDK header
  no longer matches it.
