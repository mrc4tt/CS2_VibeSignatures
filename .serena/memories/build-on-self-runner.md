# staged release workflow

## Overview

正式 release 生命周期已拆成 build、review、promotion 三个阶段。`.github/workflows/build-on-self-runner.yml`
只生成并验证 pending output；generated-output PR 的 merge 是 accepted bin、版本 tag 与 GitHub Release 的唯一晋升门。

## Responsibilities

- `build-on-self-runner.yml`：接收 `repository_dispatch` 或 machine-oriented `workflow_dispatch`，从完整
  `SOURCE_SHA` checkout；运行正常 analyzer producer scheduling、candidate/gamedata/C++ 全量验证；写 tracked
  release manifest；stage bin/private manifest；创建 immutable output PR 后停止。
- `validate-generated-output-pr.yml`：轻量验证 Bot、same-repository、branch、允许路径、base/source SHA 与 tracked hash。
- `promote-release-after-output-merge.yml`：只处理可信且已 merge 的 output PR；复核 merge parents、PR index、private
  manifest、tracked output 与 staged bin；归档后事务式晋升 bin；执行 new/republish tag 规则；上传并回读验证 Release assets。
- `release_workflow.py` / `release_workflow_lib/`：canonical JSON、inventory/hash、path containment、reparse-point 防护、
  READY/index identity、transactional swap、recovery marker 与 CLI。

## Architecture

1. 自动新版本由 bump PR merge workflow dispatch `{gamever, source_sha, mode=new, source_pull_request}`；不提前打 tag。
2. 显式调用 `.claude/skills/trigger-release-build/` 时，skill 从 `origin/main` 解析 immutable SHA，并根据 tag/Release
   的一致状态自动选择 `mode=new` 或 `mode=republish` 后 dispatch；常规新版本仍优先走上一条自动 bump 路径。
3. build preflight 在 GitHub-hosted runner 校验 allowlist、完整 SHA、default-branch reachability、`download.yaml` membership、
   tag/Release mode guards 与重复 output PR，再占用 Windows self-hosted runner。
4. republish 从 accepted manifest 的前一 `source_sha` 恢复 snapshot，并复用 source-aware affected-output invalidation；
   `-oldgamever none` 仅用于 `major_update: true`。
5. validated candidate 发布到工作树后，`stage-build` 创建 tracked manifest 和 pending bin；output commit 后绑定 PR head SHA、
   写 READY，PR 创建后写 `pr-index/<PR>.json`。
6. output branch 为 `gamesymbols/build/<GAMEVER>/<RUN_ID>-<RUN_ATTEMPT>`，从不 force-push。
7. promotion 要求 merge commit first parent 等于 `SOURCE_SHA`、second parent 等于 indexed PR head；默认分支若前进则拒绝。
   PR check 和 promotion 都从 PR base 单独 checkout trusted helper，避免执行待校验 merge 中可能被替换的授权代码。
8. accepted bin 先复制到 sibling incoming 并复核 inventory，再在 per-version lock 下 swap；旧目录保留到 Release assets
   上传并下载 hash 校验成功，最后写 `PROMOTION_COMPLETE` 并删除 backup/index。

## Identity And Storage

- `GAMEVER`：`download.yaml` 中的版本（支持数字和单字母后缀）。
- `SOURCE_SHA`：generator/config/skill/test 的 immutable default-branch commit。
- `OUTPUT_MERGE_SHA`：接受 snapshot、`dist/` 和 tracked manifest 的 output PR merge commit。
- `RELEASE_TAG`：通常等于 `GAMEVER`；new 创建在 `OUTPUT_MERGE_SHA`，republish 永不移动已有 tag。
- pending：`PERSISTED_WORKSPACE/release-staging/<GAMEVER>/<BUILD_ID>`。
- accepted：`PERSISTED_WORKSPACE/bin/<GAMEVER>`。
- canonical tracked output：`gamesymbols/<GAMEVER>.yaml`、`dist/`、`release-manifests/<GAMEVER>.json`。

## Failure Signals And Recovery

- output PR 未 merge：cleanup 只能通过 matching PR index 删除 pending staging，不能访问 accepted bin。
- archive/tag/upload 失败：READY、private manifest、staged bin 和 promoted backup 保留，promotion 可重跑。
- `promote-bin` 在触碰 accepted bin 前写 `PROMOTION_STARTED`；显式 abandon 仅允许该 marker、`PROMOTED.json`、
  `PROMOTION_COMPLETE` 及 matching incoming/backup 全部不存在时删除 staged directory 与 PR index。
- `.claude/skills/abandon-staged-release/` 接受显式 `GAMEVER/BUILD_ID`，或 staged build 自身 / 唯一被其 READY
  状态阻塞的可信 Actions run URL；客户端从 exact output branch 自动发现唯一 merged Bot PR 与 head SHA，再只 dispatch
  受保护的 `abandon-staged-release.yml`。workflow 继续复用 per-version promotion concurrency 与 `win64` environment。
- existing target 已等于 staged inventory：`promote-bin` 作为幂等重试成功返回，不重复 swap。
- Release assets 使用 `--clobber`，随后下载每个 asset 并比较 SHA-256；未验证成功前不写 completion marker。

## Verification

- `tests/test_release_workflow.py`：branch protocol、old-version baseline、manifest/hash/path/reparse/index/swap/idempotency。
- `tests/test_release_workflow_guards.py`：tag mode guards、无 manifest 保守 baseline、显式 legacy bootstrap、stale
  source/merge、cleanup/abandon 与 promotion recovery marker。
- `tests/test_build_self_runner_workflow.py`：trigger/checkout/order/no-premerge-publication/promotion/tag/bump/lightweight check。
- `tests/test_trigger_release_build.py`：repository/auth/version/tag/Release/duplicate/dispatch/run URL。
- `tests/test_abandon_staged_release.py`：Skill 显式 target、run/log blocker identity、唯一可信 merged PR 自动发现、
  confirmation/reason、duplicate dispatch 与 recovery workflow。
- `build-on-self-runner.yml` 的 runtime gate 是 `format_repo_files.py --check`（Ruff format + yamlfix）与全仓
  `python -m unittest discover -s tests -b`；standalone `ruff check`、actionlint、独立 YAML parse 与 CLI
  non-publishing smoke 不属于该 build workflow 的运行步骤。

## Explicit Legacy Bootstrap

- `invalidate-republish` 检测到 accepted `release-manifests/<GAMEVER>.json` 时，从其中的前一 `source_sha`
  恢复 snapshot 并执行 source/config-aware invalidation；manifest 缺失且未显式启用 legacy bootstrap 时不会直接失败，
  而是保守删除同版本全部 YAML baseline。
- 只有 trigger skill 在用户明确要求“无 accepted manifest 时使用 tracked snapshot”后，才传
  `--allow-legacy-bootstrap` / `allow_legacy_bootstrap=true`；普通 publish、republish、retry 或 same-version 请求不得推断启用。
- legacy 路径只允许 `workflow_dispatch + mode=republish`，`repository_dispatch` 被 preflight 拒绝。
- legacy snapshot 从 immutable `SOURCE_SHA` 读取；其最后发布 commit 必须是 `SOURCE_SHA` 祖先，并使用该 commit 的历史
  versioned config（允许 legacy root config）验证 canonical snapshot contract，再恢复并执行 source/config-aware invalidation。
- 该开关提供显式 opt-in，而非可证明的“由 skill 发起”身份认证；GitHub workflow 无法区分同权限维护者手工构造的等价 dispatch。

## Callers

- `repository_dispatch.types: [build-on-self-runner]`
- `workflow_dispatch(gamever, source_sha, mode, allow_legacy_bootstrap=false)`，通常仅由 trigger SKILL 调用
- `workflow_dispatch(pr_number, confirmation, reason)`：仅由 `abandon-staged-release` Skill 显式调用
