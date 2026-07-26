# Ordinary PR Gamedata Consistency Gate

## Status

本文记录普通开发 PR 同时提交 `gamesymbols/<GAMEVER>.yaml` 与 `gamedata/<GAMEVER>/`，并由 PR CI
只读验证两类 tracked output 与同一 immutable candidate 一致的已确认设计。

状态：已实施。

本计划扩展 `track-gamesymbols-snapshot.md` 和 `candidate-snapshot-as-symbol-store.md` 的普通 PR expected-output
契约，但不改变以下既有边界：

- 普通 PR CI 不调用 `publish`，不改写 tracked files，也不 commit/push。
- `publish-post-change-candidate` 只能发布同一 game version、candidate 和 session 中已经通过完整 C++ validation 的 symbol 与 gamedata candidate。
- 新 game version 仍由 `build-on-self-runner.yml` 在 bump PR 合并后构建。
- generated-output PR 仍是 release manifest、staged bin、tag 和 GitHub Release 的 acceptance/promotion boundary。

## Decision Summary

会影响 analysis output 或 gamedata generator output 的普通开发 PR 必须在同一个 PR 中提交：

```text
gamesymbols/<GAMEVER>.yaml
gamedata/<GAMEVER>/
```

本地交付流程使用现有 transaction：

```text
prepare-post-change-candidate
        -> post-change-validation
        -> publish-post-change-candidate
        -> explicitly stage snapshot + gamedata
```

普通 PR CI 使用另一条只读流程：

```text
actual symbol candidate
        -> compare PR head snapshot
        -> build guarded gamedata candidate
        -> compare PR head gamedata inventory
        -> C++ validation
        -> complete without publish
```

核心不变量：

```text
PR head gamesymbols/<GAMEVER>.yaml == actual symbol candidate bytes

PR head gamedata/<GAMEVER>/ inventory == guarded gamedata candidate inventory
```

其中 gamedata inventory 至少绑定每个 canonical path 的 raw-byte size 与 SHA-256，并绑定 generator contract、
analysis config 和 symbol candidate identity。

## Background

当前普通 PR 已经对 symbol snapshot 建立了完整的 expected/actual 边界：

1. 从可信 base snapshot restore deterministic baseline。
2. 使用 PR head code/config 执行 invalidation 和 analysis。
3. strict-pack actual symbol candidate。
4. 将 actual candidate 与 PR head `gamesymbols/<GAMEVER>.yaml` 比较。
5. 使用 actual candidate 构建 gamedata 并运行 C++ tests。

本地 `/create-pr` 流程也已经要求按顺序调用：

```text
/prepare-post-change-candidate
/post-change-validation
/publish-post-change-candidate
```

`publish-post-change-candidate` 会把同一 validated symbol candidate 和 guarded gamedata candidate 分别发布到：

```text
gamesymbols/<GAMEVER>.yaml
gamedata/<GAMEVER>/
```

但是普通 PR CI 当前只 guard 临时 gamedata candidate 自身，没有将其与 PR head 中 tracked
`gamedata/<GAMEVER>/` 比较。结果是两类 expected output 的门禁不对称：

| Tracked output | Local `/create-pr` publishes | Ordinary PR CI compares with actual candidate |
| --- | --- | --- |
| `gamesymbols/<GAMEVER>.yaml` | Yes | Yes |
| `gamedata/<GAMEVER>/` | Yes | No |

因此，下列错误当前可能绕过普通 PR CI：

- symbol candidate 已变化，但提交者忘记更新 gamedata。
- gamedata generator/config 已变化，但 PR 仍保留旧输出。
- PR 删除或新增了错误的 gamedata 文件。
- PR 手工修改 generated gamedata，使其不再对应本次 candidate。
- PR 只提交匹配的 snapshot，却没有提交同一 validated transaction 产生的 gamedata。

## Goals

- 让普通开发 PR 原子审查 producer/config/source、symbol snapshot 和 gamedata output。
- 保证默认分支上的 canonical snapshot 与 canonical gamedata 始终来自同一 validated candidate transaction。
- 让普通 PR CI 对 snapshot 和 gamedata 使用对称的 expected/actual comparison。
- 复用 `gamedata_candidate` session 中已有的 path、size、SHA-256、candidate、config 和 generator-contract identity。
- 保持 CI `contents: read`，不增加自动 commit、push 或 PR mutation 权限。
- 只验证当前 `VALIDATION_GAMEVER`，不 fan out 到历史或相邻版本。
- mismatch 时提供 path-level added/missing/modified diagnostics，而不是输出完整 generated files。
- 保持 generated-output PR 对正式 Release acceptance/promotion 的独占职责。

## Non-Goals

- 不让普通 PR CI 调用 `gamesymbol_candidate.py publish` 或 `gamedata_candidate.py publish`。
- 不让 CI 自动修复、stage、commit 或 push 提交者遗漏的 gamedata。
- 不把 PR head snapshot 或 PR head gamedata 作为 actual downstream input。
- 不重新运行或重新序列化已经 guard 的 gamedata candidate。
- 不在普通 bump PR 中提前生成尚未被接受的新 `PR_GAMEVER` output。
- 不替代 generated-output PR 的 release manifest、pending staging、promotion、tag 或 Release validation。
- 不允许人工编辑 gamedata 后通过降低 hash、path 或 generator-contract validation 来兼容。
- 不要求与 analysis/gamedata 无关的 PR 制造无意义 generated-output diff。

## Scope Policy

### Output-Affecting Ordinary PR

适用于可能改变当前 accepted game version 输出的修改，例如：

- analysis config、preprocessor、Agent SKILL、reference 或 analyzer output logic。
- `gamedata-generators/**`、gamedata mapping/config 或 shared generator helpers。
- 会改变 candidate formal file set、symbol payload 或 downstream rendering 的代码。

提交者必须运行完整 post-change transaction，并在实际 bytes 变化时提交 snapshot 与 gamedata。某一类输出最终
没有变化是允许的；CI comparison 用于证明它确实没有变化。

### Output-Neutral Ordinary PR

纯文档、无关测试、frontend 或其他不能影响 analysis/gamedata output 的修改不需要人为重写 generated files。
普通 PR CI 可以继续验证当前 tracked outputs 与实际 candidate 一致；如果 bytes 未变化，PR diff 中无需包含它们。

### New Game Version Bump PR

普通 PR self-runner 使用可信 base snapshot 的 `BASE_GAMEVER` 作为 `VALIDATION_GAMEVER`，不会提前构建 head
`download.yaml` 引入的新 `PR_GAMEVER`。新版本 snapshot 和 gamedata 仍由 bump merge 后 dispatch 的
`build-on-self-runner.yml` 生成，并通过 generated-output PR 接受。

因此，新版本 bump PR 不因本计划而被要求提交尚未构建的：

```text
gamesymbols/<NEW_GAMEVER>.yaml
gamedata/<NEW_GAMEVER>/
```

### Generated-Output PR

`gamesymbols/build/<GAMEVER>/<BUILD_ID>` generated-output PR 不进入普通 PR 的重分析流程。它继续通过专用
workflow 校验 output branch identity、tracked manifest、snapshot hash、gamedata inventory 和 staged state。

如果 generated-output PR 打开后默认分支又合并了普通 output-affecting PR，则该 output PR 必须按其 immutable
`SOURCE_SHA` freshness contract 判定为 stale 并重新构建。不得通过手工 conflict resolution 拼接两次不同
candidate transaction 的 snapshot、gamedata 或 manifest。

## Trust And Authority Model

普通 PR 中存在五类不同对象：

| Object | Source | Role | Trusted as actual output |
| --- | --- | --- | --- |
| Base snapshot | `pull_request.base.sha` history | Restore baseline only | No |
| PR head snapshot | PR merge-ref Git object | Expected symbol output | No |
| Actual symbol candidate | Current analysis transaction | Actual symbol output and downstream source | Yes |
| Guarded gamedata candidate | Actual symbol candidate + head config/generators | Actual gamedata output | Yes |
| PR head gamedata | PR merge-ref Git objects | Expected gamedata output | No |

comparison 只能从 actual 指向 expected：

```text
actual symbol candidate -> compare -> PR head snapshot

guarded gamedata candidate -> compare -> PR head gamedata
```

禁止反向使用 expected output 驱动 validation：

```text
PR head snapshot -> update_gamedata
PR head gamedata -> candidate/session truth
```

### Git Object Boundary

PR head expected gamedata 必须从 checkout 对应的 immutable Git revision 读取，不能信任在测试或 analyzer 执行后
可能被修改的 working-tree files。即使 `.gitattributes` 已将 `gamedata/**` 标为 `-text`，comparison 仍应直接
枚举并读取 PR merge-ref 的 Git blobs，或将这些 blob 原字节导出到 runner temp 后再比较。

读取 Git tree 时只接受 exact root 下的 regular blobs：

```text
gamedata/<VALIDATION_GAMEVER>/
```

必须拒绝：

- root 缺失或为空，但 candidate inventory 非空。
- symlink、submodule 或非 regular-blob tree mode。
- absolute path、`.`、`..`、empty component、backslash 或 root escape。
- case-insensitive path collision。
- 当前 game version 之外的 path 被纳入 comparison。

## Developer Delivery Flow

普通开发者或 `/create-pr` caller 保持现有顺序：

1. `/prepare-post-change-candidate` 构建 immutable symbol candidate 和 gamedata candidate，并保留两个 session。
2. `/post-change-validation` 对同一 candidate/session 运行完整 C++ validation。
3. `/publish-post-change-candidate` guard 同一 candidate、candidate session 和 gamedata session。
4. 原字节发布 symbol candidate 到 `gamesymbols/<GAMEVER>.yaml`。
5. 原子发布 guarded gamedata candidate 到 `gamedata/<GAMEVER>/`。
6. 检查 publish 后 snapshot SHA-256 等于 validated candidate SHA-256。
7. 只显式 stage 当前 game version 的 snapshot 和 gamedata，以及调用者原先授权的修改。
8. 在同一 PR 中 review producer changes 与 generated-output diff。

任何 validation、guard 或 publication failure 都必须在 commit/push 前停止。不得从 tracked head snapshot、现有
tracked gamedata、`bin` 或另一个 session fallback。

## Ordinary PR CI Flow

建议在 `pr-self-runner.yml` 中采用以下顺序：

1. Checkout PR merge ref，并固定事件中的 base SHA。
2. 选择 `VALIDATION_GAMEVER`，restore base，执行 invalidation 与 analysis。
3. strict-build actual symbol candidate。
4. 从 PR head Git object 读取 expected snapshot，并与 actual candidate 比较。
5. 从 actual symbol candidate 构建 isolated gamedata candidate。
6. guard gamedata session、symbol candidate、head config 和 generator contract identity。
7. 从同一 PR head Git revision 枚举 `gamedata/<VALIDATION_GAMEVER>/` raw blobs。
8. 将 head gamedata inventory 与 guarded candidate session inventory 精确比较。
9. comparison 成功后才将 symbol candidate session 的 `gamedata` step 标记为完成。
10. 对同一 actual symbol candidate 运行 C++ tests。
11. cleanup runner-temp candidate/session；不 publish tracked files。

流程图：

```text
current PR code + restored base
              |
              v
      actual symbol candidate
              |
       +------+------+
       |             |
       v             v
compare head      build guarded
snapshot          gamedata candidate
                       |
                       v
               compare head gamedata
                       |
              +--------+--------+
              |                 |
              v                 v
           success            mismatch
              |                 |
              v                 v
         C++ validation         fail
              |
              v
    complete without publish
```

CI workflow 必须继续保持：

- `permissions: contents: read`。
- 不调用任何 publish subcommand。
- 不执行 `git add`、`git commit`、`git push` 或 GitHub PR write API。
- 不从 mutable working tree 获取 expected snapshot/gamedata identity。
- cancellation/failure 时只清理 runner temp，不修改 tracked state 或 persisted accepted state。

## CLI And Library Design

### Shared Inventory Comparison

将 `verify_published_gamedata()` 中的 inventory equality 逻辑提取为共享、只读 library boundary，例如：

```python
def compare_gamedata_inventory(
    *,
    session: Mapping[str, object],
    expected_files: Sequence[Mapping[str, object]],
) -> GamedataInventoryDiff: ...
```

`GamedataInventoryDiff` 至少报告：

- `added`：只存在于 expected head gamedata。
- `missing`：candidate 要求但 expected head 缺失。
- `modified`：path 相同但 size 或 SHA-256 不同。

comparison 前必须调用现有 `guard_candidate()`，并确认：

- `session.gamever == VALIDATION_GAMEVER`。
- session candidate SHA-256 等于 actual symbol candidate。
- session analysis config SHA-256 等于 head analysis config。
- 当前 generator contract SHA-256 等于 session identity。

### Read-Only PR Command

为 `gamedata_candidate.py` 增加明确的 read-only command，例如：

```powershell
uv run gamedata_candidate.py verify-tracked `
  -session "$env:GAMEDATA_SESSION" `
  -gamever "$env:GAMEVER" `
  -candidate "$env:ACTUAL_CANDIDATE_SNAPSHOT" `
  -configyaml "$env:HEAD_CONFIG" `
  -repo-root "$env:WORKSPACE" `
  -revision HEAD
```

命令语义：

1. `guard_candidate(session)`。
2. 验证 game version、candidate 和 config identity。
3. 从 `revision` 读取 exact `gamedata/<GAMEVER>/` Git tree/blob bytes。
4. 使用与 candidate session 相同的 canonical path、size 和 SHA-256 inventory schema。
5. 运行 exact comparison，并输出 bounded path-level diagnostics。
6. mismatch 返回非零；不创建、修改或删除任何 repository file。

`-revision` 在 CI 中必须显式传入，不接受隐式 working-tree fallback。revision 必须解析为当前 checkout 的 exact
commit；branch name、remote ref 或不确定 symbolic fallback 不应在 command 内自行推断。

现有 `verify_published_gamedata()` 继续服务 release staging/promotion 的 filesystem destination verification，
但应复用同一个 pure inventory comparison helper，避免普通 PR 与 release 产生两套 equality 语义。

## Failure Reporting

日志应保持有界，并优先输出 canonical path：

```text
Tracked gamedata mismatch for 14170:
  Added in PR head:
    gamedata/14170/.../Unexpected.json

  Missing from PR head:
    gamedata/14170/.../Required.json

  Modified:
    gamedata/14170/.../GameData.json
      expected size/sha256: 1234 / abc...
      candidate size/sha256: 1240 / def...
```

不得输出整个大文件、candidate session 中的本地绝对路径、runner secrets 或完整环境变量。

## Concurrency And Release Interaction

普通开发 PR 与 generated-output PR 可能修改同一 `GAMEVER` 路径。设计规则：

- 两类 PR 都不得 force-push 已进入 review 的 generated-output branch。
- generated-output PR 的 bytes 必须来自其 manifest 绑定的 immutable `SOURCE_SHA`。
- 默认分支在 output build 后推进时，output PR 必须按照 release freshness contract 重新验证或重建。
- generated-output conflict 不得通过手工挑选 snapshot/gamedata files 解决；必须废弃旧 build 并从新的默认分支
  SHA 重新生成完整 transaction。
- 普通 PR 提交 tracked outputs 不授予其 release manifest、staged bin、tag 或 Release authority。

本计划不改变 release promotion state machine，但依赖 `new-release-workflow.md` 中的 exact-source freshness
不变量。实现时必须保证 workflow、promotion code 和 tests 对“exact source”或“ancestor source”采用同一个明确
契约；不得让两套语义长期并存。

## Required Changes

- Modify: `gamedata_candidate.py`
  - 提取共享 inventory comparison helper。
  - 增加 read-only `verify-tracked` command。
  - 从 exact Git revision 读取 versioned gamedata blob inventory。
  - 保持现有 `publish` 的 atomic destination semantics 不变。
- Modify: `.github/workflows/pr-self-runner.yml`
  - 在 isolated gamedata candidate guard 后增加 head tracked-gamedata comparison。
  - comparison 成功后再 mark `gamedata` validation step。
  - 保持 read-only permissions 和 no-publish contract。
- Modify: `tests/test_gamedata_candidate.py`
  - 覆盖 exact/add/missing/modified inventory、identity mismatch、Git tree mode/path safety 和 no-working-tree fallback。
- Modify: `tests/test_pr_self_runner_workflow.py`
  - 强制 analyzer -> symbol compare -> gamedata build/guard -> tracked compare -> C++ ordering。
  - 强制普通 PR 不调用 publish，不增加 write permissions。
- Modify: `tests/test_symbol_store_architecture.py`
  - 保留 `/create-pr` 对 prepare -> validation -> publish 的 ownership。
  - 固化 snapshot 与 gamedata 都由同一 validated post-change transaction 发布。
- Modify after implementation: `README.md` / `README_CN.md`
  - 记录普通 output-affecting PR 必须提交匹配 snapshot 与 gamedata。
  - 记录 CI 只读比较且不会自动修复遗漏。

## Test Plan

### Inventory Comparison Tests

- candidate 与 Git head inventory 完全相同时成功。
- added、missing、modified path 分别失败。
- path 相同但 raw-byte size 不同失败。
- path 和 size 相同但 SHA-256 不同失败。
- inventory ordering 不影响 comparison 结果。
- duplicate/case-colliding canonical path 被拒绝。
- expected root 缺失或 candidate root 缺失时 fail closed。

### Session Identity Tests

- wrong `GAMEVER` 失败。
- symbol candidate SHA-256 改变后失败。
- head config SHA-256 与 session 不一致时失败。
- generator contract 在 gamedata build 后改变时失败。
- gamedata candidate bytes 在 build 后改变时失败。

### Git Object Boundary Tests

- command 从 explicit revision 读取 blobs，不读取 mutable working-tree expected files。
- 修改 working-tree gamedata 不能改变 HEAD comparison 结果。
- revision 中的 symlink、submodule 和 non-blob entries 被拒绝。
- root escape、backslash、absolute path 和 invalid game version 被拒绝。
- blob bytes 按原始内容 hash，不受 checkout line-ending 设置影响。

### Workflow Contract Tests

- PR workflow 在 actual symbol compare 后构建 gamedata candidate。
- tracked gamedata comparison 发生在 gamedata guard 后、C++ tests 前。
- comparison 使用 `ACTUAL_CANDIDATE_SNAPSHOT`、`GAMEDATA_SESSION`、`HEAD_CONFIG` 和 explicit `HEAD` revision。
- comparison mismatch 阻止 `gamedata` mark 和 C++ validation。
- workflow 权限仍精确为 `contents: read`。
- workflow 中不存在 symbol/gamedata publish、git commit/push 或 PR mutation command。
- bump-download 与 generated-output PR 保持现有 event partition。

### End-To-End Tests

- 本地 prepare/validate/publish 后，普通 PR comparison 对 snapshot 和 gamedata 同时通过。
- 只回退一个 tracked gamedata 文件时 snapshot compare 仍通过，但 gamedata compare 必须失败。
- 只修改 gamedata generator 且忘记发布 output 时必须失败。
- output-neutral PR 在 tracked outputs 已一致时无需产生 generated diff。
- new-version bump PR 继续验证 base `VALIDATION_GAMEVER`，不要求 head 新版本 output。

## Rollout Plan

1. 实现 pure inventory comparison 与 Git revision inventory reader，并完成 unit/path-safety tests。
2. 增加 `verify-tracked` CLI，但暂不接入 required PR workflow。
3. 对当前 accepted `GAMEVER` 在 clean checkout 上运行 read-only comparison，确认 tracked gamedata baseline 是否一致。
4. 如 baseline 不一致，使用完整 prepare -> validation -> publish transaction 创建一次修复 PR；不得手工同步文件。
5. 将 comparison 接入 `pr-self-runner.yml`，补 workflow contract tests。
6. 更新 README/README_CN，并将新 check 设为 ordinary PR required gate。
7. 观察同版本 ordinary PR 与 generated-output PR 的冲突；确认 release exact-source freshness gate 与文档一致。

## Acceptance Criteria

- output-affecting 普通 PR 在实际 symbol bytes 变化时必须提交匹配 snapshot。
- output-affecting 普通 PR 在实际 gamedata bytes 变化时必须提交匹配 versioned gamedata。
- PR head snapshot 与 actual symbol candidate 不一致时 CI 失败。
- PR head gamedata inventory 与 guarded gamedata candidate 不一致时 CI 失败。
- gamedata comparison 绑定同一 game version、symbol candidate、analysis config 和 generator contract。
- expected gamedata 从 explicit PR head Git revision 读取，不依赖 mutable working tree。
- 普通 PR CI 保持 read-only，不 publish、stage、commit、push 或修改 PR。
- mismatch diagnostics 至少区分 added、missing 和 modified canonical paths。
- output-neutral PR 在 bytes 不变时不需要 generated-output diff。
- 新 game version bump 继续由 post-merge release build 负责。
- generated-output PR 继续独占 release manifest、staging、promotion、tag 和 Release authority。
- ordinary PR 与 generated-output PR 发生 source freshness 冲突时必须重建完整 output transaction，不手工拼接产物。

## Final Architecture

```text
Developer transaction
---------------------
analysis
  -> immutable symbol candidate
  -> guarded gamedata candidate
  -> C++ validation
  -> publish same transaction
       -> gamesymbols/<GAMEVER>.yaml
       -> gamedata/<GAMEVER>/
  -> commit code + expected outputs in one PR

Ordinary PR verification
------------------------
PR code + trusted base
  -> actual symbol candidate
       -> compare PR head snapshot Git blob
       -> build guarded gamedata candidate
            -> compare PR head gamedata Git blobs
       -> C++ validation
  -> complete without publish

Release transaction
-------------------
immutable SOURCE_SHA
  -> full candidate validation
  -> generated-output PR + manifest + staged bin
  -> merge/promotion gate
  -> tag and GitHub Release
```

最终语义：普通开发 PR 负责同时声明并证明当前 source 对应的 expected snapshot 与 expected gamedata；普通 PR
CI 只重建和比较，不写入。generated-output PR 则继续负责将特定 immutable `SOURCE_SHA` 的完整 release
transaction 接受并提升为正式发布状态。
