#!/usr/bin/env python3
"""Preprocess script for find-CInputService_ProcessConVar-decompiles skill."""

from ida_analyze_util import preprocess_common_skill

TARGET_FUNCTION_NAMES = [
    "INetworkClientService_IsPutInServer",
]

# Windows: the FCVAR_CLIENTCMD_CAN_EXECUTE gate (and with it the
# INetworkClientService::IsPutInServer vcall) is inlined directly into
# CInputService::ProcessConVar.
LLM_DECOMPILE_WINDOWS = [
    {
        "symbol_name": "INetworkClientService_IsPutInServer",
        "prompt_path": "prompt/call_llm_decompile.md",
        "reference_yaml_paths": [
            "references/engine/CInputService_ProcessConVar.{platform}.yaml",
        ],
        "expected_result_sections": ["found_vcall"],
        "dependency_policy": {
            "CInputService_ProcessConVar.{platform}.yaml": "required",
        },
    },
]

# Linux: that same gate is emitted as a shared out-of-line helper, so the vcall
# is NOT present in ProcessConVar's own body -- decompile the helper instead.
LLM_DECOMPILE_LINUX = [
    {
        "symbol_name": "INetworkClientService_IsPutInServer",
        "prompt_path": "prompt/call_llm_decompile.md",
        "reference_yaml_paths": [
            "references/engine/CInputService_IsClientOnlyCommandAllowed.{platform}.yaml",
        ],
        "expected_result_sections": ["found_vcall"],
        "dependency_policy": {
            "CInputService_IsClientOnlyCommandAllowed.{platform}.yaml": "required",
        },
    },
]

FUNC_VTABLE_RELATIONS = [
    # (func_name, vtable_class)
    ("INetworkClientService_IsPutInServer", "INetworkClientService"),
]

GENERATE_YAML_DESIRED_FIELDS = [
    # (symbol_name, generate_yaml_fields)
    # Slim Pattern C: INetworkClientService is an abstract interface class with
    # no concrete body in engine to sign, and it is not a downstream predecessor.
    (
        "INetworkClientService_IsPutInServer",
        [
            "func_name",
            "vfunc_sig",  # REQUIRED for Pattern C
            "vfunc_offset",
            "vfunc_index",
            "vtable_name",
        ],
    ),
]


async def preprocess_skill(
    session,
    skill_name,
    expected_outputs,
    old_yaml_map,
    new_binary_dir,
    platform,
    image_base,
    llm_config=None,
    debug=False,
):
    """Locate INetworkClientService_IsPutInServer vfunc slot via LLM decompile of the platform predecessor."""
    llm_decompile = LLM_DECOMPILE_WINDOWS if platform == "windows" else LLM_DECOMPILE_LINUX
    return await preprocess_common_skill(
        session=session,
        expected_outputs=expected_outputs,
        old_yaml_map=old_yaml_map,
        new_binary_dir=new_binary_dir,
        platform=platform,
        image_base=image_base,
        func_names=TARGET_FUNCTION_NAMES,
        func_vtable_relations=FUNC_VTABLE_RELATIONS,
        llm_decompile_specs=llm_decompile,
        llm_config=llm_config,
        generate_yaml_desired_fields=GENERATE_YAML_DESIRED_FIELDS,
        debug=debug,
    )
