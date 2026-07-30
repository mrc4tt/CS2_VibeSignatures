#!/usr/bin/env python3
"""Preprocess script for find-OnRenderStart-decompiles skill."""

from ida_analyze_util import preprocess_common_skill

TARGET_FUNCTION_NAMES = [
    "IViewRender_OnRenderStart",
]

LLM_DECOMPILE = [
    {
        "symbol_name": "IViewRender_OnRenderStart",
        "prompt_path": "prompt/call_llm_decompile.md",
        "reference_yaml_paths": [
            "references/client/OnRenderStart.{platform}.yaml",
        ],
        "expected_result_sections": ["found_vcall"],
        "dependency_policy": {
            "OnRenderStart.{platform}.yaml": "required",
        },
    },
]

FUNC_VTABLE_RELATIONS = [
    # IViewRender is abstract; this relation supplies vtable metadata only.
    ("IViewRender_OnRenderStart", "IViewRender"),
]

GENERATE_YAML_DESIRED_FIELDS = [
    (
        "IViewRender_OnRenderStart",
        [
            "func_name",
            "vfunc_sig",
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
    """Resolve the IViewRender OnRenderStart slot from the render-start helper."""
    return await preprocess_common_skill(
        session=session,
        expected_outputs=expected_outputs,
        old_yaml_map=old_yaml_map,
        new_binary_dir=new_binary_dir,
        platform=platform,
        image_base=image_base,
        func_names=TARGET_FUNCTION_NAMES,
        func_vtable_relations=FUNC_VTABLE_RELATIONS,
        llm_decompile_specs=LLM_DECOMPILE,
        llm_config=llm_config,
        generate_yaml_desired_fields=GENERATE_YAML_DESIRED_FIELDS,
        debug=debug,
    )
