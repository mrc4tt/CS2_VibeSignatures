#!/usr/bin/env python3
"""Preprocess script for find-CLoopTypeBase_AddDependentServices-decompiles skill.

IEngineService::GetServiceDependencies and IEngineService::GetName are the first two
IEngineService-specific vfuncs (pure-virtual interface methods). They are discovered by
decompiling a predecessor that calls them through the interface vtable and reporting the
vcall slot offsets (0x58 = GetServiceDependencies, 0x60 = GetName).

This is the de-inlined link of an inline/noinline decompile fallback pair: it decompiles
the standalone ``CLoopTypeBase_AddDependentServices`` helper, which contains both vcalls
whenever it is compiled as a separate function (Windows on all builds; Linux once the
dependency helpers are de-inlined, e.g. 14168). When ``AddDependentServices`` is inlined
into ``CLoopTypeBase_LoadDependentServices`` (e.g. Linux 14167) the standalone helper is
absent, so the predecessor cannot be resolved and this skill legitimately produces
nothing (its output is optional); the
``find-CLoopTypeBase_LoadDependentServices-decompiles`` fallback (which decompiles the
inlined parent) runs instead.
"""

from ida_analyze_util import preprocess_common_skill

TARGET_FUNCTION_NAMES = [
    "IEngineService_GetServiceDependencies",
    "IEngineService_GetName",
]

# Both vfuncs are called inside the standalone CLoopTypeBase_AddDependentServices helper.
LLM_DECOMPILE = [
    {
        "symbol_name": "IEngineService_GetServiceDependencies",
        "prompt_path": "prompt/call_llm_decompile.md",
        "reference_yaml_paths": [
            "references/engine/CLoopTypeBase_AddDependentServices.{platform}.yaml",
        ],
        "expected_result_sections": ["found_vcall"],
        "dependency_policy": {
            "CLoopTypeBase_AddDependentServices.{platform}.yaml": "optional",
        },
    },
    {
        "symbol_name": "IEngineService_GetName",
        "prompt_path": "prompt/call_llm_decompile.md",
        "reference_yaml_paths": [
            "references/engine/CLoopTypeBase_AddDependentServices.{platform}.yaml",
        ],
        "expected_result_sections": ["found_vcall"],
        "dependency_policy": {
            "CLoopTypeBase_AddDependentServices.{platform}.yaml": "optional",
        },
    },
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
            # On de-inlined Linux builds the only GetName vcall inside AddDependentServices
            # is a generic Plat_FatalError path that is byte-identical to sibling helpers'
            # fatal paths and sits ~0x17 bytes from the function end; allow the signature to
            # extend past the boundary (through 0xCC padding into the next code head) so it
            # can diverge from the collision and become unique.
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
    """Locate IEngineService GetServiceDependencies/GetName vfuncs via LLM decompile of AddDependentServices."""
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
