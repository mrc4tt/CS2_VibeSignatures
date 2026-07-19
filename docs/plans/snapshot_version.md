# Snapshot Config Digest Versioning and Baseline Fallback

## Status

Proposed two-phase improvement.

本计划修复 snapshot normalized config digest 的历史兼容问题，为摘要算法增加显式版本，
并将普通 PR CI 中“不可信的 baseline snapshot”从硬失败改为带告警的 clean bootstrap。

本计划只放宽普通 PR self-runner 对 **base snapshot** 的处理。PR HEAD snapshot、actual
candidate、release promotion、republish、显式 CLI restore 和其他 publication boundary 仍然
保持 strict failure，除非后续计划另行修改。

本文在以下范围 supersede 既有计划：

- `track-gamesymbols-snapshot.md` 中“任何 snapshot config digest mismatch 都使 PR workflow
  立即失败”的条款，改为仅 HEAD/actual mismatch 硬失败；base mismatch 允许 clean bootstrap。
- `config-yaml-migration.md` 中 historical fallback digest mismatch 的通用 hard-fail 描述，
  仅对普通 PR baseline replay 改为 warning + bootstrap；release 和 promotion 仍 fail closed。

## Incident

GitHub Actions run `29639862628` / job `88068471208` 在恢复 `14168b` baseline snapshot
时失败：

```text
snapshot config digest mismatch:
snapshot=sha256:c77057be2c4eaf34af820aeab35b151aceac39af516f87fffdf69886680d6dfc
actual=sha256:8e8dd1eac4f3a9c68300eec1cd50b65e951a3df562d9a53061117000c2ac55f0
```

base config 本身没有任何 `optional_input*` 字段。差异来自当前摘要归一化逻辑把新字段
无条件加入每个 normalized skill，并把缺失值写成空列表：

```diff
 {
   "name": "find-a",
   "expected_output": ["A.{platform}.yaml"],
+  "optional_input": [],
+  "optional_input_windows": [],
+  "optional_input_linux": []
 }
```

这不是 analysis contract 的语义变化，而是未版本化摘要算法的表示变化。历史 snapshot
使用旧算法记录 `c77057...`，HEAD 代码用新表示重算为 `8e8dd1...`，导致 baseline 在任何
Python unittest 或二进制分析执行前被拒绝。

## Problem

当前设计同时存在三个问题：

1. `config_sha256` 没有算法版本，reader 无法知道应使用哪套 normalized contract 规则。
2. 向 `SKILL_FIELDS` 增加一个默认空字段会改变所有历史 config digest，即使配置语义不变。
3. PR workflow 把 baseline snapshot 当成必须输入。baseline 不可信时直接失败，无法使用
   已存在的 clean bootstrap 路径完成更保守的全量验证。

严格比较本身仍然必要。snapshot 是与特定 analysis contract 绑定的缓存，不是任意 YAML
备份；在恢复和增量 invalidation 前必须证明 snapshot、config、game version 和正式 artifact
集合一致。需要改变的是：

- 用可版本化、可兼容的方式完成严格比较；
- baseline 无法取得信任时放弃增量缓存，而不是放弃整个 PR 验证；
- HEAD expected state 无法取得信任时继续硬失败，避免自证或无预期验证。

## Goals

- 立即恢复没有 `optional_input*` 的历史 config digest，修复当前 CI 阻塞。
- 明确定义 config digest v1 和 v2，禁止未来通过修改共享字段列表隐式改变旧算法。
- 保持历史 schema-1 snapshot 可读、可验证且 byte-stable。
- 新 snapshot 使用带显式 digest version 的 schema。
- 普通 PR CI 在 baseline snapshot 不可信时输出显著 warning，清空 symbol YAML 并全量重建。
- 保持 HEAD snapshot、actual candidate 和 publication boundary 的严格验证。
- 使用稳定错误分类或专用退出码驱动 CI，不解析人类可读 stderr 文本。
- 记录 CI 实际使用 trusted incremental 还是 bootstrap 模式，避免静默降级。

## Non-Goals

- 不取消 snapshot/config strict validation。
- 不允许不可信 baseline 内容进入 `bin/<GAMEVER>`。
- 不把 PR HEAD snapshot 恢复为 analysis 输入。
- 不将 warning fallback 扩展到 candidate comparison、release promotion 或 republish。
- 不因 digest version 迁移改变任何 `files` payload 或 per-symbol YAML schema。
- 不在本计划中改变 analyzer dependency scheduling、LLM policy 或 symbol 生成逻辑。
- 不把未知错误、文件系统错误或 workspace 安全错误降级为 warning。

## Terminology and Trust Boundaries

### Baseline Snapshot

从 `pull_request.base.sha` 选择的 accepted snapshot。它只用于加速 PR replay：

```text
trusted baseline
    -> restore
    -> targeted invalidation
    -> incremental rebuild
```

baseline 是可丢弃的优化输入。不能证明其可信时必须完全忽略其 payload。

### HEAD Snapshot

PR 声明的 expected snapshot。它是 analysis 后 actual candidate 的比较目标，不是缓存输入。
HEAD snapshot 缺失、schema 无效、digest 不匹配、非 canonical 或 payload 不一致都必须失败。

### Actual Candidate

由本次 CI analysis 从 workspace 实际构建的 immutable snapshot。gamedata 和 C++ validation
只能消费该 candidate。candidate schema、digest version 或 session identity 不一致必须失败。

### Clean Bootstrap

不恢复 baseline，不执行 base/head incremental invalidation，先安全删除
`bin/<VALIDATION_GAMEVER>/**/*.yaml`，再使用 HEAD config 运行完整 analyzer producer scheduling。

## Decisions

### 1. Immediate v1 Compatibility Patch

首先保留当前 snapshot schema 和 `config_sha256` 格式，只修复 v1 normalized representation。

旧字段继续按历史方式无条件写入 normalized skill；新增的三个 optional input 字段采用
语义归一化：

```python
V1_ADDITIVE_FIELDS = (
    "optional_input",
    "optional_input_windows",
    "optional_input_linux",
)

values = normalize_string_list(skill.get(field))
if field in V1_ADDITIVE_FIELDS and not values:
    continue
normalized[field] = values
```

规则为：

| Config 表示 | v1 normalized representation |
| --- | --- |
| 字段缺失 | 不写入该 key |
| `optional_input: []` | 不写入该 key |
| `optional_input: [A.yaml]` | 写入该 key 和非空值 |

缺失和空列表都表示“没有 optional input”，必须产生相同 digest。非空 optional input 会改变
analysis dependency contract，必须参与 digest。

该补丁必须精确恢复 incident 中的历史值：

```text
sha256:c77057be2c4eaf34af820aeab35b151aceac39af516f87fffdf69886680d6dfc
```

v1 compatibility 规则在本计划落地后冻结。未来增加任何 digest-relevant field 不得继续扩展
或改变 v1，必须新增 digest version。

### 2. Separate Snapshot Schema Version from Config Digest Version

snapshot document schema 和 config digest algorithm 是不同概念，必须分别表示：

- `schema_version`：控制 snapshot document 的字段和 canonical encoding。
- `config_digest_version`：控制 normalized analysis contract 和 hash domain。

历史 schema 继续定义为：

```yaml
schema_version: 1
game_version: "14168b"
config_sha256: "sha256:<v1-digest>"
file_count: 123
files: {}
```

schema 1 没有 `config_digest_version`，reader 必须解释为 digest v1。

新 writer 使用：

```yaml
schema_version: 2
config_digest_version: 2
game_version: "14168b"
config_sha256: "sha256:<v2-digest>"
file_count: 123
files: {}
```

schema 2 必须包含 `config_digest_version`。当前只接受值 `2`；未知值必须被明确报告，不能
回退到当前算法猜测。

### 3. Freeze Digest Algorithms

digest v1 保留历史 JSON encoding 和 SHA-256 输入，不增加 domain prefix，以保证历史值不变。
其字段集合由 legacy fields 加本计划定义的非空 `optional_input*` compatibility extension 组成。

digest v2 使用冻结的完整字段集合，包括：

- module stage index 和 module name；
- `path_windows`、`path_linux` 的 present/value；
- skill index 和 name；
- `platform`；
- `expected_output`、`expected_output_windows`、`expected_output_linux`；
- `optional_output`；
- `expected_input`、`expected_input_windows`、`expected_input_linux`；
- `optional_input`、`optional_input_windows`、`optional_input_linux`；
- `prerequisite`；
- `skip_if_exists`。

v2 将所有已知 list 字段归一化为 list，缺失和显式空列表都归一化为 `[]`。v2 hash 输入增加
固定 domain separator，避免不同算法偶然共享相同 digest：

```text
gamesymbol-config-contract:v2\n<canonical-json>
```

canonical JSON 继续使用 UTF-8、sorted keys、无无意义空白和稳定 list 顺序。未来改变字段集合、
缺省语义、排序、路径表示或 encoding 时必须新增 v3，不得修改 v2。

### 4. Version-Aware Read Flow

现有 restore 流程先用“当前算法”加载 config contract，再读取 snapshot。版本化后必须改为：

```text
read snapshot bytes
    -> parse schema_version
    -> resolve config_digest_version
    -> load config contract with that exact digest algorithm
    -> validate game version, digest, formal paths and canonical bytes
    -> only then mutate workspace
```

建议提供统一的 version-aware context loader，例如：

```python
load_snapshot_context(
    snapshot_path,
    config_path,
    game_version,
    bindir,
) -> (document, raw_bytes, contract)
```

`restore`、`verify`、PR invalidation、candidate comparison、release validation 不得各自重新实现
版本推断。

### 5. Historical and New Writer Behavior

- schema-1 snapshot 必须继续使用 digest v1 验证并保持 canonical bytes 不变。
- schema-2 snapshot 必须使用 digest v2 验证。
- 新的 `pack` 和 candidate build 默认写 schema 2 / digest v2。
- reader 同时支持 schema 1 / digest v1 和 schema 2 / digest v2。
- canonicalize schema-1 document 时不能自动升级为 schema 2。
- schema migration 必须是显式操作，不能由普通 restore 或 verify 隐式改写 tracked 文件。

### 6. Tracked Snapshot Migration

由于 actual candidate 与 PR HEAD snapshot 使用 canonical bytes 严格比较，新 writer 切换到
schema 2 时，所有仍作为 HEAD expected state 使用的 tracked `gamesymbols/*.yaml` 必须在同一
原子迁移中升级，否则 payload 相同也会因 metadata 不同而失败。

迁移只允许改变：

```text
schema_version
config_digest_version
config_sha256
```

`game_version`、`file_count` 和 `files` 必须逐值保持不变。迁移过程必须：

1. 用 schema 1 / digest v1 验证原 snapshot 和对应历史 config。
2. 保留解析后的 `files` mapping，不从 persisted runner YAML 获取 payload。
3. 用同一 config 计算 digest v2。
4. 写出 canonical schema-2 bytes。
5. 用 schema 2 / digest v2 重新验证。
6. 执行 snapshot-only round-trip，证明 payload 可恢复并重新打包。
7. 对迁移前后 `files` 做深度相等断言。

应提供可测试的 migration library/CLI，而不是手工修改 header。迁移全部 tracked snapshots
必须与 schema-2 writer、reader 和 candidate comparison 支持一起提交。

### 7. Candidate and Release Provenance

所有持久化或跨步骤携带 `config_sha256` 的结构都必须同时携带 digest version，避免 hash
脱离算法上下文：

- `SnapshotContract`；
- candidate info；
- candidate session manifest；
- `SnapshotSymbolStore` metadata；
- release manifest analysis config contract provenance。

candidate session 是临时 transaction metadata，可以直接 bump session schema 并拒绝旧 session。

release manifest 应在新 schema revision 中增加：

```json
{
  "analysis_config_contract_digest_version": 2,
  "analysis_config_contract_sha256": "sha256:..."
}
```

历史 release manifest 缺少该字段时，按其引用的 schema-1 snapshot 解释为 digest v1。promotion
和 republish 必须验证 manifest、snapshot 与 config 三者的 digest version 和 digest 一致；不得
在 release boundary 使用 warning fallback。

## Baseline Trust Probe

### Dedicated Non-Mutating Command

CI 不应通过解析 `restore` 的 stderr 判断是否允许降级。增加只读的 baseline contract probe，
例如：

```powershell
uv run gamesymbol_snapshot.py check-contract `
  -gamever "$env:GAMEVER" `
  -bindir bin `
  -configyaml "$env:BASE_CONFIG" `
  -snapshot "$env:BASE_SNAPSHOT"
```

该命令只读取 snapshot/config 并验证：

- snapshot schema 和 digest version；
- game version；
- normalized config digest；
- formal required/optional artifact 集合；
- path 安全；
- canonical bytes；
- snapshot-only restore/pack round-trip（如成本可接受，应保留）。

它不得删除或写入 `bin`。

### Exit Contract

定义稳定退出语义：

| Exit code | Meaning | PR baseline behavior |
| --- | --- | --- |
| `0` | baseline trusted | restore + incremental invalidation |
| `3` | baseline content untrusted | warning + clean bootstrap |
| `2` | invalid invocation/current config contract | hard fail |
| other | unexpected/operational failure | hard fail |

exit `3` 至少覆盖：

- snapshot schema 不支持或 malformed；
- config digest version 未知；
- game version mismatch；
- config digest mismatch；
- snapshot 非 canonical；
- required artifact 缺失；
- undeclared artifact 存在；
- snapshot payload 或 path contract 不安全；
- snapshot-only round-trip 不稳定。

以下情况不得返回 `3`：

- CLI 参数错误；
- HEAD/current analysis config 无效；
- workspace 路径越界；
- workspace 或 game root 是不允许的 reparse point；
- 删除、写入或权限错误；
- Python 未处理异常。

如果 extracted baseline config 本身可读取但当前 reader 无法将它解释为受支持的历史 contract，
probe 可以将 baseline 标记为 untrusted；但 base snapshot/config Git blob 无法定位或导出仍属于
workflow/provenance 错误，必须硬失败。

### Restore Remains Strict

probe trusted 后仍调用现有 strict `restore -replace`。restore 必须重复全部 snapshot contract
验证，以防 probe 与 restore 之间发生变化。此时任何 restore 失败都视为 operational failure，
不得再降级，因为 trusted preflight 已通过，失败可能发生在 workspace mutation 阶段。

## PR CI Fallback Flow

`.github/workflows/pr-self-runner.yml` 的目标流程：

```text
select base snapshot/config
        |
        +-- no snapshot --------------------------+
        |                                         |
        +-- check-contract exit 3 ----------------+--> warning
        |                                         |    clear all YAML
        |                                         |    full analysis
        |                                         |
        +-- check-contract exit 0 --> restore --> invalidate --> analysis
        |
        +-- other exit ---------------------------> hard fail

analysis
    -> build actual candidate
    -> strict compare with HEAD snapshot
    -> gamedata
    -> C++ validation
```

### Shared Bootstrap Cleanup

现有 no-baseline 分支的 YAML 清理逻辑必须提取为同一步内的共享 PowerShell function 或受测试的
helper，供以下两种情况共同调用：

- base commit 没有 snapshot；
- snapshot 存在但 probe 判定 untrusted。

清理前继续执行：

- game root 必须位于当前 PR workspace；
- game root 和相关父级不能是不允许的 reparse point；
- 只删除 `bin/<VALIDATION_GAMEVER>/**/*.yaml`；
- 不删除 DLL、SO、IDB、I64 或其他 depot 文件；
- 不操作 persisted workspace 原目录，只操作 PR workspace copy。

清理完成后不得运行 `gamesymbol_pr_validation.py invalidate`，因为没有可信 base contract/payload。
`ida_analyze_bin.py` 必须在空 YAML 状态下按 HEAD config 执行正常 producer scheduling。

### Observable Degradation

fallback 不能静默发生。workflow 必须输出 GitHub warning annotation：

```text
::warning title=Baseline snapshot rejected::
reason=config_digest_mismatch; incremental validation disabled; falling back to clean full rebuild
```

同时向 `$GITHUB_STEP_SUMMARY` 写入：

```text
Baseline mode: bootstrap-untrusted
Validation game version: 14168b
Reason: config_digest_mismatch
Incremental invalidation: disabled
```

建议导出：

```text
BASELINE_MODE=trusted-incremental | absent-bootstrap | untrusted-bootstrap
HAS_BASE_SNAPSHOT=false  # fallback 后更新
```

reason 使用稳定 machine-readable code，例如：

- `unsupported_snapshot_schema`
- `unsupported_config_digest_version`
- `config_digest_mismatch`
- `noncanonical_snapshot`
- `snapshot_contract_mismatch`
- `snapshot_round_trip_mismatch`

warning 文本可变化，但 reason code 需要测试并保持稳定。

## Failure Matrix

| Situation | Required behavior |
| --- | --- |
| Base commit 没有 tracked snapshot | Clean bootstrap；普通信息日志 |
| Base snapshot digest mismatch | Warning；clean bootstrap |
| Base snapshot schema/digest version 不支持 | Warning；clean bootstrap |
| Base snapshot non-canonical 或 formal paths 不匹配 | Warning；clean bootstrap |
| Base snapshot Git blob 选择歧义 | Hard fail |
| Base snapshot/config Git blob 无法导出 | Hard fail |
| Baseline probe 未处理异常 | Hard fail |
| Trusted restore 的文件系统操作失败 | Hard fail |
| Workspace/reparse/path safety check 失败 | Hard fail |
| HEAD config 缺失或无效 | Hard fail |
| HEAD snapshot 缺失、schema 无效或 digest mismatch | Hard fail |
| Actual candidate 与 HEAD snapshot 不同 | Hard fail |
| Candidate session/version identity mismatch | Hard fail |
| Release manifest/snapshot/config provenance mismatch | Hard fail |

## Implementation Areas

### Snapshot Digest and Schema

- `gamesymbol_snapshot_lib/config.py`
  - 拆分冻结的 v1/v2 field sets 和 normalization functions。
  - `load_contract` 显式接收 `config_digest_version`。
  - 禁止通过共享 `SKILL_FIELDS` 隐式改变旧版本 digest。
- `gamesymbol_snapshot_lib/model.py`
  - `SnapshotContract` 增加 `config_digest_version`。
- `gamesymbol_snapshot_lib/codec.py`
  - 同时解析/编码 schema 1 和 schema 2。
  - schema 1 隐含 digest v1；schema 2 要求显式 digest version。
  - canonical writer 保留文档原 schema，不隐式升级。
- `gamesymbol_snapshot_lib/operations.py`
  - 先解析 snapshot version，再加载对应 contract。
  - 增加 version-aware context loader 和只读 contract probe。
  - restore/verify 保持 strict mutation boundary 和 round-trip。
- `gamesymbol_snapshot_lib/snapshot_cli.py`
  - 增加 `check-contract` 和稳定 untrusted exit code/reason code。
  - 可增加显式 `migrate` 子命令处理 tracked schema migration。

### Candidate and Symbol Store

- `gamesymbol_snapshot_lib/candidate.py`
  - candidate info 和 equality guard 增加 schema/digest version。
- `gamesymbol_snapshot_lib/candidate_session.py`
  - bump ephemeral session schema；manifest 记录 digest version。
- Snapshot Symbol Store loader
  - 暴露 schema/digest version，并验证 metadata 完整性。
- candidate compare
  - strict 比较 schema、digest version、digest、file count 和 canonical bytes。

### PR Workflow

- `.github/workflows/pr-self-runner.yml`
  - baseline restore 前执行 `check-contract`。
  - exit `3` 时 warning + shared clean bootstrap。
  - trusted baseline 才执行 restore 和 incremental invalidation。
  - fallback 后继续 Python tests、analysis、candidate、gamedata 和 C++ validation。
  - HEAD snapshot comparison 保持 strict。
- `tests/test_pr_self_runner_workflow.py`
  - 固化 trust probe、warning、bootstrap 和 hard-failure ordering。

### Release Provenance

- `release_workflow_lib/manifests.py`
  - 新 manifest schema 增加 contract digest version。
- `release_workflow_lib/staging.py`
  - 从 validated candidate 复制 digest version 和 digest。
- `release_workflow_lib/validation.py`
  - historical manifest 默认 v1；新 manifest 严格核对 version + digest。
- `release_workflow_lib/promotion.py` 和相关 workflows
  - publication boundary 不允许 baseline warning fallback。

### Documentation

实施完成后更新当前使用文档，说明：

- schema-1/v1 和 schema-2/v2 的读取规则；
- 新 `check-contract` / `migrate` 命令；
- PR baseline warning fallback；
- HEAD/release strict failure boundary。

历史计划不需要全文重写，但应在容易冲突的 failure behavior 处增加 superseded 指向。

## Test Plan

### Digest Compatibility Tests

- 一个固定 minimal legacy config 的 v1 digest 使用 hard-coded expected value。
- incident base config 在无 `optional_input*` 时仍得到 `c77057...`。
- 缺失 `optional_input` 与 `optional_input: []` 的 v1 digest 相同。
- 非空 `optional_input` 改变 v1 digest。
- description、注释和 YAML 纯格式变化仍不改变 digest。
- v2 缺失和显式空 list 归一化为相同 digest。
- v2 的 optional input 非空、平台字段或其他 contract field 变化会改变 digest。
- v1 和 v2 field sets、domain separator 和 serializer 被常量/fixture tests 冻结。
- 未知 digest version 被拒绝，不回退到 current version。

### Schema and Codec Tests

- schema 1 无 version field 时解释为 digest v1。
- schema-1 canonical bytes 经过 parse/emit 保持完全一致。
- schema 2 缺少 `config_digest_version` 失败。
- schema 2 digest version 非整数、未知或不支持时失败。
- schema 1 多出 schema-2-only key 失败。
- schema 2 top-level key 集合和 canonical order 稳定。
- schema-1/v1 和 schema-2/v2 均通过 restore/pack round-trip。
- writer 默认输出 schema 2 / digest v2。

### Migration Tests

- migration 前先验证 schema-1/v1 source。
- migration 只改变 metadata，`files` 深度相等。
- migration 输出 canonical schema-2/v2 document。
- migration 重复执行要么 no-op，要么明确拒绝 already-current input。
- invalid source snapshot 不产生部分输出。
- 写入使用原子 replace。

### Trust Probe Tests

- trusted schema-1 baseline 返回 `0`。
- trusted schema-2 baseline 返回 `0`。
- digest mismatch 返回 untrusted exit `3` 和稳定 reason。
- unsupported schema/digest version 返回 `3`。
- non-canonical snapshot 返回 `3`。
- required/undeclared artifact mismatch 返回 `3`。
- malformed snapshot path 返回 `3`，且不写入 workspace。
- 缺少 CLI 参数、无效 current config 和内部异常不返回 `3`。
- probe 全程不删除或写入任何 YAML。

### Restore and Candidate Tests

- probe trusted 后 restore 仍重复验证。
- restore mutation/permission failure 为 hard failure。
- schema-1 baseline 可以恢复并参与 PR invalidation。
- schema-2 candidate session 记录并 guard digest version。
- candidate/head schema 或 digest version 不同严格失败。
- payload 相同但 HEAD metadata 不可信仍失败。

### Workflow Contract Tests

- `check-contract` 位于 restore 之前。
- 只有 probe exit `0` 才 restore 和 invalidate。
- probe exit `3` 输出 GitHub warning、更新 summary、清空 YAML 并继续 analysis。
- fallback 不执行 `gamesymbol_pr_validation.py invalidate`。
- no snapshot 和 untrusted snapshot 使用同一个 cleanup path。
- cleanup 保留 binaries/IDA databases，只删除 workspace game-root YAML。
- probe unexpected failure、restore failure 和 safety guard failure都会终止 workflow。
- fallback 后仍执行 unit tests、analysis、candidate compare、gamedata 和 C++ tests。
- HEAD snapshot mismatch 始终终止 workflow。

### Release Tests

- 新 manifest 记录 digest version 和 digest。
- legacy manifest/snapshot 按 v1 验证。
- manifest、snapshot 和 config 任一 version/digest 不一致时 promotion 失败。
- release validation 不使用 PR baseline warning fallback。

## Implementation Sequence

### Phase A: Immediate Compatibility and CI Resilience

Phase A 是当前失败的快速 patch，可以独立合并：

1. 添加 incident digest 和 empty/missing optional input 的失败回归测试。
2. 实现 v1 additive-field conditional normalization，恢复历史 digest。
3. 添加非 mutating `check-contract`、untrusted exit/reason contract 和 tests。
4. 提取 PR workflow shared bootstrap cleanup。
5. 实现 baseline warning + clean full rebuild fallback。
6. 保持 restore、HEAD candidate comparison 和 release boundary strict。
7. 运行完整 Python 和 workflow-contract regression，并重新运行失败的 PR job。

Phase A 不改变 snapshot schema，不批量重写 tracked snapshot。

### Phase B: Versioned Schema and Provenance

Phase B 的 mergeable result 必须原子完成：

1. 冻结 digest v1，实现 domain-separated digest v2。
2. 增加 schema-1/schema-2 codec 和 version-aware context loader。
3. 迁移 restore、verify、PR invalidation 和 candidate paths。
4. bump candidate session metadata，并更新 Symbol Store consumers。
5. 增加 release manifest digest-version provenance 和历史读取兼容。
6. 实现并测试显式 tracked snapshot migration。
7. 将全部当前 tracked HEAD snapshots 原子迁移到 schema 2 / digest v2。
8. 更新 workflow、docs 和 contract tests。
9. 运行完整 repository validation 和 self-runner PR validation。

不能先切换 new writer 再在后续提交迁移 HEAD snapshots，否则中间状态下所有 candidate/head
canonical comparison 都会失败。

## Validation Gates

定向验证至少包括：

```powershell
uv run python -m unittest tests.test_gamesymbol_snapshot_config -b
uv run python -m unittest tests.test_gamesymbol_snapshot_ops -b
uv run python -m unittest tests.test_gamesymbol_pr_validation -b
uv run python -m unittest tests.test_pr_self_runner_workflow -b
uv run python -m unittest tests.test_release_workflow -b
```

完整完成门禁：

```powershell
uv run ruff format <changed-python-files>
uv run ruff check <changed-python-files>
uv run python format_repo_files.py --check
uv run python -m unittest discover -s tests -b
git diff --check
```

还必须通过 self-hosted PR workflow，至少观察两条集成路径：

1. trusted baseline：restore + targeted invalidation + analysis 成功。
2. 人工 fixture 或测试分支制造的 untrusted baseline：产生 warning，clean bootstrap 后继续完成
   candidate、gamedata 和 C++ validation。

如果 full bootstrap 因运行成本无法在本地执行，不能声称集成验收通过；必须以实际 Actions job
结果作为证据。

## Risks and Mitigations

### Silent Loss of Incremental Coverage

风险：baseline 经常失效，但 CI 始终全量重建并通过，使问题长期无人处理。

缓解：强制 warning annotation、稳定 reason code、step summary 和 `BASELINE_MODE`；禁止静默 fallback。

### Excessive Full-Rebuild Cost

风险：clean bootstrap 增加 IDA/LLM 时间和费用。

缓解：只对明确的 baseline trust failure fallback；优先完成 digest compatibility；保留 trusted
incremental 快路径。

### Error Misclassification

风险：文件系统、代码 bug 或 workspace 安全错误被误分类为 untrusted baseline。

缓解：dedicated probe、typed exceptions/exit code、restore 二次 strict validation；不得使用 stderr
substring matching 或“任意非零都 bootstrap”。

### Schema Migration Churn

风险：tracked snapshot 很大，批量迁移可能产生难审查 diff。

缓解：migration test 断言 `files` 完全相等；review 中只允许 metadata 行变化；使用 canonical writer
和原子写入。

### Historical Reader Compatibility

风险：旧工具无法读取 schema-2 snapshot。

缓解：schema-2 migration 与所有 production readers 同一原子变更；历史 schema-1 reader support
长期保留；不依赖旧 commit 的工具读取新 snapshot。

## Acceptance Criteria

Phase A 完成条件：

- incident base config 重算得到历史 digest `c77057...`。
- 新 optional input 非空时仍改变 digest。
- baseline digest/schema/contract mismatch 在 PR CI 中产生 warning 并进入 clean bootstrap。
- fallback 前没有 baseline payload 写入 workspace。
- fallback 清空全部 symbol YAML 后运行完整 analyzer。
- HEAD snapshot 和 actual candidate comparison 仍严格失败。
- 不可信 baseline 以外的异常不会被吞掉。
- 完整 Python tests、format check、Ruff 和 `git diff --check` 通过。
- 原失败 Actions job 的等价链路实际通过。

Phase B 完成条件：

- digest v1/v2 算法和 field sets 被显式冻结并有 hard-coded regression fixtures。
- schema-1 snapshot 缺少 version field 时按 v1 读取且 canonical bytes 不变。
- 新 writer 默认输出 schema 2 / digest v2。
- restore/verify/invalidation 能同时处理可信 v1 baseline 和 v2 snapshot。
- 全部 tracked HEAD snapshots 已迁移为 schema 2，且 `files` payload 完全不变。
- candidate session、Symbol Store 和 release manifest 都携带 digest version。
- release promotion/republish 对 version 和 digest mismatch 保持 hard failure。
- unknown baseline digest version 在 PR CI 中 warning + bootstrap；unknown HEAD version 硬失败。
- trusted incremental 和 untrusted bootstrap 两条 self-runner 集成路径均有实际通过证据。

## Final Architecture

```text
Historical accepted snapshot
  schema 1 / implicit digest v1
            |
            +--> version-aware reader --> strict trust probe
                                         |
                                         +-- trusted --> restore + invalidate
                                         |
                                         +-- untrusted --> warning + clean bootstrap

New expected snapshot
  schema 2 / explicit digest v2
            |
            +--> analysis builds actual schema-2 candidate
                                         |
                                         +--> strict canonical HEAD comparison
                                         +--> gamedata
                                         +--> C++ validation
                                         +--> release provenance(version + digest)
```

最终原则是：baseline cache 可以被安全丢弃，expected state 和 publication provenance 不能被降级。
