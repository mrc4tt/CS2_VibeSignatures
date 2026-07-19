# Track Game Symbols Snapshot

## Status

本文记录 `gamesymbols/<GAMEVER>.yaml` 的已确认设计及实施计划。

后续计划 `candidate-snapshot-as-symbol-store.md` 已将本计划的阶段性 downstream source 与 publication timing
升级为 candidate-first 架构。本文保留前置设计依据；下文标注 superseded 的条款以该后续计划和当前实现为准。

后续计划 `snapshot_version.md` 进一步 supersede 本文中“任何 base snapshot contract mismatch 都立即失败”的
条款：普通 PR 的 base snapshot 是可丢弃缓存，trust probe 判定不可信时必须 warning + clean bootstrap；HEAD
snapshot、actual candidate 与 publication boundary 继续严格失败。

### Implementation Progress (2026-07-15)

已完成：

- deterministic `pack` / `restore` / `verify` CLI、formal output collector、canonical schema 与强制 round-trip。
- snapshot/config/source-aware PR invalidation、完整 artifact dependency closure 与 fail-safe broad rebuild。
- PR workflow 的 base/head/actual trust boundary、analysis 后 actual candidate strict pack，以及 snapshot-only downstream。
- build workflow 的 candidate-first validation、原字节 publish、publish 后 cache 回写与 follow-up snapshot PR。
- formatter exclusion、README / README_CN 使用说明，以及 snapshot / invalidation / workflow tests。

Bootstrap 状态：已删除历史遗留的 undeclared ignored 文件
`bin/14168/server/CBaseEntity_SetStateChanged.windows.yaml`。`14168` 的 2887 个 required YAML 全部存在，
22 个 optional YAML 被收集；正式 `gamesymbols/14168.yaml` 已生成，共包含 2909 个 payload，并已通过
canonical comparison、snapshot round-trip、actual-bin round-trip 和 strict `verify`。

核心结论：

- `bin/<GAMEVER>/**/*.yaml` 继续作为 ignored 本地工作区文件，不直接提交到 Git。
- 每个游戏版本将正式 symbol YAML 聚合为单个、受 Git 跟踪的 analysis lockfile：
  `gamesymbols/<GAMEVER>.yaml`。
- snapshot 使用相对于 `bin/<GAMEVER>/` 的完整 `module/filename` 作为 key。
- snapshot 的正式文件集合必须从 `config.yaml` 推导，不能通过无约束的目录 glob 决定。
- 提供确定性的 `pack`、`restore`、`verify` CLI。
- `verify` 必须执行 round-trip，证明 snapshot 可以无损恢复并重新打包为相同 canonical 内容。
- 普通 PR 必须提交对应 game version 的 snapshot 更新。CI 从 base snapshot 构造确定性分析起点，重建受影响输出，并验证实际结果与 PR 中的 head snapshot 一致。
- PR 中的 head snapshot 是待验证结果，不能作为本次分析的输入，否则会形成自证循环。
- analysis 成功后立即 strict pack candidate；正式 snapshot 只允许在 gamedata 与 C++ validation 全部成功后，
  原字节 publish 该 candidate。

## Background

当前项目将每个 symbol 的分析结果写入：

```text
bin/<GAMEVER>/<module>/<symbol>.<platform>.yaml
```

这些 YAML 同时承担多种职责：

- `ida_analyze_bin.py` 使用旧版本 YAML 做跨版本 signature reuse。
- `update_gamedata.py` 使用当前版本 YAML 生成下游 gamedata。
- `run_cpp_tests.py` 使用 YAML 验证 vtable 和 record layout。
- PR self-hosted runner 使用 persisted `bin/` 作为分析缓存。

但整个 `bin/` 当前被 `.gitignore` 忽略，因此 YAML 事实状态依赖某台开发机或 self-hosted runner 的本地持久目录。干净 clone 无法恢复同样的分析基线，也无法通过 Git review 审查一次代码修改对应的 symbol 输出变化。

直接提交 `bin/**/*.yaml` 虽然可以解决可复现性问题，但会让每个版本产生数千个 Git 文件，增加 index、review、merge 和历史维护成本。

聚合 snapshot 在两者之间提供更合适的边界：

```text
Git tracked canonical state:
  gamesymbols/<GAMEVER>.yaml

Ignored local working state:
  bin/<GAMEVER>/**/*.yaml

Downstream generated state:
  dist/**
```

## Goals

- 让每个 game version 的正式分析结果成为可审查、可恢复、可验证的 Git 状态。
- 保留 analyzer 的 `bin/<GAMEVER>/<module>/*.yaml` mutable workspace；downstream consumer 统一迁移到 Symbol Store。
- 避免把数千个小 YAML 文件提交到 Git。
- 从 `config.yaml` 推导 snapshot 文件集合，排除 stale、调试或未声明 YAML。
- 保证 snapshot 输出确定，不受文件遍历顺序、Windows 路径分隔符、生成时间或本机路径影响。
- 保证 `pack -> restore -> pack` 得到完全一致的 canonical snapshot。
- 让 PR CI 能识别以下问题：
  - 修改了 finder/preprocessor 但忘记更新 snapshot。
  - 修改了 snapshot，但实际分析结果不匹配。
  - persisted runner YAML 恰好包含 PR 结果，导致 analyzer 全部 skip 的假阳性。
  - 上游输出变化后，下游依赖没有重新生成。
- 允许未来从 snapshot 恢复任意 tracked game version，而不依赖 GitHub Release 或某台 runner 的本地状态。

## Non-Goals

- 不将 DLL、SO、IDB 或其他 `bin/` 内容提交到 Git。
- 不改变现有 per-symbol YAML schema。
- ~~不把 snapshot 直接作为 downstream 输入。~~ 已被后续计划 supersede：两个 production consumer 的唯一 symbol
  source 是 actual candidate `SnapshotSymbolStore`。
- 不要求恢复后的单个 YAML 与原文件逐空格、逐引号相同；要求解析后的 YAML 数据和重新生成的 canonical snapshot 一致。
- 不在 CI 中自动修改普通用户 PR 的 tracked snapshot。snapshot 不一致时应失败并要求提交者更新。
- 不使用 snapshot 替代真实二进制分析。
- 不让 self-hosted runner 的 persisted YAML 成为事实来源。

## Repository Layout

目标布局：

```text
gamesymbols/
  14168.yaml
  14168b.yaml
  14169.yaml

bin/
  14168/
    client/
      Foo.windows.yaml
    engine/
      Bar.linux.yaml
    server/
      Baz.windows.yaml
```

`gamesymbols/<GAMEVER>.yaml` 是该版本的 canonical analysis lockfile。

`bin/<GAMEVER>/**/*.yaml` 是 lockfile 的可恢复工作区表示，继续被 `.gitignore` 忽略。

snapshot 不放在 `dist/`，因为它是 `dist` 的上游分析数据，不是某个 downstream consumer 的最终 gamedata。将其放在 `dist/merged/` 会混淆输入与输出边界。

## Snapshot Schema

初始 schema：

```yaml
schema_version: 1
game_version: "14168"
config_sha256: "sha256:<normalized-analysis-contract-digest>"
file_count: 2910
files:
  client/CAM_Command_CommandHandler.windows.yaml:
    func_name: CAM_Command_CommandHandler
    func_va: "0x..."
    func_rva: "0x..."
    func_size: 123
    func_sig: 48 89 5C 24 ?? ...
  engine/ConnectInterfaces.windows.yaml:
    func_name: ConnectInterfaces
    func_va: "0x..."
  server/ConnectInterfaces.windows.yaml:
    func_name: ConnectInterfaces
    func_va: "0x..."
```

### Required Metadata

- `schema_version`
  - 初始值为 `1`。
  - CLI 必须拒绝高于自身支持范围的 schema。
- `game_version`
  - 始终写为字符串。
  - 必须与文件名和 CLI `-gamever` 参数一致。
- `config_sha256`
  - 不是 `config.yaml` 原始字节的 hash。
  - 它是从规范化 analysis contract 计算的 hash，避免注释或纯格式变更制造 snapshot churn。
- `file_count`
  - 必须等于 `files` 中的实际条目数。
- `files`
  - key 是相对于 `bin/<GAMEVER>/` 的完整 POSIX 路径。
  - value 是原 per-symbol YAML 的顶层 mapping。

### Config Digest Contract

`config_sha256` 至少包含以下规范化字段：

- module stage 顺序和 module name。
- `path_windows`、`path_linux` 是否存在以及其值。
- skill name 和 skill 顺序。
- `platform`。
- `expected_output`。
- `expected_output_windows`。
- `expected_output_linux`。
- `optional_output`。
- `expected_input`。
- `expected_input_windows`。
- `expected_input_linux`。
- `prerequisite`。
- `skip_if_exists`。

不应包含：

- YAML 注释。
- description 等不影响分析契约的展示字段。
- 本地绝对路径。
- 生成时间。
- runner 名称。
- 最终 Git commit SHA。snapshot 与包含它的 commit 同时创建，写入最终 commit SHA 会形成循环依赖。

### Path Rules

snapshot key 必须满足：

- 使用 `/` 作为路径分隔符。
- 是相对于 `bin/<GAMEVER>/` 的路径。
- 至少包含 module 和 filename，例如 `server/Foo.windows.yaml`。
- 以 `.yaml` 结尾。
- 不允许绝对路径。
- 不允许 `.`、`..` 或路径逃逸。
- 不允许空 path component。
- 在 Windows case-insensitive 语义下不能发生碰撞。

完整路径是必要条件。当前不同 module 中存在大量同名 YAML，仅使用 basename 会覆盖不同二进制中的 symbol。

### Canonical Ordering

canonical writer 必须保证：

- 顶层 metadata 使用固定顺序。
- `files` 按规范化 path 字典序排列。
- payload mapping 使用确定性的递归 key 顺序。
- list 保留原有顺序。
- 换行统一为 LF。
- 文件以单个换行结束。
- 不输出时间戳或本地环境数据。
- YAML dump 参数固定，不依赖 PyYAML 默认行为变化。

`format_repo_files.py` 应跳过 `gamesymbols/`，与 generated reference YAML 类似。snapshot 只能由 snapshot CLI 的 canonical writer 格式化，避免 `yamlfix` 二次改写后破坏 byte-stable 验证。

## Formal File Set

snapshot 的正式文件集合必须从 `config.yaml` 推导。目录扫描只能用于发现异常 extra 文件，不能用于决定哪些文件进入 snapshot。

### Required Outputs

对每个 module stage、每个实际支持的平台和每个适用 skill：

1. 读取 `expected_output`。
2. 合并对应平台的 `expected_output_<platform>`。
3. 按 analyzer 当前规则展开 `{platform}`。
4. 使用与 `ida_analyze_bin.resolve_artifact_path()` 一致的安全路径解析。
5. 仅保留 `.yaml` 输出。
6. 将路径转换为相对于 `bin/<GAMEVER>/` 的 canonical key。

所有 required YAML 必须存在、可解析且顶层为 mapping。任一 required YAML 缺失时，`pack` 和 `verify` 必须失败。

### Optional Outputs

`optional_output` 同样属于 config 声明的正式输出 universe，但允许不存在：

- optional YAML 存在时必须进入 snapshot。
- optional YAML 不存在时不是错误，也不进入 snapshot。
- 同一路径同时被声明为 required 和 optional 时，以 required 为准。

### Platform Rules

- module 没有对应 `path_<platform>` 时，该 module stage 不为该平台产生正式输出。
- skill 设置 `platform` 时，仅处理匹配平台。
- platform-specific output 只在对应平台展开。

正式集合逻辑必须与 analyzer 实际执行平台保持一致，不能无条件为所有 module 生成 Windows 和 Linux 路径。

### Repeated Module Stages

`config.yaml` 允许同名 module 多次出现。snapshot key 不包含 stage index，因为磁盘输出最终仍写入同一个：

```text
bin/<GAMEVER>/<module>/...
```

正式集合对重复 path 去重，但 owner graph 必须保留所有声明该 path 的 skill/stage，用于 PR invalidation 和依赖闭包计算。

### Cross-Module Outputs

现有 artifact path 解析允许 output 离开当前 module directory，但禁止离开 game version root。因此 snapshot collector 必须：

- 支持合法的跨 module artifact path。
- 使用最终解析后的 game-version-relative path 作为 key。
- 拒绝逃逸 `bin/<GAMEVER>/` 的路径。

### Undeclared YAML

未由当前 config 声明的 YAML：

- 不得进入 snapshot。
- `pack` 应报告这些文件。
- CI strict mode 应将其视为错误，防止 analyzer 或脚本生成未声明的正式输出。
- 初始迁移时应清理现有 stale YAML，或将仍有用途的文件显式加入 config。

这里允许受限 glob 仅用于诊断 `actual YAML - formal YAML`。正式集合本身仍完全由 config 推导，不是由 glob 生成。

## CLI Design

新增确定性 CLI：

```text
gamesymbol_snapshot.py
```

核心命令：

```powershell
uv run gamesymbol_snapshot.py pack -gamever 14168
uv run gamesymbol_snapshot.py restore -gamever 14168
uv run gamesymbol_snapshot.py verify -gamever 14168
```

公共参数：

- `-gamever`
- `-bindir`, 默认 `bin`
- `-configyaml`, 默认 `config.yaml`
- `-snapshot`, 默认 `gamesymbols/<GAMEVER>.yaml`
- `-debug`

### Pack

```powershell
uv run gamesymbol_snapshot.py pack \
  -gamever 14168 \
  -bindir bin \
  -configyaml config.yaml \
  -snapshot gamesymbols/14168.yaml
```

`pack` 必须：

1. 解析 config 并构造正式 required/optional 文件集合和 owner graph。
2. 检查所有 required YAML 存在。
3. 收集实际存在的 optional YAML。
4. 逐文件使用 `yaml.safe_load()`，要求顶层为 mapping。
5. 检查 path traversal、case collision 和重复 path 冲突。
6. 检查 undeclared YAML；默认 strict mode 下失败。
7. 在内存中构造 canonical snapshot。
8. 先写临时文件并重新读取验证。
9. 使用原子 replace 更新目标 snapshot。

验证失败时不能留下部分 snapshot。

`pack` 是开发者在本地完整 validation 成功后更新 lockfile 的入口。CI 对普通 PR 不应调用会修改 tracked 文件的 `pack`，而应调用只读 `verify`。

### Restore

默认 restore：

```powershell
uv run gamesymbol_snapshot.py restore -gamever 14168
```

默认行为：

- 目标文件不存在：写入。
- 目标文件语义相同：跳过。
- 目标文件语义不同：失败，不覆盖。

精确恢复：

```powershell
uv run gamesymbol_snapshot.py restore -gamever 14168 -replace
```

`-replace` 必须：

- 在修改磁盘前完整验证 snapshot。
- 只删除 `bin/<GAMEVER>/**/*.yaml`。
- 不删除 game version 目录本身。
- 不删除或修改 DLL、SO、I64、ID0、ID1、ID2、NAM、TIL 或其他文件。
- 删除 YAML 后按 snapshot 重建目录和文件。
- 恢复完成后执行一次 pack-in-memory 比较。

恢复操作不能信任 snapshot path。所有 path 必须先解析并确认位于目标 game version root 内。

### Verify

```powershell
uv run gamesymbol_snapshot.py verify \
  -gamever 14168 \
  -bindir bin \
  -configyaml config.yaml \
  -snapshot gamesymbols/14168.yaml
```

`verify` 是只读命令，必须完成：

1. schema 和 metadata 验证。
2. game version 验证。
3. config contract digest 验证。
4. 正式 required/optional 文件集合验证。
5. 实际 `bin` payload 与 snapshot payload 的语义比较。
6. canonical snapshot byte comparison。
7. undeclared YAML strict 检查。
8. round-trip 验证。

返回码建议：

- `0`: 完全一致。
- `1`: 数据、文件集合或 round-trip 不一致。
- `2`: 参数、schema 或配置错误。

### Mismatch Reporting

CI 日志不应只输出整个大 YAML 的 unified diff。CLI 应提供 path-level 摘要：

```text
Snapshot mismatch:
  Added in actual:
    server/Foo.windows.yaml

  Missing from actual:
    engine/Bar.linux.yaml

  Modified:
    server/Baz.windows.yaml
      func_sig:
        snapshot: 48 89 5C 24 ?? ...
        actual:   48 89 54 24 ?? ...
```

对大 mapping 或 list 可限制日志长度，但必须保留 path 和变化字段。

## Round-Trip Contract

round-trip 是 `verify` 的强制组成部分，不是可选测试。

### Snapshot Round-Trip

```text
tracked snapshot
      |
      v
restore into temporary bin root
      |
      v
pack from temporary bin root
      |
      v
canonical bytes equal tracked snapshot
```

必须满足：

```text
pack(restore(snapshot)) == canonical(snapshot)
```

### Actual Bin Round-Trip

```text
actual bin YAML
      |
      v
pack in memory
      |
      v
restore into temporary bin root
      |
      v
pack again
      |
      v
canonical bytes unchanged
```

必须满足：

```text
pack(restore(pack(bin))) == pack(bin)
```

临时 round-trip 目录不能复用真实 `bin/`，避免测试误删或覆盖 IDB 和二进制。

## Developer Workflow

正常修改 finder、config、reference 或公共 analyzer 逻辑时：

```text
modify analysis code/config
        |
        v
run analysis for affected game version
        |
        v
strict pack candidate exactly once
        |
        v
update_gamedata from candidate
        |
        v
run C++ validation from candidate
        |
        v
publish the same candidate bytes
        |
        v
commit code + snapshot in the same PR
```

规则：

- 会改变正式 symbol 输出的 PR 必须同时更新 snapshot。
- snapshot 没有变化是允许的，但 CI 必须重新运行所有被代码修改影响的 producers，以证明结果确实不变。
- CI 不自动修复普通 PR 的 snapshot。
- snapshot 更新应与产生它的代码/config/reference 修改处于同一 PR。

## PR Self-Runner Validation Model

`pr-self-runner.yml` 必须验证：

```text
PR tracked gamesymbols/<GAMEVER>.yaml
        ==
current PR code executed against real binaries
```

### Trust Boundaries

- base snapshot：确定性的分析缓存基线。
- head snapshot：PR 声明的期望结果，只读、待验证。
- persisted binaries/IDBs：性能缓存，可以使用。
- persisted YAML：不可信性能缓存，不能直接作为 PR 分析起点。

### Self-Validation Loop To Avoid

禁止以下流程：

```text
restore PR head snapshot into bin
        |
        v
run analyzer, all outputs already exist and are skipped
        |
        v
compare bin with the same PR snapshot
```

该流程只证明 snapshot 与自身一致，不能证明 finder 或 preprocessor 能产生它。

### Deterministic PR Flow

PR checkout 使用 merge ref，但 base 必须固定为事件中的 `pull_request.base.sha`，不能依赖 merge commit 父提交顺序。
base commit 中的 `gamesymbols/*.yaml` 为唯一可信选择来源：0 个表示 bootstrap；PR game version 已存在时使用同名 snapshot；仅有 1 个时直接使用；否则使用 base 历史中最近一次发布的 snapshot。不得按文件名排序或通过 `download.yaml` 推断。

PR head `download.yaml` 的最新版本只用于优先选择同名 base snapshot，不是默认 validation target。只要选中了
base snapshot，`VALIDATION_GAMEVER` 就固定为该 snapshot 的文件名版本；persisted bin copy、restore、
invalidation、analyzer、candidate compare、gamedata 和 C++ tests 必须全部使用这个版本。这样 PR self-runner
验证的是 head `config.yaml`、preprocessor、Agent skill 和相关源码改动能否在最后一个可信 base snapshot 上
产生合规结果，而不是提前构建尚未被接受的新 game version。

推荐步骤：

1. Checkout PR merge ref。
2. 从 head `download.yaml` 读取 `PR_GAMEVER`，仅作为 base snapshot 同名优先选择提示。
3. 枚举 `pull_request.base.sha` 中的 `gamesymbols/*.yaml`，按上述规则选择 base snapshot。
4. 从该 snapshot 最后发布的 commit 提取匹配的 base `config.yaml`，从 `base.sha` 提取 snapshot 原始字节。
5. 有 base snapshot 时令 `VALIDATION_GAMEVER=BASE_GAMEVER`；bootstrap 时才使用 `PR_GAMEVER`。
6. 将 persisted workspace 的 `bin/<VALIDATION_GAMEVER>` 复制到 workspace 内的真实目录，保留 DLL 和 SO；`bin` 不得是 junction 或 symlink。
7. 使用 base config 和 base snapshot 对 `bin/<VALIDATION_GAMEVER>` 执行 `restore -replace`。
8. 从 `HEAD` 导出同版本 snapshot 原始 Git blob，比较 base config/snapshot 与 head config/snapshot，并读取 PR changed files；不得使用可能被 checkout 行尾转换的工作区 snapshot 字节。
9. 计算需要 invalidation 的 producers 和传递依赖闭包。
10. 删除所有 invalidated skills 的 required 和 optional outputs，以及 head config 已移除的 base output paths。
11. 运行 Python unit tests。
12. 对 `VALIDATION_GAMEVER` 运行 `ida_analyze_bin.py`。
13. 构建 actual candidate，并与 head 中 `gamesymbols/<VALIDATION_GAMEVER>.yaml` 比较。
14. 使用该 candidate 运行 `update_gamedata.py` 和 `run_cpp_tests.py`。

流程图：

```text
base.sha snapshot + base.sha config
              |
              v
select VALIDATION_GAMEVER from base snapshot
              |
              v
restore deterministic base into bin/<VALIDATION_GAMEVER>
              |
              v
invalidate snapshot/config/source-code affected outputs
              |
              v
run analyzer
              |
              v
pack actual result in memory
              |
              v
compare with PR head snapshot + round-trip
              |
              v
update gamedata + C++ validation
```

### Persisted Workspace Behavior

当前 PR workflow 会复制 persisted `bin/<GAMEVER>`。迁移后：

- `.github/workflows/build-on-self-runner.yml` 也必须停止把 workspace `bin` 通过 `mklink` 映射到 `PERSISTED_WORKSPACE/bin`，改为像 PR workflow 一样复制所需的 `bin/<GAMEVER>` 到 workspace 的真实目录；`cs2_depot` 可以继续使用 persisted link。
- 新 game version 尚无 persisted `bin/<GAMEVER>` 时，build workflow 应创建空的 workspace 版本目录，再由 depot copy 和 analyzer 填充。
- 可以继续复制二进制和 IDB。
- 复制过来的 YAML 必须在恢复 base snapshot 前删除，而且删除动作只能作用于 workspace 副本。
- persisted YAML 不能决定 analyzer 是否 skip。
- 任何 YAML 清理或 snapshot restore 前都必须拒绝 linked/reparse-point `bin`，并验证目标路径仍位于当前 workspace。
- PR validation 成功并合并后，可以把已验证的实际 YAML 回写 persisted workspace。
- 回写只能发生在 snapshot verification 和完整 validation 成功之后。
- build workflow 如需保留现有缓存语义，只能在完整 validation 成功后显式回写需要持久化的 binaries、IDB 和 YAML；失败或取消不得改写 persisted `bin`。

## Invalidation Design

仅比较 snapshot delta 不足以验证 PR。必须同时考虑 snapshot、config 和分析代码变化。

### Snapshot Delta

```python
added = head_paths - base_paths
deleted = base_paths - head_paths
modified = {
    path
    for path in base_paths & head_paths
    if base_files[path] != head_files[path]
}
```

`added | deleted | modified` 是第一组 invalidation seeds。

### Invalidate Whole Producer Outputs

不能只删除发生变化的单个 path。

如果一个 skill 产生多个 required/optional outputs，只删除其中一个 optional output 可能仍会让 analyzer 因 required outputs 全部存在而 skip。因此一旦一个 output path 被 invalidated：

- 找到所有 owner skills。
- 删除这些 skills 的全部 required outputs。
- 删除这些 skills 当前存在的全部 optional outputs。

### Config Delta

base/head config 比较应识别：

- 新增、删除或修改的 skill。
- output/input path 变化。
- platform gate 变化。
- prerequisite 变化。
- skip behavior 变化。
- module binary path 或 stage 变化。

受影响 skill 的全部 outputs 进入 invalidation seeds。

### Source Change Mapping

CI 必须防止以下假阳性：

```text
finder changed
snapshot unchanged
base output exists
analyzer skips
verify passes
```

因此 changed files 必须映射到 producer：

- `ida_preprocessor_scripts/find-*.py`
  - invalidate 对应 config skill outputs。
- `.claude/skills/<skill>/**`
  - invalidate 对应 Agent fallback skill outputs。
- `ida_preprocessor_scripts/references/**/*.yaml`
  - invalidate 所有引用该 reference 的 LLM_DECOMPILE skills。
- 被多个 finder import 的公共 helper
  - invalidate 所有直接和传递调用方。
- `ida_analyze_util.py`、`ida_skill_preprocessor.py`、核心 analyzer output writer 等无法安全局部映射的变化
  - 采用 fail-safe 扩大范围，可重建所有 modules。

如果 changed analysis file 无法可靠映射，默认行为必须是扩大重建范围，不能静默复用 base outputs。

纯 docs、frontend 或与 analysis 无关的文件变化不需要 invalidation。

### Dependency Closure

在 initial invalidation seeds 之后，必须按 artifact producer/consumer graph 计算传递闭包：

```text
A.yaml changed
    -> producer A invalidated
    -> consumer B uses A.yaml as expected_input
    -> producer B invalidated
    -> all B outputs removed
    -> continue transitively
```

依赖图应复用 analyzer 当前语义：

- `expected_output -> expected_input`。
- platform-specific input/output。
- legacy `prerequisite`。
- 合法 cross-module artifact path。
- 重复 module stages。

graph 必须以解析后的完整 artifact path 为连接依据，不能只按 basename 匹配。

### Deleted Outputs

head config 或 head snapshot 删除的 path 必须从 restored base 中删除，即使 head 中已经没有 producer。否则 stale YAML 会残留在 `bin`。

## Snapshot Verification In PR

analysis 完成后，CI 对 head snapshot 执行 strict verify。

必须失败的情况：

- PR 缺少 `gamesymbols/<GAMEVER>.yaml`。
- snapshot game version 不匹配。
- snapshot config digest 过期。
- required output 缺失。
- actual 存在 snapshot 未包含的正式 optional output。
- snapshot 包含 actual 未产生的 optional output。
- 任一 payload 不一致。
- actual 产生 undeclared YAML。
- snapshot 非 canonical。
- round-trip 不稳定。

CI 只输出 mismatch，不自动运行 `pack` 覆盖用户提交。

## Full Validation And Publication Timing (Superseded)

本节原有的 validation 后 pack 时序已被 candidate-first transaction boundary supersede。当前时序为：

```text
Analyze all selected binaries successfully
        |
        v
Strict pack immutable candidate exactly once
        |
        v
Update all downstream gamedata from candidate
        |
        v
Run C++ tests from the same candidate
        |
        v
Publish the same raw candidate bytes
```

普通开发 PR 中，开发者本地按该顺序生成并发布 expected snapshot；PR CI 在 runner temp 重建 actual candidate，
与 head expected snapshot 比较后驱动 downstream，不 publish tracked 文件。

正式 build workflow 在 analysis 后立即 build candidate，并且只在两个 consumer 成功后执行 byte-preserving publish。

不应在每个 skill、module 或 platform 完成后重写 snapshot：

- 中间结果不是完整快照。
- 会产生频繁大文件 I/O。
- 并行或分阶段执行时可能发生竞争。
- 后续 validation 仍可能失败。

## New Game Version Exception

当前自动版本流程是：

```text
bump-download PR merged
        |
        v
tag-bump-after-merge creates tag
        |
        v
build-on-self-runner runs analysis
```

因此，新版本的正式 analysis 当前发生在 tag commit 已固定之后。新版本无法像普通 PR 一样在原始 bump PR 中天然包含 snapshot。

### Phase 1: Minimal Workflow Change

短期采用 follow-up snapshot PR：

1. bump-download PR 合并并创建 tag。
2. build-on-self-runner 完成新版本 analysis、gamedata 和 C++ tests。
3. 成功后执行一次 `pack`，生成 `gamesymbols/<NEW_GAMEVER>.yaml`。
4. bot 创建 `gamesymbols/<NEW_GAMEVER>` 分支和 follow-up PR。
5. build workflow 自身完成新版本完整 candidate validation，并创建 generated-output PR。
6. generated-output PR 由专用轻量校验处理；普通 PR self-runner 继续验证最后一个可信 base snapshot 版本。

该阶段保持现有 tag/build 时序，breaking changes 最小，但 game version tag 指向的 commit 不包含对应 snapshot。

### Phase 2: Tag Contains Snapshot

如果未来要求 game version tag 自身包含 snapshot，则必须改为：

```text
create bump PR
    -> analyze on PR
    -> generate and commit snapshot into PR
    -> validate snapshot
    -> merge PR
    -> create game version tag
    -> publish release
```

该方案架构更完整，但需要重构当前 post-merge analysis 状态机，不作为第一阶段前置条件。

## Release Artifacts

tracked snapshot 是 canonical Git 状态，Release artifact 是可选的分发优化，两者不冲突。

可以继续发布：

```text
gamesymbol-<GAMEVER>.7z
```

archive 可以包含：

```text
gamesymbols/<GAMEVER>.yaml
```

或恢复后的：

```text
bin/<GAMEVER>/**/*.yaml
```

但 Release 不是 PR validation 的事实来源。Git tracked snapshot 才是 review 和 deterministic base 的来源。

## Implementation Structure

建议文件变化：

- Add: `gamesymbol_snapshot.py`
  - config contract 解析。
  - 正式 output set 构造。
  - canonical YAML encode/decode。
  - `pack`、`restore`、`verify`。
  - semantic diff 和 round-trip。
- Add: `gamesymbol_pr_validation.py`
  - 加载 base/head config 和 snapshot。
  - 解析 changed files。
  - 构造 producer/consumer graph。
  - 计算 invalidation closure。
  - 删除 invalidated outputs。
- Add: `tests/test_gamesymbol_snapshot.py`
  - snapshot schema、正式集合、CLI、restore 和 round-trip tests。
- Add: `tests/test_gamesymbol_pr_validation.py`
  - snapshot/config/source diff 和 dependency closure tests。
- Modify or remove: `prune_pr_expected_output_bin.py`
  - snapshot-aware invalidation 完成后，现有“仅删除 PR 新增 expected_output”逻辑不再足够。
  - 可以先复用其 config path expansion helper，再由新脚本替代 workflow 调用。
- Modify: `.github/workflows/pr-self-runner.yml`
  - restore base snapshot。
  - invalidate affected outputs。
  - analysis 后 verify head snapshot。
- Modify: `.github/workflows/build-on-self-runner.yml`
  - 保留 persisted `cs2_depot` link，但移除 workspace `bin` 到 `PERSISTED_WORKSPACE/bin` 的 `mklink`。
  - 复制 persisted `bin/<GAMEVER>` 到 workspace 的真实目录，并允许新版本从空目录开始。
  - 完整 validation 成功后再显式回写需要保留的缓存，避免 workspace YAML 清理直接修改 persisted workspace。
  - 新版本完整 validation 后生成一次 snapshot。
  - 第一阶段可创建 follow-up snapshot PR。
- Modify: `format_repo_files.py`
  - 跳过 `gamesymbols/` generated YAML。
- Modify: `README.md`
  - 记录 pack/restore/verify 和 PR snapshot 规则。
- Add: `gamesymbols/<BOOTSTRAP_GAMEVER>.yaml`
  - 初始 baseline snapshot。

## Test Plan

### Formal Set Tests

- required `expected_output` 被收集。
- `expected_output_windows` 和 `expected_output_linux` 只进入对应平台。
- module 缺少 platform binary path 时不产生该平台输出。
- platform-pinned skill 不产生另一平台输出。
- optional output 存在时进入 snapshot，不存在时允许。
- repeated module stage 的 path 被去重但 owner 被保留。
- 合法 cross-module output 被规范化。
- game version root path escape 被拒绝。
- case-insensitive path collision 被拒绝。
- non-YAML expected output 不进入 gamesymbol snapshot。
- undeclared YAML 在 strict mode 下失败。

### Pack Tests

- missing required output 失败。
- unreadable YAML 失败。
- top-level non-mapping YAML 失败。
- output ordering 在不同文件创建顺序下保持一致。
- metadata 和 file count 正确。
- pack 使用临时文件和 atomic replace。
- pack 失败不修改已有 snapshot。

### Restore Tests

- 默认 restore 创建缺失文件。
- 默认 restore 跳过语义相同文件。
- 默认 restore 拒绝覆盖不同文件。
- `-replace` 只删除 YAML。
- `-replace` 保留 DLL、SO、I64 和 IDA database files。
- snapshot path traversal 被拒绝。
- snapshot game version mismatch 被拒绝。
- restore 后 payload 与 snapshot 一致。

### Verify And Round-Trip Tests

- exact actual/snapshot 返回成功。
- added、missing、modified path 分别失败并产生可读报告。
- non-canonical snapshot 失败。
- config digest mismatch 失败。
- `pack(restore(snapshot))` byte-stable。
- `pack(restore(pack(bin)))` byte-stable。

### PR Invalidation Tests

- base/head snapshot added path invalidates owner。
- deleted path 从 restored base 删除。
- modified path invalidates owner 全部 outputs。
- optional output 变化仍会删除 owner required outputs，强制 skill 重跑。
- config skill 修改 invalidates 对应 outputs。
- preprocessor script 修改但 snapshot 未变时仍 invalidates owner。
- reference YAML 修改 invalidates consumers。
- shared helper 修改 invalidates direct/transitive users。
- unknown core analysis change 触发 fail-safe broad rebuild。
- downstream artifact consumer closure 被完整计算。
- basename 相同但 module 不同的 artifacts 不互相污染。

### Workflow Tests

- PR workflow 从 `pull_request.base.sha` 的 snapshot 集合选择 base snapshot，不恢复 head snapshot，也不按文件名排序。
- persisted YAML 在分析前被清除。
- analyzer 在 snapshot verify 之前运行。
- snapshot verify 在 gamedata/C++ validation 之前或紧接 analysis 之后运行。
- snapshot mismatch 使 workflow 失败。
- ordinary PR workflow 不修改 tracked snapshot。
- PR/build workflow 的 workspace `bin` 是真实目录；清理 workspace YAML 不会修改 persisted `bin`。
- build workflow 失败或取消时不回写 workspace `bin` 到 persisted workspace。
- build workflow 只在完整 validation 成功后生成新版本 snapshot。

## Rollout Plan

### Step 1: Snapshot Core

- 实现正式 output set collector。
- 实现 schema、canonical writer 和 parser。
- 实现 `pack`、`restore`、`verify`。
- 实现 round-trip tests。

### Step 2: Bootstrap Baseline

- [x] 对当前完整且已验证的 game version `14168` 运行 `pack`。
- [x] 清理现有 undeclared YAML。
- [x] 生成第一个 `gamesymbols/14168.yaml`。
- [x] 修改 formatter 跳过 snapshot。

### Step 3: PR Deterministic Base

- 修改 PR workspace 准备逻辑，保留 binaries/IDBs 但清除 YAML。
- 从 `pull_request.base.sha` 选择并恢复 base snapshot。
- 初期可先基于 snapshot/config delta 做 invalidation。
- analysis 后 strict pack actual candidate，再与 head snapshot compare。

### Step 4: Source-Aware Invalidation

- 增加 preprocessor、Agent SKILL、reference 和 helper changed-file mapping。
- 增加 dependency closure。
- 对无法映射的核心变化使用 broad rebuild。
- 替换现有 `prune_pr_expected_output_bin.py` workflow 入口。

### Step 5: New Version Automation

- build workflow analysis 后 pack candidate 一次，完整 validation 后原字节 publish。
- 自动创建 follow-up snapshot PR。
- 后续再决定是否把 analysis 前移，使 tag commit 包含 snapshot。

## Acceptance Criteria

- `bin/` 保持 ignored，Git 不跟踪 per-symbol YAML。
- `gamesymbols/<GAMEVER>.yaml` 使用完整 `module/filename` key。
- snapshot 文件集合由 config contract 推导。
- 所有 required YAML 缺失都会使 pack/verify 失败。
- optional YAML 存在时被跟踪，不存在时允许。
- undeclared YAML 不会被静默收入 snapshot。
- `pack` 在同一输入上重复运行产生相同字节。
- `restore -replace` 不影响任何 binary 或 IDA database file。
- `verify` 强制执行 round-trip。
- 普通 PR 修改分析结果但未更新 snapshot 时失败。
- 普通 PR 错误更新 snapshot 时失败。
- 修改 finder 但忘记更新 snapshot 时，CI 会重新运行对应 producer，并在实际输出变化时失败。
- persisted runner YAML 无法让未执行的 finder 获得假阳性。
- 删除 workspace 当前 game version 下的 YAML 不会删除或改写 `PERSISTED_WORKSPACE/bin` 中的文件。
- 上游 artifact 变化会传递 invalidation 到下游 consumers。
- 普通 PR CI 不自动改写 tracked snapshot。
- analysis transaction 只 strict pack 一次 candidate，正式 snapshot 只在完整 validation 成功后原字节 publish。

## Final Architecture

```text
config.yaml + preprocessors + Agent SKILLs + references
                         |
                         v
                 ida_analyze_bin.py
                         |
                         v
          bin/<GAMEVER>/**/*.yaml (ignored)
                         |
                         v
              strict pack candidate
                         |
             +-----------+-----------+
             |                       |
             v                       v
      update_gamedata             C++ tests
             |                       |
             +-----------+-----------+
                         |
                         v
               full validation success
                         |
                         v
       gamesymbols/<GAMEVER>.yaml (same bytes)
                         |
          +--------------+----------------+
          |              |                |
          v              v                v
   restore baseline  PR expected     reproducibility
```

该设计将 `bin` 限定为 analyzer mutable workspace，将 candidate 定义为唯一 downstream Symbol Store，并将
`gamesymbols/<GAMEVER>.yaml` 定义为 validation-approved candidate 原始字节形成的 analysis lockfile。
