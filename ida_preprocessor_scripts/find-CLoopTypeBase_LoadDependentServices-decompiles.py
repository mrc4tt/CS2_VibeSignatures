#!/usr/bin/env python3
"""Preprocess script for find-CLoopTypeBase_LoadDependentServices-decompiles skill.

IEngineService::GetServiceDependencies and IEngineService::GetName are the first two
IEngineService-specific vfuncs (pure-virtual interface methods), discovered by decompiling
a predecessor that calls them through the interface vtable and reporting the vcall slot
offsets (0x58 = GetServiceDependencies, 0x60 = GetName).

This is the inlined link of an inline/noinline decompile fallback pair: it decompiles
``CLoopTypeBase_LoadDependentServices`` directly, which contains both vcalls only when the
dependency helpers (AddDependentServices/GenerateServiceDependencies/
GenerateSecondaryDependencies) are inlined into it (e.g. Linux 14167). It is the fallback
for ``find-CLoopTypeBase_AddDependentServices-decompiles`` (which handles the de-inlined
case by decompiling the standalone helper) and is skipped whenever the two IEngineService
outputs already exist (i.e. the de-inlined path already produced them, as on Windows and
on de-inlined Linux builds).
"""

from ida_analyze_util import preprocess_common_skill

TARGET_FUNCTION_NAMES = [
    "IEngineService_GetServiceDependencies",
    "IEngineService_GetName",
]

# When the helpers are inlined, both vcalls live inside CLoopTypeBase_LoadDependentServices.
LLM_DECOMPILE = [
    (
        "IEngineService_GetServiceDependencies",
        "prompt/call_llm_decompile.md",
        "references/engine/CLoopTypeBase_LoadDependentServices.{platform}.yaml",
    ),
    (
        "IEngineService_GetName",
        "prompt/call_llm_decompile.md",
        "references/engine/CLoopTypeBase_LoadDependentServices.{platform}.yaml",
    ),
]

FUNC_VTABLE_RELATIONS = [
    # (func_name, vtable_class)
    ("IEngineService_GetServiceDependencies", "IEngineService"),
    ("IEngineService_GetName", "IEngineService"),
]

GENERATE_YAML_DESIRED_FIELDS = [
    # (symbol_name, generate_yaml_fields)
    # Slim Pattern C: neither vfunc is a downstream predecessor, so no func_va/func_rva/func_size.
    (
        "IEngineService_GetServiceDependencies",
        [
            "func_name",
            "vfunc_sig",  # REQUIRED for Pattern C
            "vfunc_offset",
            "vfunc_index",
            "vtable_name",
        ],
    ),
    (
        "IEngineService_GetName",
        [
            "func_name",
            "vfunc_sig",  # REQUIRED for Pattern C
            "vfunc_offset",
            "vfunc_index",
            "vtable_name",
            # Keep the GetName output shape identical to the -decompiles de-inlined path
            # (find-CLoopTypeBase_AddDependentServices-decompiles), where the GetName vcall
            # can only be signed by crossing the function boundary. The generator still
            # prefers the shortest in-boundary signature when one exists (e.g. the inlined
            # LoadDependentServices body), so this is a no-op there.
            "vfunc_sig_allow_across_function_boundary:true",
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
    """Locate IEngineService GetServiceDependencies/GetName vfuncs via LLM decompile of LoadDependentServices."""
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
