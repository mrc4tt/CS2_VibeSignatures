#!/usr/bin/env python3
"""Preprocess script for find-CEntitySystem_InitEntityMaterialAttributes skill.

Windows-only de-inline helper. Since 14168 server.dll, the entity-material-attributes
init logic was de-inlined out of CEntitySystem_Init into a standalone
CEntitySystem_InitEntityMaterialAttributes function. This skill locates that function
via an LLM_DECOMPILE ``found_call`` against CEntitySystem_Init (reference:
CEntitySystem_Init-noinline, which shows the direct call).

It is the first link of the de-inline fallback chain:
  1. find-CEntitySystem_InitEntityMaterialAttributes  (this skill; optional)
  2. find-CEntitySystem_m_EntityMaterialAttributes     (decompiles the located func)
  3. find-CEntitySystem_Init-decompiles                (inlined fallback; keeps the
                                                        member as an inlined target)
On an inlined build the call is absent, ``found_call`` returns nothing, and this skill
soft-skips (optional_output) so the chain yields to the inlined fallback.
"""

from ida_analyze_util import preprocess_common_skill

TARGET_FUNCTION_NAMES = [
    "CEntitySystem_InitEntityMaterialAttributes",
]

LLM_DECOMPILE = [
    {
        "symbol_name": "CEntitySystem_InitEntityMaterialAttributes",
        "prompt_path": "prompt/call_llm_decompile.md",
        "reference_yaml_paths": [
            "references/server/CEntitySystem_Init-noinline.{platform}.yaml",
        ],
        "expected_result_sections": ["found_call"],
    },
]

GENERATE_YAML_DESIRED_FIELDS = [
    # (symbol_name, generate_yaml_fields)
    (
        "CEntitySystem_InitEntityMaterialAttributes",
        [
            "func_name",
            "func_sig",
            "func_va",
            "func_rva",
            "func_size",
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
    """Locate the de-inlined CEntitySystem_InitEntityMaterialAttributes via found_call."""
    return await preprocess_common_skill(
        session=session,
        expected_outputs=expected_outputs,
        old_yaml_map=old_yaml_map,
        new_binary_dir=new_binary_dir,
        platform=platform,
        image_base=image_base,
        func_names=TARGET_FUNCTION_NAMES,
        llm_decompile_specs=LLM_DECOMPILE,
        llm_config=llm_config,
        generate_yaml_desired_fields=GENERATE_YAML_DESIRED_FIELDS,
        debug=debug,
    )
