[Back to README](../../README.md) | [中文](../zh-CN/analysis.md)

# Binary acquisition and symbol analysis

## Download the CS2 depot

Download the configured depot version, then copy the target binaries into the workspace:

```bash
uv run download_depot.py -tag 14156

uv run copy_depot_bin.py -gamever 14156 -platform all-platform
uv run copy_depot_bin.py -gamever 14156 -platform all-platform -checkonly
```

Use `-checkonly` in CI or preflight scripts when you only need to know whether all expected target binaries already exist under `bin/<gamever>/...`. This mode only checks target paths, does not require a populated `cs2_depot`, returns `0` when all expected binaries are ready, `1` when any target is missing, and `2` for configuration or argument errors.

The scheduled `Bump Download` GitHub Actions workflow keeps `download.yaml` current. It runs `bump_download.py` against the CS2 default branch, appends an entry only when the discovered `PatchVersion` and depot manifests require it, creates the matching local commit and tag, and pushes them from the workflow.

Preview a bump locally without writing Git state:

```bash
uv run bump_download.py -config download.yaml -depotdir cs2_depot -dry-run
```

If DepotDownloader needs authentication, add the same `-username`, `-password`, and `-remember-password` flags used by the workflow.

## Analyze configured symbols

The Analyzer finds and generates signatures for symbols declared in `configs/<GAMEVER>.yaml`.

Command synopsis:

```bash
uv run ida_analyze_bin.py -gamever 14156 [-oldgamever=14155] [-configyaml=path/to/custom.yaml] [-modules=server] [-skill=find-CBaseEntity_vtable] [-platform=windows] [-agent=claude/codex/opencode/"claude.cmd"/"codex.cmd"/"opencode.cmd"] [-maxretry=3] [-vcall_finder=g_pNetworkMessages] [-llm_model=gpt-4o] [-llm_apikey=your-key] [-llm_baseurl=https://api.example.com/v1] [-llm_temperature=0.2] [-llm_effort=medium] [-llm_fake_as=codex] [-rename] [-debug]
```

Shared LLM parameters:

- `-llm_apikey`: required when an LLM-backed workflow is enabled, including `vcall_finder` aggregation and `LLM_DECOMPILE`.
- `-llm_baseurl`: optional custom compatible base URL; required with `-llm_fake_as=codex`.
- `-llm_model`: optional; defaults to `gpt-4o`.
- `-llm_temperature`: optional; sent only when explicitly set.
- `-llm_effort`: optional; defaults to `medium`; supports `none|minimal|low|medium|high|xhigh`.
- `-llm_fake_as`: optional; `codex` switches to direct `/v1/responses` SSE transport.
- Environment fallbacks: `CS2VIBE_LLM_APIKEY`, `CS2VIBE_LLM_BASEURL`, `CS2VIBE_LLM_MODEL`, `CS2VIBE_LLM_TEMPERATURE`, `CS2VIBE_LLM_EFFORT`, and `CS2VIBE_LLM_FAKE_AS`.
- LLM workflows do not read `OPENAI_API_KEY`, `OPENAI_API_BASE`, or `OPENAI_API_MODEL`.

Analyzer behavior:

- Old signatures from `bin/{previous_gamever}/{module}/{symbol}.{platform}.yaml` are tried through MCP before Agent skills run. Successful reuse does not consume Agent tokens.
- `-agent="claude.cmd"` selects the Claude CLI installed through npm on Windows.
- `-agent="opencode.cmd"` selects the npm-installed OpenCode CLI on Windows. OpenCode loads `.opencode/agents/sig-finder.md` and runs skills non-interactively.
- Prefer programmatic preprocessors, then `LLM_DECOMPILE` preprocessors, then Agent skills.
- `-skill=<exact-name>` only runs an exact skill name within the active `-modules` filter. It does not run prerequisites automatically; required `expected_input` artifacts must already exist.
- `-rename` runs rename/comment post-processing over existing expected-output YAML files.

Process reporting, the Redis-backed Scheduler, and the progress dashboard are documented in [Process reporting, scheduling, and dashboard](process-monitoring.md).

## `vcall_finder`

- `-vcall_finder=g_pNetworkMessages` explicitly selects one or more comma-separated object names. It requires an explicit `-modules=...`; every selected object is processed for every selected module, and `*` is not supported.
- `vcall_finder` objects are not registered in `configs/<GAMEVER>.yaml`. If an object is absent from every selected module and platform, the command fails instead of aggregating stale detail files.
- The script exports full disassembly and pseudocode for each referencing function into `vcall_finder/{gamever}/{object_name}/{module}/{platform}/`, then runs LLM aggregation after all module/platform IDA work finishes.
- If a detail YAML already has a top-level `found_vcall`, that function skips the LLM call and reuses the cached result. A successful response immediately writes `found_vcall: [...]` or `found_vcall: []` back to the detail YAML.
- `vcall_finder/{gamever}/{object_name}.txt` is an appended YAML document stream. Each record directly contains `insn_va`, `insn_disasm`, and `vfunc_offset` without a nested `found_vcall` wrapper.

Example:

```bash
uv run ida_analyze_bin.py -gamever=14141 -modules=networksystem -platform=windows -vcall_finder=g_pNetworkMessages -llm_model=gpt-5.4 -llm_apikey=your-key -llm_effort=high -llm_fake_as=codex -llm_baseurl=http://127.0.0.1:8080/v1
```

Example outputs:

- `vcall_finder/14141/g_pNetworkMessages/networksystem/windows/sub_140123450.yaml`
- `vcall_finder/14141/g_pNetworkMessages.txt`

## IDA preprocessor string setup

`CS2VIBE_STRING_MIN_LENGTH` controls optional IDA string-list setup for preprocessor string enumeration only:

- Unset or empty: do not call `idautils.Strings.setup`; use the IDB current string-list state.
- Integer `>=1`: call `idautils.Strings.setup(strtypes=[ida_nalt.STRTYPE_C], minlen=<value>)` when the current IDB has not already been set up with the same parameters.
- Non-integer or values `<1`: fall back to `4` and use the same IDB-level setup guard.
- Setup state is stored per IDB; changing the effective `minlen` triggers setup again.
- This is not an LLM parameter.

For `LLM_DECOMPILE` inputs, continue with [Reference YAML for `LLM_DECOMPILE`](reference-yaml.md). For immutable candidate creation and downstream validation, continue with [Snapshots and gamedata](snapshot-and-gamedata.md).
