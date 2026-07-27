[返回中文 README](../../README_CN.md) | [English](../en/conributing-via-pr.md) | [创建符号分析 skill](creating-skills.md)

# 通过 Pull Request 贡献符号分析 skill

完成符号分析 skill 的创建并在本地验证后，可使用 `SKILL: create-pr`（调用方式为 `/create-pr`）将其共享到项目中。该 skill 会按仓库要求依次完成 candidate 准备、验证、发布、提交、推送和创建 Pull Request。

## 调用 `create-pr` 前

1. 先完成该 skill 的专项检查。对于新的符号分析 skill，通常包括新的 `SKILL.md`、preprocessor 或辅助脚本，以及对应的配置或 reference 更新。
2. 在仓库根目录只暂存本次贡献涉及的文件，不要使用全仓库 add 命令：

   ```bash
   git add -- .claude/skills/<skill-name>/SKILL.md
   git add -- <preprocessor-or-supporting-files> <config-or-reference-files>
   git diff --cached --name-only
   ```

3. 确认没有未暂存的 tracked changes。已有的无关 untracked files 可以保留未跟踪状态，`create-pr` 会保留它们。
4. 确认仓库存在 `origin` remote，且 `gh auth status` 认证成功。必须解析出唯一的游戏版本：可以向 skill 传入 `gamever`，也可以在 `.env` 中设置 `CS2VIBE_GAMEVER`。

`gamesymbols/<GAMEVER>.yaml` 与 `gamedata/<GAMEVER>/` 属于生成输出。通过验证后由 `create-pr` 发布，无需在此流程中手动暂存。

## 调用 skill

可以这样请求 agent：

```text
Use SKILL: create-pr to share the staged symbol-analysis skill.
gamever: 14156
branch: dev-find-example
commit_title: feat(skills): add find-example symbol-analysis skill
```

`branch`、commit title、PR 标题/正文以及 issue 编号都是可选的；省略时，`create-pr` 会根据 staged diff 生成合适的值。它会从 `dev*` 分支针对 `main` 创建 PR，不会直接向 `main` 提交。

## `create-pr` 执行的步骤

该流程按顺序执行以下门禁：

1. 记录并检查准确的 staged paths。
2. 针对选定的游戏版本运行 `/prepare-post-change-candidate`。
3. 对 immutable candidate 运行 `/post-change-validation`。
4. 仅在验证成功后运行 `/publish-post-change-candidate`。
5. 只暂存授权范围内的格式化变更和当前版本生成输出。
6. 按仓库 Conventional Commit 格式提交，并附带 `Co-Authored-By: Codex`。
7. 推送 `dev*` 分支，并针对 `main` 创建一个 PR。

如果没有 staged changes、存在未暂存 tracked changes、认证失败、任一门禁失败或出现未预期的路径变化，skill 会在提交和创建 PR 前停止。不要绕过失败门禁，也不要手动发布 candidate。

## 完成后

记录 skill 返回的分支、commit SHA、PR URL、游戏版本、candidate SHA-256 和最终提交路径列表，并检查 PR 确实只包含目标 skill、其配套文件，以及选定游戏版本的生成输出。
