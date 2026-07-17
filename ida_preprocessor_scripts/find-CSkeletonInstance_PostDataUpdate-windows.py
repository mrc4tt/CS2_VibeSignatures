#!/usr/bin/env python3
"""Preprocess script for find-CSkeletonInstance_PostDataUpdate-windows skill."""

from ida_analyze_util import preprocess_common_skill

TARGET_FUNCTION_NAMES = [
    "CModelState_SetupJointState",
]

TARGET_STRUCT_MEMBER_NAMES = [
    "CSkeletonInstance_m_modelState_m_hModel",
    "CSkeletonInstance_m_modelState",
]

LLM_DECOMPILE = [
    {
        "symbol_name": "CModelState_SetupJointState",
        "prompt_path": "prompt/call_llm_decompile.md",
        "reference_yaml_paths": [
            "references/client/CSkeletonInstance_PostDataUpdate.{platform}.yaml",
        ],
        "expected_result_sections": ["found_call"],
    },
    {
        "symbol_name": "CSkeletonInstance_m_modelState_m_hModel",
        "prompt_path": "prompt/call_llm_decompile.md",
        "reference_yaml_paths": [
            "references/client/CSkeletonInstance_PostDataUpdate.{platform}.yaml",
        ],
        "expected_result_sections": ["found_struct_offset"],
    },
    {
        "symbol_name": "CSkeletonInstance_m_modelState",
        "prompt_path": "prompt/call_llm_decompile.md",
        "reference_yaml_paths": [
            "references/client/CSkeletonInstance_PostDataUpdate.{platform}.yaml",
        ],
        "expected_result_sections": ["found_struct_offset"],
    },
]

GENERATE_YAML_DESIRED_FIELDS = [
    # (symbol_name, generate_yaml_fields)
    (
        "CModelState_SetupJointState",
        [
            "func_name",
            "func_sig",
            "func_va",
            "func_rva",
            "func_size",
        ],
    ),
    (
        "CSkeletonInstance_m_modelState_m_hModel",
        [
            "struct_name",
            "member_name",
            "offset",
            "size",
            "offset_sig",
            "offset_sig_disp",
        ],
    ),
    (
        "CSkeletonInstance_m_modelState",
        [
            "struct_name",
            "member_name",
            "offset",
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
    """Reuse previous gamever offset_sig/func_sig to locate targets and write YAML."""
    return await preprocess_common_skill(
        session=session,
        expected_outputs=expected_outputs,
        old_yaml_map=old_yaml_map,
        new_binary_dir=new_binary_dir,
        platform=platform,
        image_base=image_base,
        func_names=TARGET_FUNCTION_NAMES,
        struct_member_names=TARGET_STRUCT_MEMBER_NAMES,
        llm_decompile_specs=LLM_DECOMPILE,
        llm_config=llm_config,
        generate_yaml_desired_fields=GENERATE_YAML_DESIRED_FIELDS,
        debug=debug,
    )
