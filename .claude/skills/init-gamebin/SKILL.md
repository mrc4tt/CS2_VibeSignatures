---
name: init-gamebin
description: Initialize this repository's local game binaries for an exact GAMEVER from download.yaml or its latest entry, delegate symbol YAML restoration to restore-from-snapshot, and optionally rename known functions in IDA databases. Use only when explicitly asked to initialize or restore gamebin/bin state for a CS2 game version.
---

# Initialize Game Binaries

Use the bundled script as the only entry point for downloading, merging, and depot fallback. Never overwrite an existing
binary, substitute an unlisted version, or continue after a failed step. Delegate all symbol snapshot behavior to the
project-level `$restore-from-snapshot` skill; do not call `gamesymbol_snapshot.py` or restore YAML locally in this skill.

## Select GAMEVER

1. Extract an exact `GAMEVER` from the user's request. Resolve `latest` only when the user explicitly requests latest.
2. If the user did not specify a version, run:

   ```powershell
   uv run python .claude/skills/init-gamebin/scripts/init_gamebin.py versions
   ```

   Tell the user which entry is latest and ask: `Which GAMEVER do you want to initialize?`
   Wait for an explicit version before continuing.
3. Reject values absent from `download.yaml`; do not guess or silently use latest.

## Prepare Binaries

Run from the owning repository root:

```powershell
uv run python .claude/skills/init-gamebin/scripts/init_gamebin.py prepare <GAMEVER-or-latest>
```

The script checks existing binaries, downloads and non-overwritingly merges `gamebin-<GAMEVER>.7z` when needed, and uses
the Steam depot fallback only for a missing Release asset.

If the command fails, stop immediately and report its exact error as:

```text
<skill_error>ERROR REASON</skill_error>
```

Do not attempt an alternate download, edit `.env`, or proceed to symbol restoration or IDA renaming.

## Restore Symbol YAML

After binary preparation succeeds, invoke the project-level `$restore-from-snapshot` skill with the selected GAMEVER.
Follow that skill's trusted restore, base-snapshot suggestion, explicit yes/no confirmation, and result handling exactly.
Do not duplicate its commands or safety rules here.

## Offer IDB Renaming

After `$restore-from-snapshot` finishes, inspect its final result. If it reports
`Symbol snapshot: unavailable; no YAML restored`, report the selected GAMEVER and finish successfully. Do not ask about
IDB renaming or run IDB renaming for a GAMEVER without restored symbols.

When either a trusted snapshot or a user-confirmed forced base snapshot was restored successfully, ask user:
`Need to sync existing symbols to idb?`

- If the user declines, report the selected GAMEVER and finish.
- If the user confirms, search `bin/<GAMEVER>/*/*.id0`. If any lock file exists, stop, list every path, and tell the
  user to close the corresponding IDA instances.
- Otherwise run the following command without a timeout, wait for its real exit status, and do not poll unnecessarily (the shell may take a very long time, typically 30 mins):

  ```bash
  uv run ida_analyze_bin.py -gamever <GAMEVER> -configyaml configs/<GAMEVER>.yaml -debug -rename >> /tmp/bump_idb_output.log 2>&1
  ```

On success, report the summary from the final 20 log lines and the full log path. On failure, read the final 60 lines;
if needed, locate the last `Error`, `Failed`, or `Traceback` entries. Report the exit code and relevant excerpt inside
`<skill_error>...</skill_error>`, then stop without attempting repairs.
