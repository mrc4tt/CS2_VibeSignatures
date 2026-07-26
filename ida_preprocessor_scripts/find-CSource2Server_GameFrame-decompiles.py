#!/usr/bin/env python3
"""Preprocess script for find-CSource2Server_GameFrame-decompiles skill."""

from ida_analyze_util import preprocess_common_skill
from ida_preprocessor_scripts._igamesystem_dispatch_common import (
    preprocess_igamesystem_dispatch_skill,
)

SOURCE_YAML_STEM = "CSource2Server_GameFrame"
TARGET_SPECS = [
    {"target_name": "IGameSystem_OnServerPreEntityThink", "rename_to": "GameSystem_OnServerPreEntityThink"},
    {"target_name": "IGameSystem_OnServerPostEntityThink", "rename_to": "GameSystem_OnServerPostEntityThink"},
]
VIA_INTERNAL_WRAPPER = False
INTERNAL_RENAME_TO = None
MULTI_ORDER = "index"

TARGET_FUNCTION_NAMES = [
    "IVEngineServer2_IsLogEnabled",
]

FUNC_VTABLE_RELATIONS = [
    # IVEngineServer2 is abstract; vtable_name is metadata only.
    ("IVEngineServer2_IsLogEnabled", "IVEngineServer2"),
]

LLM_DECOMPILE = [
    {
        "symbol_name": "IVEngineServer2_IsLogEnabled",
        "prompt_path": "prompt/call_llm_decompile.md",
        "reference_yaml_paths": ["references/server/CSource2Server_GameFrame.{platform}.yaml"],
        "expected_result_sections": ["found_vcall"],
        "dependency_policy": {"CSource2Server_GameFrame.{platform}.yaml": "required"},
    },
]

GENERATE_YAML_DESIRED_FIELDS = [
    (
        "IVEngineServer2_IsLogEnabled",
        ["func_name", "vfunc_sig", "vfunc_offset", "vfunc_index", "vtable_name"],
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
    """Resolve GameSystem dispatches and IVEngineServer2::IsLogEnabled."""
    _ = skill_name
    dispatch_ok = await preprocess_igamesystem_dispatch_skill(
        session=session,
        expected_outputs=expected_outputs,
        new_binary_dir=new_binary_dir,
        platform=platform,
        image_base=image_base,
        source_yaml_stem=SOURCE_YAML_STEM,
        target_specs=TARGET_SPECS,
        via_internal_wrapper=VIA_INTERNAL_WRAPPER,
        internal_rename_to=INTERNAL_RENAME_TO,
        multi_order=MULTI_ORDER,
        debug=debug,
    )
    if not dispatch_ok:
        return False

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
