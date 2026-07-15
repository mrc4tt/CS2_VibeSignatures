#!/usr/bin/env python3
"""Preprocess script for find-CEntitySystem_m_EntityMaterialAttributes skill.

Windows-only de-inline path. Decompiles the de-inlined
CEntitySystem_InitEntityMaterialAttributes function (located by
find-CEntitySystem_InitEntityMaterialAttributes) to recover the
CEntitySystem::m_EntityMaterialAttributes struct-member offset.

Second link of the de-inline fallback chain (see
find-CEntitySystem_InitEntityMaterialAttributes). ``optional_output`` so that on an
inlined build -- where the helper skill soft-skipped and no
CEntitySystem_InitEntityMaterialAttributes.{platform}.yaml exists -- this skill
soft-skips too and yields to find-CEntitySystem_Init-decompiles (the inlined fallback,
which keeps m_EntityMaterialAttributes as an inlined target).
"""

from ida_analyze_util import preprocess_common_skill

TARGET_STRUCT_MEMBER_NAMES = [
    "CEntitySystem_m_EntityMaterialAttributes",
]

LLM_DECOMPILE = [
    # (symbol_name, path_to_prompt, path_to_reference)
    (
        "CEntitySystem_m_EntityMaterialAttributes",
        "prompt/call_llm_decompile.md",
        "references/server/CEntitySystem_InitEntityMaterialAttributes.{platform}.yaml",
    ),
]

GENERATE_YAML_DESIRED_FIELDS = [
    # (symbol_name, generate_yaml_fields)
    (
        "CEntitySystem_m_EntityMaterialAttributes",
        [
            "struct_name",
            "member_name",
            "offset",
            # "size",
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
    """Decompile the de-inlined init function to locate the struct member and write YAML."""
    return await preprocess_common_skill(
        session=session,
        expected_outputs=expected_outputs,
        old_yaml_map=old_yaml_map,
        new_binary_dir=new_binary_dir,
        platform=platform,
        image_base=image_base,
        struct_member_names=TARGET_STRUCT_MEMBER_NAMES,
        llm_decompile_specs=LLM_DECOMPILE,
        llm_config=llm_config,
        generate_yaml_desired_fields=GENERATE_YAML_DESIRED_FIELDS,
        debug=debug,
    )
