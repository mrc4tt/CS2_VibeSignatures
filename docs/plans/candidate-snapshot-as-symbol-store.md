# Candidate Snapshot as Symbol Store

## Status

本文记录在 `docs/plans/track-gamesymbols-snapshot.md` 完整实施并通过其验收标准之后，
将 candidate snapshot 提升为 downstream Symbol Store 的后续设计与实施计划。

### Implementation Progress (2026-07-15)

本计划已完成：

- 新增 `gamesymbol_store.py`，提供 typed errors、`SymbolStore` protocol、immutable
  `SnapshotSymbolStore` 与 migration/test-only `DirectorySymbolStore`。
- 新增 `gamesymbol_candidate.py` 与 candidate library API，完成 strict build、semantic compare、hash/file-identity
  guard、session state、validation step gate 和 byte-preserving atomic publish。
- `update_gamedata.py` 与 C++ reference loaders 已切换为 snapshot-only production source；CLI 强制显式
  `-snapshot`，不存在 directory/bin fallback。
- PR workflow 已切换为 base restore -> analysis -> actual candidate -> head expected compare -> candidate-only
  downstream，并移除普通 PR persisted YAML writeback。
- build workflow 已切换为 analysis -> candidate -> gamedata -> C++ -> same-byte publish -> persisted cache。
- README、README_CN、前置计划的 superseded architecture/timing，以及 store/candidate/consumer/workflow tests 已更新。
- 现行 post-change/fix-cppheaders skill、LLVM runner issue 指南与 Serena memories 已同步 mandatory snapshot CLI。

验收验证：

- 完整 Python regression：811 tests passed。
- `14168` end-to-end independence replay：从 tracked snapshot 恢复临时 workspace，构建 candidate 后删除全部
  临时 `bin/14168/**/*.yaml`，gamedata 仍生成 32 个 byte-identical dist 文件。
- 同一 candidate 完成 11 个 C++ compile tests、12 个 layout compares，差异为 0。
- candidate、expected 与 published bytes 的 SHA-256 均为
  `a345d028673f0beb6e56038bfb382a95570b5c240a8cca30b0dad17624d630c2`。

执行顺序是硬约束：

```text
track-gamesymbols-snapshot.md
        |
        v
全部实现并通过 acceptance criteria
        |
        v
candidate-snapshot-as-symbol-store.md
```

本计划不替代前置计划中的 snapshot schema、formal file set、canonical writer、
`restore`、invalidation 和 PR trust-boundary 设计，而是在其稳定基础上改变 analysis 之后的
数据流和 publication timing。

核心结论：

- `bin/<GAMEVER>/**/*.yaml` 保留为 analyzer 的 mutable workspace、增量输出区和跨版本 reuse 表示。
- 每次完整 analysis transaction 成功结束后，必须立即执行一次 strict pack，生成 immutable candidate snapshot。
- `update_gamedata.py` 和 `run_cpp_tests.py` 只允许从 candidate snapshot 对应的 `SnapshotSymbolStore` 读取 symbol 数据。
- downstream consumer 不得读取或 fallback 到 `bin/<GAMEVER>/**/*.yaml`。
- candidate validation 全部成功后，发布流程复制 candidate 的原始字节到
  `gamesymbols/<GAMEVER>.yaml`；不得重新 parse、dump 或再次 pack。
- 普通 PR 不发布 snapshot，只比较实际 candidate 与 PR head snapshot；PR head snapshot 不能成为 downstream 输入。
- candidate validation 失败时，tracked snapshot 必须保持 byte-for-byte 不变。

## Relationship To The Prerequisite Plan

前置计划完成后，初始数据流为：

```text
ida_analyze_bin.py
        |
        v
bin/<GAMEVER>/**/*.yaml
        |\
        | +--> update_gamedata.py
        | +--> run_cpp_tests.py
        |
        v
gamesymbols/<GAMEVER>.yaml
```

本计划完成后，数据流改为：

```text
ida_analyze_bin.py
        |
        v
bin/<GAMEVER>/**/*.yaml
        |
        v
strict pack exactly once
        |
        v
candidate snapshot
        |\
        | +--> update_gamedata.py
        | +--> run_cpp_tests.py
        |
        v
publish the same candidate bytes
        |
        v
gamesymbols/<GAMEVER>.yaml
```

因此，本计划执行时需要明确 supersede 前置计划中的以下阶段性约束：

- “不把 snapshot 直接作为 `update_gamedata.py` 或 `run_cpp_tests.py` 的输入”。
- “先运行 downstream validation，再 pack canonical snapshot”。
- final architecture 中 `bin` 同时直接分流到 snapshot 和 downstream consumers 的结构。

这些条款在前置计划实施阶段仍然有效。只有当前计划进入实施并完成迁移后，才更新前置计划、README 和 workflow 文档中的最终架构描述。

## Background

前置计划解决的是 repository truth 和 reproducibility 问题：

- tracked snapshot 成为 Git 中可 review、可 restore、可 verify 的 analysis lockfile。
- ignored `bin` 不再是依赖某台机器的唯一事实状态。
- PR CI 能从 base snapshot 构造确定性分析起点。

但是，只要 downstream consumer 仍直接读取 `bin`，analysis 之后仍存在两个物理读取边界：

```text
actual bin YAML
    -> downstream output

actual bin YAML
    -> packed snapshot
```

即使两条分支由同一批文件产生，也仍需要额外证明：

- downstream 实际消费的数据与最终提交的 snapshot 完全一致。
- pack 后没有脚本继续修改 `bin`，导致 snapshot 和 downstream 输入发生时间差。
- downstream 没有读取 formal snapshot 未包含的 legacy、stale 或 undeclared YAML。
- PR validation 没有错误地使用 head snapshot 自证。

将 strict pack 移到 analysis 与 downstream validation 之间，可以把 pack 定义为 analysis transaction 的 commit boundary：

```text
mutable analysis state
        |
        v
immutable candidate
        |
        v
all read-only symbol consumers
```

这样，gamedata、C++ validation 和最终 published snapshot 都可以绑定到同一个 candidate SHA-256。

## Terminology

### Base Snapshot

从 base revision 或最近一个可信 tracked game version 取得的 snapshot。

用途：

- restore deterministic analysis baseline。
- 为未 invalidated outputs 提供已验证的 reuse 起点。

base snapshot 不是本次 analysis 的结果，也不能作为本次 downstream validation 的输入。

### Head Snapshot

普通 PR 中由提交者放入 head revision 的 `gamesymbols/<GAMEVER>.yaml`。

用途：

- 表达 PR 声明的 expected result。
- 与当前 PR 代码实际产生的 candidate 比较。

head snapshot 是只读 expected artifact，不是实际结果，不能传给 `update_gamedata.py` 或 C++ tests。

### Actual Bin Workspace

```text
bin/<GAMEVER>/**/*.yaml
```

它是本次 analyzer 可以修改的 workspace representation，包含：

- 从 base snapshot restore 的未 invalidated outputs。
- 当前 analyzer 新生成或重新生成的 outputs。
- analyzer 运行所需的二进制、IDB 和其他本地缓存。

candidate 生成后，actual bin 不再是本轮 downstream data source。

### Candidate Snapshot

analysis transaction 成功后，从 actual bin 通过 strict canonical pack 生成的 snapshot。

candidate 必须：

- 使用与 published snapshot 完全相同的 schema 和 canonical encoding。
- 包含 head analysis config 对应的完整 formal file set。
- 不包含 candidate-only metadata、时间戳、临时路径或 validation 状态。
- 在 candidate-ready 之后保持 byte-immutable。
- 能在 validation 成功后不经过重新序列化直接发布。

### Published Snapshot

```text
gamesymbols/<GAMEVER>.yaml
```

它是 validation 成功后发布的 candidate 原始字节。

必须满足：

```text
sha256(candidate) == sha256(published snapshot)
```

### Symbol Store

Symbol Store 是 downstream consumer 使用的只读逻辑接口。

最终 production backend 只有：

```text
SnapshotSymbolStore(candidate snapshot)
```

迁移期间可以保留 `DirectorySymbolStore` 作为 parity test backend，但 production workflow 不得通过它读取 `bin`。

### Candidate Session

一次从 analysis 完成到 candidate validation 或失败结束的本地 orchestration session。

session 包含：

- candidate file。
- candidate SHA-256。
- game version 和 config digest。
- validation state。
- 仅用于 orchestration 的 untracked session manifest。

session manifest 不是 repository truth，也不能写入 published snapshot。

## Goals

- 将 strict pack 定义为 analysis transaction 的唯一 commit boundary。
- 保证 `update_gamedata.py` 和 C++ tests 消费的正是最终可能发布的 snapshot bytes。
- downstream validation 完成前不修改 tracked snapshot。
- validation 成功后不再执行第二次 pack。
- 将 snapshot path/query/validation 逻辑集中在共享 Symbol Store 中。
- 消除 downstream 对 `bin` 文件存在性、目录 glob 和 persisted YAML 的依赖。
- 保持前置计划的 config digest、formal set、round-trip 和 canonical byte-stability 约束。
- 保持 PR base/head/actual candidate 三者的 trust boundary。
- 允许 candidate validation 失败后安全重试，不留下半发布状态。
- 让日志能够用 candidate SHA-256 关联 analysis、gamedata、C++ tests 和 publication。

## Non-Goals

- 不让 analyzer 直接写入聚合 snapshot。
- 不在每个 skill、module 或 platform 完成后 pack。
- 不删除 analyzer 对 per-symbol YAML 的增量读写能力。
- 不让 `bin` 成为 tracked repository state。
- 不改变单个 symbol payload 的既有字段语义。
- 不让 PR head snapshot 作为本次实际分析或 downstream 输入。
- 不允许 validation 失败后自动覆盖 tracked snapshot。
- 不在 candidate snapshot 中写入 validation 状态、命令日志、runner 信息或生成时间。
- 不用 session manifest 替代 snapshot canonical validation。
- 不在第一阶段同时重构所有 analyzer filesystem APIs；本计划只切断 downstream consumers 对 `bin` 的读取。
- 不承诺任意第三方脚本都能直接使用 Symbol Store；首批范围限定为 repository-owned gamedata 和 C++ validation。

## Authority Model

不同阶段的权威状态不同，但任一阶段只有一个被允许的 downstream source：

| Stage | Mutable state | Authoritative read source | Published state |
| --- | --- | --- | --- |
| restore/invalidation | `bin` | base snapshot 仅用于 restore | existing tracked snapshot |
| analysis running | `bin` | 不允许运行 downstream | existing tracked snapshot |
| candidate ready | `bin` 可保留但冻结语义 | candidate snapshot | existing tracked snapshot |
| downstream validation | `dist/**`、test temp output | candidate snapshot | existing tracked snapshot |
| validation success | candidate immutable | candidate snapshot | 尚未更新 |
| publication complete | local caches | published snapshot | candidate 原始字节 |
| validation failure | diagnostics only | candidate 可用于复现 | tracked snapshot 不变 |

核心规则：

```text
Before candidate:
  bin is mutable analysis workspace.

After candidate:
  candidate is the only symbol read source.

After publication:
  published snapshot is the durable canonical source.
```

## Analysis Transaction Boundary

“每次 analysis 结束后自动 pack”中的 analysis 必须定义为 top-level transaction，而不是任意低层操作。

### Valid Transaction Boundary

以下步骤共同构成一次 analysis transaction：

1. 从可信 base snapshot restore workspace YAML，或为新版本准备空 formal state。
2. 根据 snapshot/config/source delta 计算 invalidation closure。
3. 删除所有 invalidated producer outputs 和已删除 contract paths。
4. 运行目标 game version 的 top-level analyzer orchestration。
5. analyzer 返回成功，且没有仍在运行的 symbol producer。
6. 对 head config 执行 strict pack candidate。

第 6 步必须是第 5 步成功后的直接后继步骤。production workflow 不允许在两者之间运行 gamedata、C++ tests 或其他 YAML consumer。

### Invalid Boundaries

不得在以下时机生成 candidate：

- 单个 finder 完成后。
- 单个 module 完成后，但其他 module 尚未结束。
- Windows 完成而 Linux 尚未完成时。
- analyzer 失败或取消后。
- invalidation closure 尚未完成时。
- required output 仍缺失时。
- workspace 仍有 producer 可能写 YAML 时。

### Partial Analysis

允许 analyzer 只重跑 invalidated producer 子集，但 candidate 仍必须代表完整 game version formal set。

因此 partial rebuild 合法的前提是：

- workspace 先从可信 base snapshot restore。
- 未重跑 outputs 来自 base snapshot。
- invalidation dependency closure 已完整计算。
- strict pack 能验证所有 required outputs 和 undeclared YAML。

对没有完整 baseline 的新 game version，partial analysis 不能产生 candidate；strict pack 必须失败，直到完整 formal set 存在。

## Candidate Lifecycle State Machine

推荐状态机：

```text
CREATED
   |
   v
ANALYZING
   | success
   v
PACKING
   | strict pack + reopen validation success
   v
CANDIDATE_READY
   |
   +--> EXPECTED_MATCHED       (PR only)
   |
   v
GAMEDATA_PASSED
   |
   v
CPP_PASSED
   |
   v
VALIDATED
   |
   +--> PUBLISHED              (developer/build publication)
   |
   +--> COMPLETE_NO_PUBLISH    (ordinary PR)

Any failure/cancellation
   -> FAILED
```

状态规则：

- 只有 `PACKING` 可以创建或替换 candidate file。
- `CANDIDATE_READY` 后记录 candidate SHA-256。
- 后续每个 stage 开始和结束时都重新检查 candidate SHA-256。
- candidate hash 改变时 session 立即进入 `FAILED`。
- `VALIDATED` 必须同时表示 gamedata 和 C++ validation 成功。
- PR expected mismatch 可以在 downstream 前 fail fast，避免浪费执行时间。
- `PUBLISHED` 只能从 `VALIDATED` 进入。
- analyzer 需要重跑时必须废弃当前 session，不能回到 `ANALYZING` 并复用旧 candidate。

## Candidate File Contract

### Schema

candidate 复用前置计划定义的 published snapshot schema：

```yaml
schema_version: 1
game_version: "14168"
config_sha256: "sha256:<normalized-analysis-contract-digest>"
file_count: 2910
files:
  server/Foo.windows.yaml:
    func_name: Foo
    func_sig: 48 89 5C 24 ?? ...
```

不增加以下字段：

- `candidate: true`
- `validation_status`
- `candidate_path`
- `created_at`
- `runner`
- `source_commit`

否则 candidate bytes 将无法直接成为 published bytes。

### Candidate Identity

candidate 生成后计算：

```text
candidate_sha256 = sha256(raw canonical file bytes)
```

该 hash 用于：

- downstream source logging。
- session state transition guard。
- PR actual/expected comparison reporting。
- publication 前后 byte identity 验证。

candidate SHA-256 不写入 candidate 自身，避免自引用。

### Staging Location

candidate 默认不能直接写入 tracked `gamesymbols/`。

推荐位置：

- GitHub Actions / self-hosted runner：`$RUNNER_TEMP/gamesymbol-candidates/<session>/<GAMEVER>.yaml`。
- 本地 orchestration：操作系统 temporary directory 下的 session-specific 路径。
- debug：允许用户显式指定 repo 外或已忽略的 staging root，并使用 `-keep-candidate` 保留。

production candidate builder 必须：

- 要求显式 staging root，或创建安全的 session temp directory。
- 拒绝 candidate output 与 published snapshot path 相同。
- 拒绝 candidate output 位于 `gamesymbols/` tracked namespace。
- 拒绝输出目标是 symlink、junction 或 reparse point。
- 在同一 staging directory 内 temp-write + validate + atomic replace。

### Immutability

candidate-ready 后：

- consumer 以只读方式打开 candidate。
- consumer 不得接受 candidate output path。
- candidate session 保存初始 SHA-256。
- publication 前再次计算 SHA-256。
- candidate 被修改、截断、替换或重新 canonicalize 时必须失败。

操作系统 read-only attribute 可以作为额外保护，但不能替代 hash verification。

## Strict Candidate Pack Contract

candidate pack 必须复用前置计划的 formal set collector 和 canonical writer，不得创建第二套 serializer。

执行顺序：

1. 加载 head `config.yaml`。
2. 计算 normalized analysis contract digest。
3. 构造 required/optional formal output set 和 owner graph。
4. 验证所有 required YAML 存在、可读且顶层为 mapping。
5. 收集存在的 optional YAML。
6. 拒绝 undeclared YAML、path escape、case collision 和 duplicate canonical key。
7. 在内存中构造 snapshot data model。
8. 使用唯一 canonical encoder 产生 bytes。
9. 写入 candidate temporary file。
10. 重新打开 candidate 并执行 schema、metadata、config digest、canonical bytes 和 round-trip 验证。
11. 原子替换 candidate session target。
12. 计算 candidate SHA-256 并将 session 状态更新为 `CANDIDATE_READY`。

任一步失败时：

- 不产生可消费 candidate。
- 不运行 downstream validation。
- 不修改 tracked snapshot。
- session 标记为 `FAILED`。
- 保留 path-level mismatch/validation diagnostics。

## Symbol Store Design

### Shared Interface

建议新增：

```text
gamesymbol_store.py
```

核心只读接口：

```python
class SymbolStore(Protocol):
    @property
    def game_version(self) -> str: ...

    @property
    def config_sha256(self) -> str: ...

    @property
    def candidate_sha256(self) -> str: ...

    def contains(self, module: str, filename: str) -> bool: ...

    def get(self, module: str, filename: str) -> Mapping[str, Any] | None: ...

    def require(self, module: str, filename: str) -> Mapping[str, Any]: ...

    def glob_module(self, module: str, filename_pattern: str) -> Sequence[SymbolEntry]: ...

    def iter_module(self, module: str) -> Sequence[SymbolEntry]: ...
```

`SymbolEntry` 至少包含：

```python
@dataclass(frozen=True)
class SymbolEntry:
    path: str
    module: str
    filename: str
    payload: Mapping[str, Any]
```

consumer 不应访问 store 内部的顶层 `files` dict，也不应自行解析 snapshot YAML。

### SnapshotSymbolStore

production backend：

```python
SnapshotSymbolStore.open(
    snapshot_path,
    expected_game_version=gamever,
    expected_config_digest=config_digest,
)
```

打开时必须一次性验证：

- snapshot 是普通文件且不经过不允许的 reparse/symlink 路径。
- UTF-8、YAML parse 和 top-level schema 有效。
- schema version 受支持。
- `game_version` 与 CLI 参数一致。
- `config_sha256` 与当前 analysis contract 一致。
- `file_count` 正确。
- path 使用 canonical POSIX form。
- payload 顶层为 mapping。
- path ordering、recursive key ordering、LF 和 final newline canonical。
- snapshot raw bytes 的 SHA-256。

默认不允许关闭这些验证。单元测试可以通过 internal helper 构造 store，但 production CLI 不能提供 `--skip-validation`。

### DirectorySymbolStore

迁移期 test-only backend：

```python
DirectorySymbolStore(bin_root, game_version)
```

用途仅限：

- 建立 directory 与 snapshot 查询 parity tests。
- 在迁移每个 consumer 时比较旧/新输出。
- 定位现有 consumer 依赖的 undeclared 或 legacy YAML。

最终 production workflow、README 标准命令和 release automation 不得使用该 backend。

### Path Model

Symbol Store 使用前置计划的 canonical key：

```text
<module>/<filename>.yaml
```

API 参数规则：

- `module` 必须是单个 canonical path component。
- `filename` 和 `filename_pattern` 不能包含 `/`、`\\`、`.` 或 `..` path component。
- exact lookup 大小写敏感。
- snapshot 必须在 case-insensitive 语义下无碰撞。
- 所有结果按完整 canonical path 排序。

### Glob Semantics

当前 C++ validation 使用 module directory 内的 filename glob。Snapshot backend 必须提供确定、跨平台一致的等价语义。

`glob_module(module, filename_pattern)` 初始只支持：

- literal characters。
- `*`。
- `?`。
- character classes 仅在现有 consumer 确实需要时增加。

明确禁止：

- pattern 中包含 path separator。
- recursive `**`。
- absolute pattern。
- parent traversal。

matching 使用 case-sensitive canonical filename 和确定性 `fnmatchcase` 语义，不依赖 Windows filesystem glob 的大小写行为。

迁移 parity test 如果发现旧流程依赖 case-insensitive glob，应修正 config/symbol naming，而不是把宿主 OS 差异带入 snapshot store。

### Payload Immutability

store 返回的 payload 不允许 consumer 原地修改共享数据。

可选实现：

- `get()` 返回 defensive deep copy。
- 或递归转换为 immutable mapping/list view。

初始实现优先选择清晰正确的 defensive copy；只有 profiling 证明存在显著开销时才引入更复杂的 immutable view。

### Error Model

建议错误类型：

```text
SymbolStoreError
  SnapshotFormatError
  SnapshotCanonicalError
  SnapshotConfigMismatchError
  SnapshotGameVersionMismatchError
  InvalidSymbolPathError
  SymbolNotFoundError
  CandidateChangedError
```

规则：

- schema/canonical/config mismatch 是 hard failure。
- `get()` 对不存在路径返回 `None`，用于保留明确允许缺失的现有 consumer 语义。
- `require()` 对不存在路径抛出 `SymbolNotFoundError`。
- consumer 必须显式选择 `get` 或 `require`，不能捕获所有异常后回退到 filesystem。
- 错误日志输出 canonical key、snapshot path 和 candidate SHA-256，不输出整个大 snapshot。

## No-Fallback Rule

迁移完成后，以下模式被禁止：

```python
payload = snapshot_store.get(module, filename)
if payload is None:
    payload = load_yaml_from_bin(...)
```

也禁止：

- snapshot store missing 后 glob `bin`。
- snapshot parse 失败后使用 persisted YAML。
- candidate config digest mismatch 后读取 tracked old snapshot。
- PR actual candidate mismatch 后改用 head snapshot运行 downstream。

production consumer CLI 必须保证 source selection 是 mutually exclusive，并在 candidate 模式下不保留任何隐式 directory fallback。

## `update_gamedata.py` Migration

### Function Boundary

当前：

```python
load_all_yaml_data(config, bin_dir, gamever, platforms, debug=False)
```

目标：

```python
load_all_yaml_data(config, symbol_store, platforms, debug=False)
```

内部 lookup 从：

```python
os.path.join(bin_dir, gamever, module_name, filename)
```

改为：

```python
symbol_store.get(module_name, filename)
```

missing diagnostic 中的 `path` 改为 canonical store key，例如：

```text
server/Foo.windows.yaml
```

### CLI

最终 production CLI：

```powershell
uv run update_gamedata.py \
  -gamever 14168 \
  -snapshot "$CANDIDATE_SNAPSHOT" \
  -configyaml config.yaml
```

规则：

- `-snapshot` 在 production workflow 中必须显式传入，不能默认读取 tracked head snapshot。
- `-bindir` 不再参与 YAML 读取。
- 迁移期如保留 `-bindir`，必须要求显式 `-symbolstore directory`，并只用于 parity/debug tests。
- `-snapshot` 与 directory backend 参数 mutually exclusive。
- 启动时打印 candidate SHA-256、game version、file count 和 config digest。

### Base And Dist Overlay Config

`update_gamedata.py` 当前会加载 base `config.yaml`，再与 `dist/*/config.yaml` 合并。

迁移后：

- candidate config digest 仍绑定 base analysis contract。
- dist overlay 是 consumer mapping，不得改变 candidate formal file set。
- overlay 可以覆盖 alias/category 等 downstream mapping。
- overlay 不得让 consumer 从 snapshot formal set 之外读取文件。
- overlay 添加的新 logical symbol 如果无法解析到 candidate key，必须沿用明确、可测试的 missing/skip 语义，不能 fallback 到 `bin`。

实施前必须进行一次 consumer coverage audit：

1. 枚举所有 `dist/*/config.yaml` 合并后的 symbol/platform lookup。
2. 将 lookup 转换为 canonical candidate keys。
3. 与 formal snapshot paths 比较。
4. 分类为 required、explicitly optional、alias-resolved 或 invalid consumer reference。
5. 修复任何依赖 undeclared workspace YAML 的配置。

本计划不强制在迁移时把所有历史 skip 变成 hard failure，但所有允许缺失必须有定向测试，不能通过 directory fallback 隐式成功。

### Alias And Patch Compatibility

现有逻辑中的：

- canonical name lookup。
- patch compatibility aliases。
- `::` 到 `_` 的 alias mapping。
- platform gate。

都必须保持行为不变，只替换 physical data source。

alias lookup 仍然只能在 candidate keys 内进行。alias 指向 candidate 中不存在的 YAML 时，按现有 missing/skip contract 处理并输出 canonical attempted keys。

### Struct Member And Legacy Fallback

现有 structmember 逻辑可能先查：

```text
<module>/<logical-symbol>.<platform>.yaml
```

再查 legacy：

```text
<module>/<struct-name>.<platform>.yaml
```

迁移规则：

- 两次 lookup 都通过同一个 `SnapshotSymbolStore`。
- legacy file 如果属于正式兼容输入，必须被前置计划的 required/optional contract 声明并进入 candidate。
- strict pack 下的 undeclared legacy YAML 不得被 consumer 看见。
- 迁移测试必须覆盖 new-format 优先、legacy fallback、member missing 和 platform-specific cases。

### Downstream Output Semantics

只更换 symbol source，不应在同一阶段顺便改变：

- JSON/VDF/JSONC format conversion。
- alias normalization output。
- skip/update counters。
- dist module discovery。
- download-latest behavior。

Directory 与 Snapshot backend 在同一 fixture 上必须生成 byte-equivalent downstream outputs，除非现有输出本身包含非确定数据；如有例外必须单独记录。

## C++ Validation Migration

### Function Boundary

当前 C++ helpers 接收：

```text
bindir + gamever + module list + filename glob
```

目标改为：

```text
symbol_store + module list + filename glob
```

重点修改：

- `load_merged_reference_vtable_data`
- `load_reference_vtable_data`
- `load_merged_reference_structmember_data`
- `compare_compiler_vtable_with_yaml`
- `compare_compiler_record_layout_with_yaml`
- `compile_and_compare`
- `run_one_test`

### CLI

目标命令：

```powershell
uv run run_cpp_tests.py \
  -gamever 14168 \
  -snapshot "$CANDIDATE_SNAPSHOT" \
  -configyaml config.yaml
```

`-bindir` 不再用于 reference YAML 查询。若未来 C++ tests 需要 bin 中的非-YAML文件，应为该资源增加独立、明确命名的参数，不能借此恢复 YAML fallback。

### VTable Query

现有 module directory glob：

```text
<class-name>_*.{platform}.yaml
```

改为：

```python
symbol_store.glob_module(
    module_name,
    f"{effective_class_name}_*.{platform}.yaml",
)
```

必须保持：

- module selection。
- alias class names。
- merge/non-merge reference modules。
- deterministic file ordering。
- conflict reporting。
- pointer size 和 target triple mapping。

### Record Layout Query

structmember glob 同样迁移到 `glob_module`，并保持：

- member name normalization。
- member offset/size parsing。
- repeated member conflict reporting。
- reference modules filtering。

### Independence Test

candidate 生成后，测试应允许删除或移动 `bin/<GAMEVER>/**/*.yaml`，然后运行 C++ validation。

如果 C++ tests 仍能成功且结果不变，才能证明它已经真正只依赖 candidate。

## CLI And Orchestration Design

### Why Pack Should Not Be Embedded In Each Producer

不应让每个 finder、module worker 或 platform worker自行调用 pack，因为会：

- 产生不完整 snapshot。
- 增加大文件重复序列化。
- 引入并行写竞争。
- 使失败边界不清晰。

也不建议让 `ida_analyze_bin.py` 直接 import snapshot module 后在内部写 tracked file，因为 snapshot formal-set implementation 可能复用 analyzer 的 artifact path semantics，容易形成循环依赖。

推荐由 top-level orchestration wrapper 或 workflow 将以下两个步骤组成不可分割的 production sequence：

```text
run analyzer
if analyzer exit == 0:
    pack candidate
else:
    fail without candidate
```

### Candidate Commands

可以扩展 `gamesymbol_snapshot.py` 或新增薄 orchestration CLI：

```text
gamesymbol_candidate.py
```

建议命令：

```powershell
uv run gamesymbol_candidate.py build \
  -gamever 14168 \
  -bindir bin \
  -configyaml config.yaml \
  -output "$CANDIDATE_SNAPSHOT" \
  -session "$CANDIDATE_SESSION"

uv run gamesymbol_candidate.py compare \
  -candidate "$CANDIDATE_SNAPSHOT" \
  -expected gamesymbols/14168.yaml \
  -configyaml config.yaml

uv run gamesymbol_candidate.py publish \
  -candidate "$CANDIDATE_SNAPSHOT" \
  -session "$CANDIDATE_SESSION" \
  -snapshot gamesymbols/14168.yaml
```

职责边界：

- `build` 调用前置计划的 pack library，不能复制 serializer。
- `compare` 验证两个 snapshot 后进行 byte/semantic diff，不读取 `bin`。
- `publish` 不 pack，只复制已验证 candidate bytes。
- session state 由 orchestration 更新；普通 PR workflow 不调用 `publish`。

### Candidate Session Manifest

建议使用 untracked JSON manifest：

```json
{
  "schema_version": 1,
  "game_version": "14168",
  "candidate_path": "<staging path>",
  "candidate_sha256": "sha256:<raw-bytes-hash>",
  "config_sha256": "sha256:<analysis-contract-hash>",
  "state": "candidate_ready",
  "completed_steps": {
    "analysis": true,
    "pack": true,
    "expected_compare": null,
    "gamedata": false,
    "cpp_tests": false
  }
}
```

规则：

- manifest 与 candidate 放在同一 session staging root。
- manifest 可包含本地路径，但绝不提交 Git。
- manifest 每次状态更新使用 atomic replace。
- publish 前要求 state 为 `validated`。
- publish 重新验证 candidate hash、schema、game version 和 config digest。
- manifest 只能防止误操作，不能替代 workflow trust boundary 或 snapshot validation。

### Automatic Pack Enforcement

production 中“analysis 后自动 pack”通过唯一支持的 orchestration entrypoint 和 workflow gate 强制：

- production workflow 不直接调用裸 `ida_analyze_bin.py` 后跳到 downstream。
- analyzer success step 的唯一后继是 candidate `build`。
- downstream jobs/steps 必须依赖 candidate artifact 和 manifest。
- static workflow tests 检查 analyzer、candidate build、consumer 和 publication 的顺序。
- README 将裸 analyzer invocation 标记为 low-level/debug workflow；它产生的 `bin` 不能直接发布或驱动 downstream。

如果后续新增其他 production analysis entrypoint，必须同样接入 candidate build，否则 Change Delivery Gate 失败。

### Publication Without Repack

`publish` 必须执行 byte-preserving promotion：

1. 读取 session 中记录的 candidate SHA-256。
2. 重新计算 candidate SHA-256 并比较。
3. 重新执行 snapshot structural/canonical/config validation。
4. 将 candidate raw bytes 复制到 published destination 所在目录的 temporary file。
5. flush，并在适用平台执行 fsync。
6. 对 destination temp file 计算 SHA-256，要求等于 candidate。
7. 使用 `os.replace()` 原子更新 `gamesymbols/<GAMEVER>.yaml`。
8. 重新读取 published file 并确认 SHA-256 相等。
9. session 状态更新为 `published`。

因为 runner temp 和 repository 可能位于不同 volume，不能假设直接 move 是原子的。必须先 copy 到 destination directory，再在同一 filesystem 内 atomic replace。

publish 过程中禁止调用 YAML parser/dumper 来重新生成目标内容。

## Developer Workflow

推荐 workflow：

```text
modify analyzer/config/reference
        |
        v
restore trusted baseline if needed
        |
        v
run analysis transaction
        |
        v
automatic strict pack candidate
        |
        v
update_gamedata --snapshot <candidate>
        |
        v
run_cpp_tests --snapshot <candidate>
        |
        v
publish exact candidate bytes
        |
        v
review code + dist + gamesymbols changes
```

建议提供单一 high-level command，将 candidate build、downstream validation 和 optional publish 串联起来；但内部仍应保留可单独运行的 build/compare/publish 子命令用于 CI 和调试。

失败处理：

- gamedata 失败：不发布；修复后如果 analysis outputs 未变，可重新使用同一 candidate。
- C++ tests 失败且只修改 headers：可重新运行 C++ tests，candidate hash 必须不变。
- 修复导致 analyzer/config/reference 改变：废弃 candidate，重新开始 analysis transaction。
- 手工修改 `bin`：不能改变已生成 candidate；如需让改动生效，必须重新 analysis + pack。
- 手工修改 candidate：session hash check 失败，必须重新 pack。

## Ordinary PR Self-Runner Flow

PR trust boundary：

- base snapshot：restore input。
- actual candidate：当前 PR 代码产生的实际结果和唯一 downstream input。
- head snapshot：PR expected result，仅用于 compare。
- persisted YAML：不可信缓存，分析前清除。

推荐步骤：

1. Checkout PR merge ref。
2. 从 head `download.yaml` 读取 `PR_GAMEVER`，只用于优先选择同名 base snapshot。
3. 从 `pull_request.base.sha` 的 snapshot 集合选择 base snapshot，并从该 snapshot 的发布 commit 提取匹配的 base config。
4. 有 base snapshot 时令 `VALIDATION_GAMEVER=BASE_GAMEVER`；bootstrap 时才使用 `PR_GAMEVER`。
5. 复制 persisted `bin/<VALIDATION_GAMEVER>` 到 workspace real `bin` directory。
6. 使用 base config + base snapshot restore `bin/<VALIDATION_GAMEVER>` baseline。
7. 从 `HEAD` 导出同版本 snapshot 原始 Git blob，根据 base/head snapshot、config 和 changed files 计算 invalidation closure。
8. 删除 invalidated producer outputs 和 head 已删除 paths。
9. 运行 Python unit tests 和 head analyzer code，二者都以 `VALIDATION_GAMEVER` 为目标。
10. analyzer success 后立即 strict pack actual candidate 到 runner temp。
11. 将 actual candidate 与 head `gamesymbols/<VALIDATION_GAMEVER>.yaml` 比较。
12. mismatch 时输出 semantic diff 并失败；不运行 publish。
13. `update_gamedata.py` 和 `run_cpp_tests.py` 只读取 actual candidate。
14. 确认 candidate SHA-256 在所有步骤前后不变。
15. 成功结束，不修改 tracked head snapshot。

流程图：

```text
base.sha snapshot + base.sha config
              |
              v
select base snapshot version as VALIDATION_GAMEVER
              |
              v
restore baseline into bin/<VALIDATION_GAMEVER>
              |
              v
invalidate + run head analyzer
              |
              v
pack actual candidate exactly once
              |
              +------ compare ------> PR head snapshot
              |                         expected only
              v
SnapshotSymbolStore(actual candidate)
              |
       +------+------+
       |             |
       v             v
 update_gamedata   C++ tests
       |             |
       +------+------+
              |
              v
      complete without publish
```

禁止：

```text
PR head snapshot
    -> SnapshotSymbolStore
    -> downstream passes
```

该流程仍然是 self-validation loop，即使 analyzer 在之前运行过也不能接受。

## Build And New Game Version Flow

正式 build/new-version workflow：

1. 准备真实 workspace `bin/<GAMEVER>`。
2. 从可信 old-version snapshot restore reuse baseline，或为 major update 按规则禁用 reuse。
3. 运行完整 analysis。
4. strict pack candidate 到 runner temp。
5. gamedata 只读取 candidate。
6. C++ tests 只读取 candidate。
7. 所有 validation 成功后 publish candidate raw bytes。
8. publish 成功后才允许回写 persisted workspace caches。
9. 使用 published bytes 创建 follow-up snapshot PR 或后续 tag-containing-snapshot flow。

顺序必须是：

```text
analysis
  -> candidate pack
  -> downstream validation
  -> publish same bytes
  -> persisted cache writeback
  -> PR/release automation
```

validation 失败或 job 取消时：

- 不发布 tracked snapshot。
- 不回写 persisted YAML。
- 不创建 snapshot PR。
- candidate 可作为受控 debugging artifact 上传，但必须明确标记为 unvalidated，不得作为 release artifact。

## Replay And Historical Versions

对已经 published 的历史版本，可以直接把 tracked snapshot 作为 read-only Symbol Store：

```powershell
uv run update_gamedata.py \
  -gamever 14168 \
  -snapshot gamesymbols/14168.yaml

uv run run_cpp_tests.py \
  -gamever 14168 \
  -snapshot gamesymbols/14168.yaml
```

这类 replay 不涉及新 analysis，因此 tracked snapshot 本身就是可信 immutable input，不需要重新创建 candidate。

如果 replay 的 config digest 与 snapshot 不匹配，必须失败；不能忽略 digest 或回退到 `bin`。

## Trust And Safety Boundaries

### Candidate Versus Expected

actual candidate 和 head expected snapshot 必须由不同路径加载：

- candidate 来自当前 analyzer actual `bin` strict pack。
- expected 来自 PR head Git object。
- compare 只比较二者。
- consumer 只接收 candidate path。

workflow variable 命名应避免混淆：

```text
ACTUAL_CANDIDATE_SNAPSHOT
EXPECTED_HEAD_SNAPSHOT
BASE_RESTORE_SNAPSHOT
```

禁止使用含糊的 `SNAPSHOT_PATH` 同时承担多个角色。

### Workspace And Reparse Points

沿用前置计划门禁：

- workspace `bin` 必须是真实目录。
- YAML cleanup 只能作用于当前 workspace copy。
- candidate staging root 必须位于批准的 temp root。
- candidate、session manifest 和 published destination 必须拒绝 unexpected symlink/junction/reparse traversal。
- publication 只能写入明确的 `gamesymbols/<GAMEVER>.yaml` destination。

### Untrusted Snapshot Content

snapshot 使用 `yaml.safe_load()`。

所有 canonical keys 在查询前验证：

- 非绝对路径。
- 无 `.` / `..`。
- 无空 component。
- 无 path separator 混用。
- 无 case collision。

Symbol Store 只把 key 当逻辑 identifier，不将 snapshot key重新拼接到 filesystem 读取路径。

### Process Failure

- analyzer non-zero：不 pack。
- pack non-zero：不运行 consumer。
- consumer non-zero：不 publish。
- publish 中断：destination temp 可清理，原 tracked snapshot 保持不变。
- workflow cancellation：finally cleanup candidate/session temp；不回写 persisted workspace。

## Compatibility And Migration Strategy

不能一次删除所有 directory APIs 后再发现现有行为差异。采用短期双 backend、最终单 production backend 的迁移方式。

### Compatibility Phase

- 新增 `SymbolStore` protocol。
- 用 `DirectorySymbolStore` 封装现有 filesystem 行为。
- 用 `SnapshotSymbolStore` 实现 candidate 读取。
- consumer core 只依赖 protocol。
- tests 对两个 backend 运行同一组 fixtures。

### Cutover Phase

- production workflow 显式传入 candidate snapshot。
- downstream CLI 日志确认 backend 为 `snapshot`。
- 删除 workflow 中传给 downstream 的 YAML `-bindir`。
- candidate pack 后，在一个 integration test 中删除 workspace YAML，再运行 downstream。

### Enforcement Phase

- production CLI 默认或强制使用 snapshot。
- directory backend 标记 internal/test-only。
- repository workflow static tests 禁止 downstream 使用 `-bindir`。
- 搜索并审计 repository-owned downstream code 中所有 `bin/<GAMEVER>/**/*.yaml` 读取。
- 对新增 consumer 增加 architecture test，要求通过 `SymbolStore`。

## Implementation Structure

前置计划完成后，建议文件变化：

- Add: `gamesymbol_store.py`
  - `SymbolStore` protocol。
  - `SymbolEntry`。
  - `SnapshotSymbolStore`。
  - migration/test-only `DirectorySymbolStore`。
  - canonical lookup、module glob、error types。
- Add: `gamesymbol_candidate.py`
  - candidate build、compare、guard、validation mark 和 publish 的薄 CLI。
  - candidate SHA-256 guard。
  - byte-preserving atomic promotion。
- Add: `gamesymbol_snapshot_lib/candidate.py` / `candidate_session.py`
  - typed candidate library API、manifest state、file-identity guard 与 atomic I/O。
- Modify: `gamesymbol_snapshot.py`
  - 将 formal-set collector、parser、canonical encoder 和 validation 暴露为稳定 library API。
  - 保证 candidate build 和 published snapshot 共用同一 serializer。
  - 增加 snapshot-to-snapshot semantic compare helper。
- Modify: `update_gamedata.py`
  - `load_all_yaml_data` 改为接收 `SymbolStore`。
  - 增加 `-snapshot`。
  - 删除 production directory fallback。
  - missing diagnostics 使用 canonical store key。
- Modify: `cpp_tests_util.py`
  - vtable/record reference loaders 改为通过 `SymbolStore` exact/glob query。
- Modify: `run_cpp_tests.py`
  - 增加 `-snapshot` 并构造共享 store。
  - 不再将 `bindir` 传给 YAML compare helpers。
- Keep: `gamesymbol_pr_validation.py`
  - 保持专注于 base/head invalidation；analysis 后的 candidate build/compare 由共享 candidate CLI 和 workflow 编排，
    避免把 transaction lifecycle 混入 invalidation module。
- Modify: `.github/workflows/pr-self-runner.yml`
  - analyzer 后立即 candidate build。
  - actual/head compare。
  - downstream 只接收 actual candidate。
  - ordinary PR 不 publish。
- Modify: `.github/workflows/build-on-self-runner.yml`
  - candidate-first downstream flow。
  - validation success 后 byte-preserving publish。
  - publish 后才回写 persisted caches。
- Add: `tests/test_gamesymbol_store.py`
  - Snapshot/Directory backend contracts 和 parity。
- Add: `tests/test_gamesymbol_candidate.py`
  - lifecycle、hash guard、failure atomicity 和 publication identity。
- Modify: `tests/test_update_gamedata.py`
  - store fixtures、overlay/alias/legacy cases 和 no-bin independence。
- Modify: `tests/test_run_cpp_tests.py`
  - snapshot glob、merged module、vtable/record parity、CLI source selection 和 candidate-only integration。
- Add: `tests/test_symbol_store_architecture.py`
  - 禁止 production consumer 恢复 direct bin/directory YAML reads。
- Modify: workflow tests
  - enforce analyzer -> pack -> downstream -> publish ordering。
  - forbid head snapshot as consumer input。
- Modify: `README.md` / `README_CN.md`
  - 记录 candidate transaction、source roles、standard commands 和 failure recovery。
- Modify after implementation: `docs/plans/track-gamesymbols-snapshot.md`
  - 标记被本计划 supersede 的 Non-Goals/publication timing/final architecture。

## Library API Boundaries

为了避免 CLI 间复制逻辑，建议至少提供以下稳定 Python APIs：

```python
def build_candidate_snapshot(
    *,
    game_version: str,
    bin_root: Path,
    config_path: Path,
    output_path: Path,
) -> CandidateInfo: ...

def open_snapshot_store(
    *,
    snapshot_path: Path,
    config_path: Path,
    expected_game_version: str,
) -> SnapshotSymbolStore: ...

def compare_snapshots(
    *,
    actual_path: Path,
    expected_path: Path,
    config_path: Path,
    expected_game_version: str,
) -> SnapshotDiff: ...

def publish_candidate(
    *,
    candidate_path: Path,
    candidate_sha256: str,
    destination: Path,
) -> PublishedInfo: ...
```

`CandidateInfo` 至少包含：

- path。
- raw-byte SHA-256。
- game version。
- config digest。
- file count。

这些 API 必须抛出 typed exceptions，不调用 `sys.exit()`；CLI wrapper 再将错误映射为 exit code。

## Exit Codes And Failure Reporting

建议统一 exit codes：

- `0`: success。
- `1`: data mismatch、downstream validation failure 或 candidate changed。
- `2`: CLI/schema/config/path contract error。
- `3`: publication I/O failure。

candidate build success 日志：

```text
Candidate snapshot ready:
  game_version: 14168
  file_count: 2910
  config_sha256: sha256:...
  candidate_sha256: sha256:...
  path: <staging path>
```

每个 consumer 启动时输出：

```text
Symbol source: snapshot
Candidate SHA-256: sha256:...
Game version: 14168
Config digest: sha256:...
```

PR mismatch 日志继续使用 path/field-level semantic diff，不输出整个 aggregate YAML。

## Test Plan

### SnapshotSymbolStore Tests

- canonical candidate 能成功打开。
- schema version、game version、config digest mismatch 分别失败。
- non-canonical bytes 失败，即使 semantic YAML 相同。
- `file_count` mismatch 失败。
- top-level non-mapping payload 失败。
- path traversal、absolute path、backslash、empty component 和 case collision 失败。
- exact `get`、`require`、`contains` 行为正确。
- `glob_module` 只匹配目标 module。
- glob 结果按 canonical path 稳定排序。
- glob 不依赖宿主 OS 大小写规则。
- payload mutation 不影响 store 内部数据。
- candidate SHA-256 与 raw bytes 一致。

### Directory/Snapshot Parity Tests

- 同一 directory formal set pack 后，两种 backend 的 exact lookup 结果一致。
- module iteration path/order 一致。
- vtable filename glob 结果一致。
- structmember filename glob 结果一致。
- missing path 行为一致。
- platform-specific symbol selection 一致。
- undeclared directory YAML 不会进入 Snapshot backend，并在 strict pack 时失败。

### Candidate Build Tests

- analyzer failure 时不会调用 pack。
- successful transaction 只调用一次 canonical serializer。
- missing required output 导致 candidate build 失败。
- existing optional output 进入 candidate。
- undeclared YAML 导致 candidate build 失败。
- candidate target 不能位于 tracked `gamesymbols/`。
- candidate target symlink/reparse point 被拒绝。
- temp-write validation 失败不留下 candidate-ready file。
- build 后 reopen/round-trip validation 成功。
- session manifest 与 candidate hash/config digest 一致。

### Candidate Immutability Tests

- gamedata 前 candidate hash 不变。
- gamedata 后 candidate hash 不变。
- C++ tests 前后 candidate hash 不变。
- 手工修改 candidate 后下一个 stage 失败。
- 替换 candidate inode/file 后 hash guard 失败。
- 修改或删除 `bin` YAML 不影响已打开或重新打开的 candidate store。

### `update_gamedata` Tests

- base config exact lookup 通过 Snapshot backend。
- platform gate 行为不变。
- patch alias fallback 行为不变。
- `::` alias normalization 行为不变。
- new-format structmember 优先。
- legacy struct fallback 只从 snapshot 读取。
- legacy file 未进入 formal set 时 strict pack/coverage audit 失败。
- dist overlay override 行为不变。
- dist overlay 新 logical symbol missing 时按显式 contract 处理。
- debug missing report 输出 canonical store keys。
- Directory/Snapshot backend 生成相同 dist output。
- candidate 生成后删除 `bin` YAML，update 仍成功且输出不变。
- snapshot invalid 时不会 fallback 到 `bin`。

### C++ Validation Tests

- vtable single-module lookup 通过 store。
- multi-module merged vtable lookup 结果不变。
- `merge_reference_modules=false` 行为不变。
- alias class names 行为不变。
- record layout member lookup 结果不变。
- glob ordering 稳定。
- missing reference reporting 保持可读。
- candidate 生成后删除 `bin` YAML，C++ compare 仍成功。
- invalid candidate 不会 fallback 到 directory。

### Snapshot Compare Tests

- actual candidate 与 canonical head snapshot byte-identical 时成功。
- semantic equal 但 head non-canonical 时失败。
- metadata、added、missing、modified path 分别产生可读报告。
- expected config digest 过期时失败。
- compare 不访问 `bin`。

### Publication Tests

- validation state 非 `validated` 时拒绝 publish。
- candidate hash 改变时拒绝 publish。
- candidate schema/config/game version 无效时拒绝 publish。
- destination 写入失败时原 snapshot 不变。
- cross-volume source 通过 copy-to-destination-temp + replace 发布。
- published raw bytes 与 candidate 完全一致。
- publish 不调用 YAML dumper。
- publish 成功后 session state 为 `published`。
- publication failure 不回写 persisted workspace。

### PR Workflow Tests

- base snapshot 只用于 restore。
- head snapshot 只用于 expected compare。
- actual candidate 来自 analyzer actual bin。
- analyzer success 的直接后继是 candidate build。
- candidate mismatch 在 downstream 前失败。
- downstream CLI 接收 actual candidate path。
- downstream CLI 不接收 head/base snapshot path。
- downstream command 不包含 YAML `-bindir` fallback。
- ordinary PR 从不调用 publish。
- persisted YAML 不能成为 consumer input。

### Build Workflow Tests

- analysis 后只 pack 一次 candidate。
- gamedata 和 C++ tests 使用相同 candidate SHA-256。
- validation 失败不发布 snapshot。
- validation 成功后 publish 同一 candidate bytes。
- publish 发生在 persisted cache writeback 之前。
- job cancel 不回写 cache 或创建 snapshot PR。
- follow-up PR 使用已发布 candidate bytes，不重新 pack。

### End-To-End Independence Test

关键 acceptance test：

```text
run analysis
    -> pack candidate
    -> move/delete all bin/<GAMEVER>/**/*.yaml
    -> run update_gamedata from candidate
    -> run C++ validation from candidate
```

必须证明：

- 两个 downstream consumer 不再打开任何 bin YAML。
- 输出和 compare 结果与删除前一致。
- published snapshot 仍与 candidate byte-identical。

## Rollout Plan

状态：Step 0 至 Step 8 已全部实施并通过上述 acceptance replay。

### Step 0: Prerequisite Completion Gate

- `track-gamesymbols-snapshot.md` 的所有 acceptance criteria 已满足。
- snapshot schema/canonical writer/formal set/restore/verify API 已稳定。
- PR source-aware invalidation 和 dependency closure 已上线。
- workspace/persisted cache safety gate 已上线。
- 至少一个 bootstrap game version snapshot 已 tracked。

任一条件未满足时不开始本计划实现。

### Step 1: Consumer Coverage Audit

- 枚举 `update_gamedata` 的 base + dist overlay lookup。
- 枚举 C++ vtable/record glob patterns。
- 对照 formal snapshot paths。
- 修复或声明 legacy/optional consumer inputs。
- 记录允许缺失的现有行为并补测试。

### Step 2: Symbol Store Core

- 实现 `SymbolStore` protocol 和 typed errors。
- 实现 `SnapshotSymbolStore`。
- 实现 migration-only `DirectorySymbolStore`。
- 实现 exact/module-glob/path validation。
- 完成 backend parity tests。

### Step 3: Candidate Transaction Core

- 将 snapshot pack/compare/publish 提取为 library APIs。
- 实现 candidate session、hash guard 和 staging safety。
- 实现 byte-preserving atomic publish。
- 完成 failure injection 和 publication identity tests。

### Step 4: `update_gamedata` Migration

- loader 改为 `SymbolStore`。
- 增加 candidate `-snapshot` CLI。
- 完成 alias/patch/struct/overlay parity tests。
- production workflow 切换为 candidate backend。
- 验证删除 bin YAML 后 gamedata 仍能生成。

### Step 5: C++ Validation Migration

- reference loaders 改为 `SymbolStore`。
- module glob 改为 deterministic store query。
- `run_cpp_tests.py` 增加 candidate `-snapshot`。
- 完成 vtable/record parity tests。
- 验证删除 bin YAML 后 C++ validation 仍能运行。

### Step 6: PR Candidate Flow

- analyzer 后自动 strict pack actual candidate。
- candidate/head snapshot compare。
- downstream 只读取 actual candidate。
- 禁止普通 PR publish。
- 增加 workflow ordering/trust-boundary tests。

### Step 7: Build Publication Flow

- build/new-version workflow 改为 candidate-first validation。
- validation success 后原字节 publish。
- publish 后才允许 persisted cache writeback。
- follow-up PR/release 复用 published bytes。

### Step 8: Enforcement And Cleanup

- 从 production docs/workflows 移除 downstream `-bindir` YAML source。
- 将 DirectorySymbolStore 限制为 tests/internal migration tooling。
- repository-wide audit 所有 downstream bin YAML reads。
- 更新 README、前置计划的 superseded sections 和 architecture diagram。
- 将 direct-to-tracked pack 标记为 bootstrap/legacy-only，标准流程统一使用 candidate promotion。

## Acceptance Criteria

- 前置 `track-gamesymbols-snapshot.md` 已完成并保持通过。
- production analysis success 后自动执行一次且仅一次 strict candidate pack。
- candidate 使用与 published snapshot 相同的 schema 和 canonical encoder。
- candidate 不包含任何临时或 validation-only metadata。
- candidate-ready 后 raw-byte SHA-256 在所有 downstream stages 中保持不变。
- `update_gamedata.py` 的唯一 symbol source 是 actual candidate `SnapshotSymbolStore`。
- `run_cpp_tests.py` 的唯一 YAML reference source 是同一个 actual candidate `SnapshotSymbolStore`。
- 两个 consumer 在 candidate 生成后删除全部 `bin/<GAMEVER>/**/*.yaml` 仍可运行并产生相同结果。
- snapshot missing/invalid/config mismatch 时 consumer 失败或按显式 missing contract 处理，绝不 fallback 到 `bin`。
- PR base snapshot 只用于 restore。
- PR head snapshot 只用于 expected compare。
- PR actual candidate 是 downstream 唯一输入。
- 普通 PR workflow 不发布或改写 tracked snapshot。
- validation 失败、异常或取消时 tracked snapshot byte-for-byte 不变。
- validation 成功后 publication 不执行第二次 pack。
- published snapshot raw bytes 与 candidate 完全一致。
- publish 成功前不回写 persisted workspace YAML。
- candidate/head mismatch 有 path/field-level diagnostics。
- dist overlay、patch alias、legacy struct、vtable glob 和 record layout 行为都有 parity tests。
- production workflow 不再将 `-bindir` 作为 downstream YAML source。
- repository-owned 新 downstream symbol consumer 必须通过 `SymbolStore`，不能直接读取 `bin` YAML。

## Final Architecture

```text
config.yaml + preprocessors + Agent SKILLs + references
                         |
                         v
                 ida_analyze_bin.py
                         |
                         v
          bin/<GAMEVER>/**/*.yaml
       mutable analyzer workspace only
                         |
                         v
        strict canonical pack exactly once
                         |
                         v
             candidate snapshot bytes
             sha256 = CANDIDATE_SHA
                         |
              +----------+----------+
              |                     |
              v                     v
      update_gamedata.py       run_cpp_tests.py
              |                     |
              +----------+----------+
                         |
                         v
                 full validation
                         |
               success  |  failure
                  +------+------+
                  |             |
                  v             v
      publish same raw bytes    discard/no publish
                  |
                  v
      gamesymbols/<GAMEVER>.yaml
        sha256 = CANDIDATE_SHA
```

最终语义：

```text
bin
  = mutable producer workspace

candidate snapshot
  = immutable analysis transaction result
  = sole downstream Symbol Store

published snapshot
  = validation-approved candidate bytes
  = durable Git source of truth
```

该设计使 analysis、gamedata、C++ validation 和 publication 围绕同一 candidate identity 建立严格事务边界：
analyzer 可以继续使用适合增量工作的 per-symbol YAML，但所有 read-only downstream consumer 只看到已经 canonicalized、
可验证并且最终能够原字节发布的 snapshot。
