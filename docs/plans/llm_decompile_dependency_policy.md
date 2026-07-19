# LLM Decompile Dependency Policy

## Status

Proposed atomic migration.

本计划将 `LLM_DECOMPILE` 依赖改为强制、显式、可静态审计的
`dependency_policy`。每个 reference YAML 对应的当前版本 artifact 必须分类为
`required` 或 `optional`，不再支持隐式依赖类型、`dependencies: []` 或正式的纯 IDA
名称查找依赖。

迁移必须一次完成：分析器 schema、config schema、调度器、全部预处理脚本和 unittest
必须同步更新，默认分支不保留双 schema 兼容期。

## Problem

当前实现从 `reference_yaml_paths` 的 `func_name` 推导 artifact，允许 `dependencies`
覆盖，其中空列表表示不要求 artifact。该模型无法区分：

- optional helper；
- prerequisite 后的 IDA 名称；
- 同一次 preprocess 刚生成的 artifact；
- 无意漏写的依赖。

config 只有 `expected_input`，没有 optional artifact 对应的 `optional_input`。unittest
因此无法证明依赖集合完整，也无法检查 required/optional 分类和 config 是否一致。

## Decision

每个 LLM spec 必须声明完整 policy：

```python
LLM_DECOMPILE = [
    {
        "symbol_name": "TargetSymbol",
        "prompt_path": "prompt/call_llm_decompile.md",
        "reference_yaml_paths": [
            "references/server/RequiredAnchor.{platform}.yaml",
            "references/server/OptionalHelper.{platform}.yaml",
        ],
        "expected_result_sections": ["found_call"],
        "dependency_policy": {
            "RequiredAnchor.{platform}.yaml": "required",
            "OptionalHelper.{platform}.yaml": "optional",
        },
    },
]
```

只允许：

- `required`：必须声明在 `expected_input`，运行时缺失即失败。
- `optional`：必须声明在 `optional_input`；存在时验证并使用，缺失时不在输入预检失败。

不增加 `runtime`。同一次 preprocess 内的 artifact 链必须拆分；可选 helper 使用
`optional`；稳定 producer 使用 `required`。IDA 名称查找可以保留为地址解析的内部
fallback，但不能替代依赖契约。

自动推导只用于验证 policy 是否完整，不再决定依赖类型。

## Invariants

1. 每个 LLM spec 必须包含非空 `dependency_policy` mapping。
2. policy value 只允许 `required` 或 `optional`。
3. 从全部 reference YAML `func_name` 推导出的 artifact 集合必须与 policy keys 完全相等。
4. 每个 artifact 必须恰好分类一次，不能漏项或多项。
5. required artifact 必须位于对应平台 `expected_input`。
6. optional artifact 必须位于对应平台 `optional_input`。
7. 同一 artifact 不得同时出现在 required 和 optional config input。
8. 每个依赖必须有唯一、平台兼容的 producer skill。
9. skill 不得依赖自己的 output；发现内部 artifact 链必须拆分。
10. required 和 optional input 都建立 producer 到 consumer 的调度边。
11. required input 缺失是硬失败；optional input 缺失不阻止 consumer 运行。
12. 已存在的 optional artifact 使用与 expected input 相同的有效性检查。
13. 最终 schema 删除 `dependencies` 和 `optional_dependencies`。

## Artifact Derivation

对每个 reference：

1. 解析 `{platform}` 和 `{module_name}`；
2. 读取 YAML 顶层 `func_name`；
3. 推导 `<func_name>.{platform}.yaml`；
4. 对多个 reference 结果去重；
5. 与 policy keys 做严格集合比较。

policy key 使用 artifact basename。config 仍可使用 `../engine/Foo.{platform}.yaml` 等
相对路径；校验时按解析后的 basename 查找，且必须唯一匹配，零匹配或多匹配均失败。

## Config Schema and Scheduling

config 新增：

```yaml
expected_input:
  - RequiredAnchor.{platform}.yaml
optional_input:
  - OptionalHelper.{platform}.yaml
expected_input_windows: []
expected_input_linux: []
optional_input_windows: []
optional_input_linux: []
```

平台字段与现有 `expected_input_<platform>` 使用相同的合并、去重和路径展开规则。

调度和预检语义：

- required/optional input 都加入 artifact producer 图和循环检测；
- optional edge 使用独立的 `EdgeType.OPTIONAL_INPUT`；
- optional producer 尝试完成后再运行 consumer，即使没有生成文件；
- required input 必须存在并通过 artifact validation；
- optional input 存在时必须通过相同 validation，不存在时记录但不失败；
- preprocessor 接收 `_expected_inputs` 和 `_optional_inputs` 两组已解析声明路径；
- 仅用于 artifact 排序的旧 `prerequisite` 应由 required/optional input 替代。

`prerequisite` 只保留给无法由 artifact 表达的非数据顺序约束。

## LLM Validation

`ida_analyze_util.py` 必须在 fast path 和 LLM 请求前：

1. 强制 policy 存在且拒绝旧 `dependencies` 字段；
2. 校验 key/value 类型和允许值；
3. 推导 reference artifact 集合并与 policy 严格比较；
4. 将 required policy 与 `_expected_inputs` 对照；
5. 将 optional policy 与 `_optional_inputs` 对照；
6. 检查 config input 无重叠、无 basename 歧义；
7. 失败时报告 symbol、artifact、policy 和缺失的 config 字段。

## Required Split: ExecuteQueuedDeletion

删除组合脚本：

```text
ida_preprocessor_scripts/
  find-CEntitySystem_QueueDestroyEntity-AND-CEntitySystem_ExecuteQueuedDeletion-decompiles.py
```

当前脚本混合了以下链：

```text
CEntitySystem_QueueDestroyEntity
  -> CEntitySystem_ExecuteQueuedDeletion
  -> CEntitySystem_m_nExecuteQueuedDeletionDepth
```

第二个目标依赖同一次调用刚生成的第一个 artifact，因此必须拆成两个 skill。

### Skill 1: ExecuteQueuedDeletion

新增 `ida_preprocessor_scripts/find-CEntitySystem_ExecuteQueuedDeletion.py`，只生成
`CEntitySystem_ExecuteQueuedDeletion.{platform}.yaml`：

```python
LLM_DECOMPILE = [
    {
        "symbol_name": "CEntitySystem_ExecuteQueuedDeletion",
        "prompt_path": "prompt/call_llm_decompile.md",
        "reference_yaml_paths": [
            "references/server/CEntitySystem_QueueDestroyEntity.{platform}.yaml",
        ],
        "expected_result_sections": ["found_call"],
        "dependency_policy": {
            "CEntitySystem_QueueDestroyEntity.{platform}.yaml": "required",
        },
    },
]
```

```yaml
- name: find-CEntitySystem_ExecuteQueuedDeletion
  expected_output:
    - CEntitySystem_ExecuteQueuedDeletion.{platform}.yaml
  expected_input:
    - CEntitySystem_QueueDestroyEntity.{platform}.yaml
```

### Skill 2: ExecuteQueuedDeletionDepth

新增 `ida_preprocessor_scripts/find-CEntitySystem_m_nExecuteQueuedDeletionDepth.py`，只生成
`CEntitySystem_m_nExecuteQueuedDeletionDepth.{platform}.yaml`：

```python
LLM_DECOMPILE = [
    {
        "symbol_name": "CEntitySystem_m_nExecuteQueuedDeletionDepth",
        "prompt_path": "prompt/call_llm_decompile.md",
        "reference_yaml_paths": [
            "references/server/CEntitySystem_ExecuteQueuedDeletion.{platform}.yaml",
        ],
        "expected_result_sections": ["found_struct_offset"],
        "dependency_policy": {
            "CEntitySystem_ExecuteQueuedDeletion.{platform}.yaml": "required",
        },
    },
]
```

```yaml
- name: find-CEntitySystem_m_nExecuteQueuedDeletionDepth
  expected_output:
    - CEntitySystem_m_nExecuteQueuedDeletionDepth.{platform}.yaml
  expected_input:
    - CEntitySystem_ExecuteQueuedDeletion.{platform}.yaml
```

迁移必须更新所有旧 skill 名称引用、测试 fixture、报告期望和 config 顺序，并确认旧组合
skill 名称无残留。两个新 skill 必须可以独立运行、失败和重试。

## Existing Exception Migration

- optional de-inline helper：使用 `optional` policy，并增加 `optional_input`。
- ExecuteQueuedDeletion 内部链：按上一节拆分，两个依赖均为 `required`。
- `INetworkClientService_IsActive`：Windows required
  `CNetworkGameServerBase_ServerSimulate`；Linux required
  `CNetworkGameServerBase_ServerSimulateInternal`，使用平台专用 input。
- 稳定 producer：使用 `required`，不得继续依赖 config 顺序或 IDA 名称。
- 多 reference spec 可以同时包含 required 和 optional policy。

仅用于 optional artifact producer 排序的 `prerequisite` 应由 `optional_input` 替代。

## Implementation Areas

- `ida_analyze_bin.py`：解析 optional input、建立调度边、执行 optional preflight 和报告。
- `ida_skill_preprocessor.py`：传递 `_optional_inputs`。
- `ida_analyze_util.py`：实现 policy schema、严格集合校验和 config 对照，删除旧推导覆盖逻辑。
- `configs/*.yaml`：补齐 optional/platform input，拆分 ExecuteQueuedDeletion skill。
- `ida_preprocessor_scripts/*.py`：全部改为显式 policy，删除全部 `dependencies`。
- `tests/`：覆盖 schema、调度、preflight、仓库审计和拆分 skill。

## Test Plan

必须覆盖：

- 缺少 policy、非法 policy、旧字段、少项或多项均失败；
- required 缺少 expected input、optional 缺少 optional input 均失败；
- required/optional 重叠、跨模块歧义、平台错配均失败；
- optional input 缺失不硬失败，存在但无效时失败；
- optional producer 始终先于 consumer；
- self-dependency 和 required/optional cycle 被拒绝；
- repository audit 遍历全部 LLM specs，验证 reference、policy、config 和 producer；
- repository audit 断言旧 `dependencies` 和旧组合 skill 名称不存在；
- 两个 ExecuteQueuedDeletion 新 skill 的 target、policy、config 边和独立运行行为正确。

完成验证：

```powershell
uv run ruff format <changed-python-files>
uv run ruff check <changed-python-files>
uv run yamlfix <changed-config-files>
uv run python -m unittest discover -s tests -b
git diff --check
```

## Migration Order

1. 增加失败的 schema、optional input、scheduler 和 repository-audit tests。
2. 实现 config optional input 调度与 preflight。
3. 实现 dependency policy 规范化和严格校验。
4. 拆分 ExecuteQueuedDeletion 组合 skill。
5. 迁移全部 LLM specs、config 和 artifact prerequisite。
6. 删除旧 dependency 实现和兼容测试。
7. 运行完整质量门禁。

## Acceptance Criteria

- 所有 LLM spec 都包含完整 policy，且只使用 `required`/`optional`。
- 所有 reference artifact 被恰好分类一次。
- config 正确支持、调度并验证 `optional_input`。
- 仓库不存在旧 `dependencies` schema。
- ExecuteQueuedDeletion 组合脚本被两个独立 skill 替代。
- repository audit 能发现漏写 policy、input、producer 和平台映射。
- 完整 unittest、Ruff、YAML 格式检查和 `git diff --check` 全部通过。
