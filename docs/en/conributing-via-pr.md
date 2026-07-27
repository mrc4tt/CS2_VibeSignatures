[Back to README](../../README.md) | [中文](../zh-CN/conributing-via-pr.md) | [Creating skills](creating-skills.md)

# Contributing symbol-analysis skills via a pull request

After creating and verifying a symbol-analysis skill, use `SKILL: create-pr` (invoked as `/create-pr`) to share it with the project. The skill takes the staged change through the repository's candidate preparation, validation, publication, commit, push, and pull-request workflow.

## Before invoking `create-pr`

1. Finish the skill's implementation-specific checks. For a new symbol-analysis skill, this normally includes the new `SKILL.md`, its preprocessor or supporting scripts, and the corresponding configuration or reference updates.
2. From the repository root, stage only the files that belong to this contribution. Do not use repository-wide add commands:

   ```bash
   git add -- .claude/skills/<skill-name>/SKILL.md
   git add -- <preprocessor-or-supporting-files> <config-or-reference-files>
   git diff --cached --name-only
   ```

3. Make sure there are no unstaged tracked changes. Existing unrelated untracked files can remain untracked; `create-pr` will preserve them.
4. Ensure the repository has an `origin` remote and that GitHub CLI authentication (`gh auth status`) succeeds. Resolve exactly one game version, either by passing `gamever` to the skill or by setting `CS2VIBE_GAMEVER` in `.env`.

Generated `gamesymbols/<GAMEVER>.yaml` and `gamedata/<GAMEVER>/` files are published by `create-pr` after validation. They do not need to be added manually for this workflow.

## Invoke the skill

Ask the agent to run the skill, for example:

```text
Use SKILL: create-pr to share the staged symbol-analysis skill.
gamever: 14156
branch: dev-find-example
commit_title: feat(skills): add find-example symbol-analysis skill
```

`branch`, `commit_title`, PR title/body, and an issue number are optional. If omitted, `create-pr` derives suitable values from the staged diff. It creates the PR from a `dev*` branch against `main`; it never commits directly to `main`.

## What `create-pr` does

The workflow runs these gates in order:

1. Captures and checks the exact staged paths.
2. Runs `/prepare-post-change-candidate` for the selected game version.
3. Runs `/post-change-validation` against that immutable candidate.
4. Runs `/publish-post-change-candidate` only after validation succeeds.
5. Stages only authorized formatter changes and current-version generated outputs.
6. Commits with the repository's Conventional Commit format and `Co-Authored-By: Codex`.
7. Pushes the `dev*` branch and opens one PR against `main`.

The skill stops before commit or PR creation when there are no staged changes, unstaged tracked changes, missing authentication, a failed or non-runnable gate, or an unexpected path change. Do not bypass a failed gate or manually publish the candidate.

## After the skill finishes

Record the reported branch, commit SHA, PR URL, game version, candidate SHA-256, and final committed path list. Review the PR to confirm that it contains the intended skill and supporting files, plus only the generated outputs for the selected game version.
