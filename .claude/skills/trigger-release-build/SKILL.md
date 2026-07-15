---
name: trigger-release-build
description: Safely dispatch the repository release build from the immutable current origin/main SHA. Use only when explicitly asked to rebuild or republish a game version, including requests such as “重新发布 14170”, “使用当前 main 重建 14170 的 release”, or “触发最新游戏版本的 release build”.
disable-model-invocation: true
---

# Trigger Release Build

Use the bundled script as the only remote-operation entry point. Do not construct an ad-hoc `gh workflow run`
command, accept a user-supplied SHA, move a tag, edit a Release, cancel work, or merge an output PR.

## Procedure

1. Extract the requested game version, or use `latest` only when the user explicitly asks for the latest version.
2. Run from any directory:

   ```powershell
   uv run python .claude/skills/trigger-release-build/scripts/trigger_release_build.py <GAMEVER-or-latest>
   ```

3. Report the script's selected version, full `SOURCE_SHA`, commit subject, and Actions run URL.
4. If the script refuses the operation, surface its exact safety reason and stop. Do not bypass repository, auth,
   version, tag/Release, duplicate-work, or `origin/main` checks.

The script always dispatches `mode=republish` with full validation and affected-output invalidation fixed by the
workflow. Any requested generator/config change must already be merged into `origin/main`.
