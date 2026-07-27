[返回中文 README](../../README_CN.md) | [English](../en/reference-yaml.md)

# `LLM_DECOMPILE` reference YAML

reference YAML 存放在：

```text
ida_preprocessor_scripts/references/<module>/<func_name>.<platform>.yaml
```

## 准备步骤

1. 确认目标函数已有包含 `func_va` 的当前版本 YAML，或可通过 `configs/<GAMEVER>.yaml` 中的 symbol name 或 alias 在 IDA 中定位。
2. 选择以下任一入口生成 reference YAML：

   - 独立 CLI：

   ```bash
   uv run generate_reference_yaml.py -gamever 14141 -module engine -platform windows -func_name CNetworkGameClient_RecordEntityBandwidth -mcp_host 127.0.0.1 -mcp_port 13337
   ```

   - 替代方案：使用 `generate-reference-yaml` Skill（`SKILL: generate-reference-yaml`）。在支持 Skill 的 Agent 中运行：

     ```text
     Run SKILL: .claude/skills/generate-reference-yaml/SKILL.md
     ```

     传入相同的必需参数 `func_name`、`gamever`、`module` 和 `platform`。该 Skill 使用相同的 CLI，并支持连接已有 MCP 或自动启动 `idalib-mcp`。

   如需通过 CLI 自动启动 `idalib-mcp`：

   ```bash
   uv run generate_reference_yaml.py -gamever 14141 -module engine -platform windows -func_name CNetworkGameClient_RecordEntityBandwidth -auto_start_mcp -binary bin/14141/engine/engine2.dll
   ```

3. 检查生成的 YAML：

   - `func_va` 可信。
   - `disasm_code` 非空且与目标函数语义匹配。
   - `procedure` 在可用时与预期语义一致；Hex-Rays 不可用时允许为空。
   - `func_name` 只能确认输出文件对应请求的 canonical name，不能单独证明地址解析正确。

4. 将文件接入目标 `find-*.py` 的 `LLM_DECOMPILE` 配置：

   - 仓库路径：`ida_preprocessor_scripts/references/<module>/<func_name>.<platform>.yaml`
   - `LLM_DECOMPILE` 中的相对路径：`references/<module>/<func_name>.<platform>.yaml`
   - 每个配置项必须显式声明允许的结果 section：

     ```python
     {
         "symbol_name": "INetworkMessages_FindNetworkGroup",
         "prompt_path": "prompt/call_llm_decompile.md",
         "reference_yaml_paths": [
             "references/engine/CNetworkGameClient_RecordEntityBandwidth.{platform}.yaml",
         ],
         "expected_result_sections": ["found_vcall"],
         "dependency_policy": {
             "CNetworkGameClient_RecordEntityBandwidth.{platform}.yaml": "required",
         },
     }
     ```

合法 section 包括 `found_call`、`found_vcall`、`found_funcptr`、`found_gv` 和 `found_struct_offset`。

同一 symbol 需要多个 reference 时，应写入同一个 `reference_yaml_paths` 列表，不要重复声明 spec。每个 reference artifact 都必须在 `dependency_policy` 中有对应项，值为 `required` 或 `optional`；`required` artifact 必须属于 expected-input 集合，`optional` artifact 必须属于 optional-input 集合。

可选字段 `instruction_rules` 和 `expected_size` 用于增加结果约束。`instruction_rules` 是非空的 `{regex, text}` 对象列表：正则表达式会对 LLM 返回的指令做完整匹配，`text` 用于说明允许的形式。`expected_size` 是仅适用于 `found_struct_offset` 结果的正整数，必须与返回的成员访问大小一致：

```python
{
    "symbol_name": "CNetworkGameServer_ClientList",
    "prompt_path": "prompt/call_llm_decompile.md",
    "reference_yaml_paths": [
        "references/engine/CEngineServer_ClientPrintf.{platform}.yaml",
    ],
    "expected_result_sections": ["found_struct_offset"],
    "instruction_rules": [
        {
            "regex": r"(?i)^cmp\s+(?:e(?:ax|bx|cx|dx|si|di|bp|sp)|r(?:[89]|1[0-5])d)\s*,\s*(?:dword ptr\s+)?\[[^\]]+\]$",
            "text": "cmp reg, [base+offset]",
        },
        {
            "regex": r"(?i)^cmp\s+(?:dword ptr\s+)?\[[^\]]+\]\s*,\s*(?:e(?:ax|bx|cx|dx|si|di|bp|sp)|r(?:[89]|1[0-5])d)$",
            "text": "cmp [base+offset], reg",
        },
    ],
    "expected_size": 4,
    "dependency_policy": {
        "CEngineServer_ClientPrintf.{platform}.yaml": "required",
    },
}
```

`expected_size` 不能用于函数或全局变量目标。`LLM_DECOMPILE` 复用 Analyzer 的共享参数：`-llm_model`、`-llm_apikey`、`-llm_baseurl`、`-llm_temperature`、`-llm_effort` 和 `-llm_fake_as`。
