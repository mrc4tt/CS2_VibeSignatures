---
name: abandon-staged-release
description: Safely dispatch the protected recovery workflow that explicitly abandons one merged generated-output PR's unpromoted staged release state. Use only when the user explicitly asks to abandon or clean a specific blocked staged build after promotion failed before promote-bin.
---

# Abandon Staged Release

Use the bundled script as the only remote-operation entry point. Do not run `cleanup-unmerged`, delete `READY`,
remove staging paths manually, accept a user-supplied SHA/path, resume promotion, or trigger a replacement build.

## Procedure

1. Require an explicit merged generated-output PR number, exact confirmation, and one-line reason.
2. Run from any directory:

   ```powershell
   uv run python .claude/skills/abandon-staged-release/scripts/abandon_staged_release.py `
     <PR_NUMBER> `
     --confirm "ABANDON <GAMEVER>/<BUILD_ID>" `
     --reason "<WHY_PROMOTION_IS_BEING_ABANDONED>"
   ```

3. Report the PR URL, derived game version/build ID/head SHA, reason, and Actions run URL.
4. If the script or workflow refuses the operation, surface the exact safety reason and stop. Never bypass repository,
   PR author/repository/base/branch, confirmation, active-run, promotion-marker, recovery-path, or index/manifest checks.

The workflow only removes the matching staged directory and PR index. It refuses any state containing
`PROMOTION_STARTED`, `PROMOTED.json`, `PROMOTION_COMPLETE`, or matching accepted-bin incoming/backup paths. It never
modifies accepted `bin/<GAMEVER>` and never automatically reruns a release build.
