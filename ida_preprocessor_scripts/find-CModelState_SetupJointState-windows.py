#!/usr/bin/env python3
"""Preprocess script for find-CModelState_SetupJointState-windows skill."""

from ida_analyze_util import preprocess_common_skill

TARGET_FUNCTION_NAMES = []

TARGET_STRUCT_MEMBER_NAMES = [
    "CModelState_m_nTotalTransformCount",
    "CModelState_m_nBoneCount",
    "CModelState_m_nAttachmentCount",
]

LLM_DECOMPILE = [
    # (symbol_name, path_to_prompt, path_to_reference)
    (
        "CModelState_m_nTotalTransformCount",
        "prompt/call_llm_decompile.md",
        "references/client/CModelState_SetupJointState.{platform}.yaml",
    ),
    (
        "CModelState_m_nBoneCount",
        "prompt/call_llm_decompile.md",
        "references/client/CModelState_SetupJointState.{platform}.yaml",
    ),
    (
        "CModelState_m_nAttachmentCount",
        "prompt/call_llm_decompile.md",
        "references/client/CModelState_SetupJointState.{platform}.yaml",
    ),
]

GENERATE_YAML_DESIRED_FIELDS = [
    # (symbol_name, generate_yaml_fields)
    (
        "CModelState_m_nTotalTransformCount",
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
        "CModelState_m_nBoneCount",
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
        "CModelState_m_nAttachmentCount",
        [
            "struct_name",
            "member_name",
            "offset",
            "size",
            "offset_sig",
            "offset_sig_disp",
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
    """Reuse previous gamever offset_sig to locate targets and write YAML."""
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
