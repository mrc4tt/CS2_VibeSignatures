---
name: init-gamebin
description: Initialize this repository's local game binaries for an exact GAMEVER from download.yaml or its latest entry, restore tracked game-symbol YAML artifacts, and optionally rename known functions in IDA databases. Use only when explicitly asked to initialize or restore gamebin/bin state for a CS2 game version.
---

# Initialize Game Binaries

Use the bundled script as the only entry point for downloading, merging, depot fallback, and snapshot restoration. Never
overwrite an existing file, substitute an unlisted version, or continue after a failed step.

## Select GAMEVER

1. Extract an exact `GAMEVER` from the user's request. Resolve `latest` only when the user explicitly requests latest.
2. If the user did not specify a version, run:

   ```powershell
   uv run python .claude/skills/init-gamebin/scripts/init_gamebin.py versions
   ```

   Tell the user which entry is latest and ask: `Which GAMEVER do you want to initialize?` / `需要初始化哪个GAMEVER?` Wait for an explicit version before continuing.
3. Reject values absent from `download.yaml`; do not guess or silently use latest.

## Prepare Binaries and YAML

Run from the owning repository root:

```powershell
uv run python .claude/skills/init-gamebin/scripts/init_gamebin.py prepare <GAMEVER-or-latest>
```

The script checks existing binaries, downloads and non-overwritingly merges `gamebin-<GAMEVER>.7z` when needed, uses
the Steam depot fallback only for a missing Release asset, then restores and verifies `gamesymbols/<GAMEVER>.yaml`.

If the command fails, stop immediately and report its exact error as:

```text
<skill_error>ERROR REASON</skill_error>
```

Do not attempt an alternate download, add `-replace`, edit `.env`, or proceed to IDA renaming.

## Offer IDB Renaming

After preparation succeeds, ask exactly: `Need to sync existing symbols to idb?` / `需要将已知函数名同步/重命名到idb里?`

- If the user declines, report the selected GAMEVER and finish.
- If the user confirms, search `bin/<GAMEVER>/*/*.id0`. If any lock file exists, stop, list every path, and tell the
  user to close the corresponding IDA instances.
- Otherwise run the following command without a timeout, wait for its real exit status, and do not poll unnecessarily:

  ```bash
  uv run ida_analyze_bin.py -gamever <GAMEVER> -debug -rename >> /tmp/bump_idb_output.log 2>&1
  ```

On success, report the summary from the final 20 log lines and the full log path. On failure, read the final 60 lines;
if needed, locate the last `Error`, `Failed`, or `Traceback` entries. Report the exit code and relevant excerpt inside
`<skill_error>...</skill_error>`, then stop without attempting repairs.
