---
name: create-pr
when_to_use: when user request to create a PR
description: |
  Deliver already-staged repository changes through the full post-change candidate lifecycle and open a GitHub
  pull request. Use after implementation-specific tests pass and all task-related source/config/reference changes
  are explicitly staged. Prepares, validates, and publishes the immutable candidate; refreshes only the original
  staged paths plus current-version generated outputs; commits on a dev branch; pushes; and creates the PR.
---

# Create Pull Request

Create one pull request from the caller's staged changes. Treat the index at invocation time as the authorized
change set. The only additional paths this workflow may stage are the formatter updates to those same paths and
the validated `gamesymbols/<GAMEVER>.yaml` / `gamedata/<GAMEVER>/` outputs produced by publication.

## Inputs

- `gamever` - use the caller-provided value. If omitted, read `CS2VIBE_GAMEVER` from `.env`.
- `branch` - optional `dev*` branch name. If omitted while on `main`, derive a concise `dev-<topic>` name from the
  staged change.
- `commit_title` - optional Conventional Commit title. If omitted, derive it from the staged diff.
- `pr_title` / `pr_body` - optional PR text. If omitted, derive it from the staged diff and actual validation
  results.
- `issue` - optional GitHub issue number. Add `Closes #<issue>` to the PR body when supplied.

Resolve exactly one non-empty `GAMEVER`. Set `ANALYSIS_CONFIG="configs/$GAMEVER.yaml"` and stop if that file does
not exist. Never fall back to another game version.

## Safety Rules

- Run from the repository root and require an `origin` remote plus successful `gh auth status`.
- Never commit directly to `main`, force-push, amend an existing commit, or use `git add -A` / `git add .`.
- Preserve unrelated untracked files and never stage them.
- Require zero unstaged tracked changes at invocation. This forbids partially staged paths and prevents the
  formatter from absorbing unrelated work.
- Treat the initial staged path list as immutable authorization. Do not add other source, config, reference, test,
  or documentation paths after the gates run.
- Stop on the first failed/non-runnable gate. Do not repair or retry inside this skill, and do not commit, push, or
  create a PR after a gate failure.

## Step 1: Capture and Guard the Staged Change

Record the current branch and complete status, then inspect the index:

```bash
git branch --show-current
git status --short
git diff --cached --quiet
git diff --cached --name-only
git diff --cached --name-status
git diff --cached --stat
git diff --name-only
git ls-files --others --exclude-standard
git remote
gh auth status
git fetch origin main --prune
git rev-parse HEAD
git rev-parse origin/main
```

`git diff --cached --quiet` must exit `1`, proving that staged changes exist. Exit `0` means there is nothing to
deliver; stop with:

```text
<skill_error>create-pr cannot run: no staged changes were provided.</skill_error>
```

Save the exact `git diff --cached --name-only` result as `INITIAL_STAGED_PATHS`, including staged additions,
renames, and deletions. Read `git diff --cached` to understand the change, detect accidentally staged unrelated
files or credentials, and derive the commit/PR summary.

`git diff --name-only` must be empty. If any unstaged tracked change exists, stop before formatting or candidate
creation and report the paths. Untracked files may remain, but record them and never stage them.

Validate the intended branch before running expensive gates:

- On `main`, choose the caller-provided `branch` or derive a valid, unused `dev-<topic>` name. Validate it with
  `git check-ref-format --branch <dev-branch>` and require that it does not exist locally or on `origin`.
- On an existing `dev*` branch whose `HEAD` still equals `origin/main`, use that branch unless the caller explicitly
  supplied the same name.
- On any other branch, stop and ask the caller to use `main` or a `dev*` branch.
- Check `gh pr list --state open --head <dev-branch> --json url`. Stop if an open PR already exists for the
  intended branch. Never create a duplicate PR.

## Step 2: Prepare the Immutable Candidate

**ALWAYS** Use SKILL `/prepare-post-change-candidate` with the resolved `gamever`.

Retain the returned candidate path, candidate session path, gamedata session path, and candidate SHA-256. If the
skill fails, stop the entire task.

After preparation, inspect `git diff --name-only`. Formatting may have changed a path only when it belongs to
`INITIAL_STAGED_PATHS`. If any other tracked path changed, stop and report it; do not stage it or continue.

## Step 3: Validate the Exact Candidate

**ALWAYS** Use SKILL `/post-change-validation` with the same `gamever`, candidate path, and candidate session path
returned by `/prepare-post-change-candidate`.

Require explicit success, runnable C++ tests, and zero failure counters. If validation fails or is non-runnable,
stop exactly as that skill requires. Do not publish, commit, push, or create a PR.

## Step 4: Publish the Validated Candidate

Only after validation succeeds, **ALWAYS** Use SKILL `/publish-post-change-candidate` with the same `gamever`,
candidate path, candidate session path, and gamedata session path.

Require the published snapshot SHA-256 to equal the validated candidate SHA-256. Publication may modify only:

- existing paths in `INITIAL_STAGED_PATHS` that were reformatted;
- `gamesymbols/$GAMEVER.yaml`;
- files under `gamedata/$GAMEVER/`.

Compare `git status --short` with the status recorded in Step 1. Any new or modified path outside that allowlist is
a hard stop. Preserve pre-existing unrelated untracked files and leave them untracked.

## Step 5: Refresh the Authorized Index

Refresh formatter changes only for existing files in `INITIAL_STAGED_PATHS`, passing every path explicitly:

```bash
git add -- <explicit-existing-initial-staged-paths>
git add -- "gamesymbols/$GAMEVER.yaml" "gamedata/$GAMEVER"
```

Already-staged deletions need no refresh. Never use a repository-wide add command.

Then verify:

```bash
git diff --name-only
git diff --cached --quiet
git diff --cached --name-only
git diff --cached --stat
```

Require zero unstaged tracked changes and a non-empty staged diff. Every final staged path must be either an initial
staged path or an allowed current-version publication path. Review the final cached diff before committing.

## Step 6: Create the Commit on a Dev Branch

If currently on `main`, create the validated branch now:

```bash
git switch -c <dev-branch>
```

If already on the intended `dev*` branch, remain there. Derive or validate `commit_title` using the repository
format `<type>(scope): <summary>`: start with a verb, keep it at most 100 characters, and omit the final period.

Commit exactly the staged index:

```bash
git commit -m "<commit_title>" -m "Co-Authored-By: Codex"
```

Verify the new commit's changed paths match the final staged path list and that no unstaged tracked changes remain.
Do not amend if the verification fails; stop and report the mismatch.

## Step 7: Push and Create the Pull Request

Push without force:

```bash
git push -u origin <dev-branch>
```

Build the PR title from `pr_title` or the commit title. Build the body from the committed staged diff and actual
results, using this concise shape:

```markdown
## Summary
- <behavioral change>
- <supporting change>

## Validation
- implementation-specific tests: <commands/results supplied by the caller>
- candidate preparation: passed for `<GAMEVER>`
- C++ post-change validation: passed with runnable tests and zero failures
- candidate publication: passed; published SHA-256 matches the validated candidate

Closes #<issue>
```

Omit the issue line when no issue was supplied. Create the PR explicitly against `main`:

```bash
gh pr create --base main --head <dev-branch> --title "<pr_title>" --body "<pr_body>"
```

Report the branch, commit SHA, pushed remote, PR URL, game version, candidate SHA-256, and the final committed path
list. If push succeeds but PR creation fails, report the remote branch and exact failure; do not delete the branch,
force-push, or create a second commit.

## Checklist

- [ ] Initial cached diff is non-empty and contains only task-related changes.
- [ ] No unstaged tracked changes existed before candidate preparation.
- [ ] `/prepare-post-change-candidate` succeeded for the resolved game version.
- [ ] `/post-change-validation` ran real C++ tests and succeeded for the exact candidate.
- [ ] `/publish-post-change-candidate` published the same validated candidate.
- [ ] Final staged paths are limited to initial staged paths plus current-version publication outputs.
- [ ] Commit is on a `dev*` branch and follows the repository commit format.
- [ ] Branch was pushed without force and exactly one PR was created against `main`.
