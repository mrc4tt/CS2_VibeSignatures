[Back to README](../../README.md) | [中文](../zh-CN/reference-yaml.md)

# Reference YAML for `LLM_DECOMPILE`

Reference YAML files are stored at:

```text
ida_preprocessor_scripts/references/<module>/<func_name>.<platform>.yaml
```

## Preparation

1. Confirm the target function already has a current-version YAML with `func_va`, or can be resolved in IDA by symbol name or alias from `configs/<GAMEVER>.yaml`.
2. Generate the reference YAML using either entry point:

   - Standalone CLI:

   ```bash
   uv run generate_reference_yaml.py -gamever 14141 -module engine -platform windows -func_name CNetworkGameClient_RecordEntityBandwidth -mcp_host 127.0.0.1 -mcp_port 13337
   ```

   - Alternative: use the `generate-reference-yaml` Skill (`SKILL: generate-reference-yaml`). In a Skill-capable agent, run:

     ```text
     Run SKILL: .claude/skills/generate-reference-yaml/SKILL.md
     ```

     Provide the same required `func_name`, `gamever`, `module`, and `platform` values. The Skill uses the same CLI and supports both attaching to an existing MCP and auto-starting `idalib-mcp`.

   To auto-start `idalib-mcp` from the CLI, run:

   ```bash
   uv run generate_reference_yaml.py -gamever 14141 -module engine -platform windows -func_name CNetworkGameClient_RecordEntityBandwidth -auto_start_mcp -binary bin/14141/engine/engine2.dll
   ```

3. Check the generated YAML:

   - `func_va` is credible.
   - `disasm_code` is non-empty and matches the target function semantics.
   - `procedure` matches the expected semantics when available. It can be empty when Hex-Rays is unavailable.
   - `func_name` only confirms the output file targets the requested canonical name; it does not prove address-resolution correctness.

4. Wire the file into the target `find-*.py` `LLM_DECOMPILE` specification:

   - Repository path: `ida_preprocessor_scripts/references/<module>/<func_name>.<platform>.yaml`
   - Relative path inside `LLM_DECOMPILE`: `references/<module>/<func_name>.<platform>.yaml`
   - Every entry must explicitly declare its accepted result sections:

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

Valid result sections are `found_call`, `found_vcall`, `found_funcptr`, `found_gv`, and `found_struct_offset`.

Use multiple `reference_yaml_paths` for one symbol instead of repeating the same symbol in multiple specifications. Every referenced artifact must have a matching `dependency_policy` entry whose value is `required` or `optional`; required artifacts belong to the expected-input set, while optional artifacts belong to the optional-input set.

The optional `instruction_rules` and `expected_size` fields add result constraints. `instruction_rules` is a non-empty list of `{regex, text}` objects; the regular expression is matched against the reported instruction with a full match, and `text` describes the accepted form. `expected_size` is a positive integer used only for `found_struct_offset` results and must match the reported member access size:

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

`expected_size` must not be used for function or global-variable targets. `LLM_DECOMPILE` uses the shared Analyzer flags `-llm_model`, `-llm_apikey`, `-llm_baseurl`, `-llm_temperature`, `-llm_effort`, and `-llm_fake_as`.
