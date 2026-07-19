#!/usr/bin/env python3
"""Preprocess script for find-CEngineServiceMgr_UnregisterLoopMode-noinline skill (deinline-fix chain, link 2/3).

Collects the ``CLoopTypeBase::GetImplType`` (+0x50), ``ILoopModeFactory::GetLoopModeType``
(+0x20) and ``ILoopModeFactory::Shutdown`` (+0x8) vcalls for the *de-inlined* layout of
``CEngineServiceMgr::UnregisterLoopMode`` (Linux 14168+).

When the helper is de-inlined the three vcalls are split across two functions:
  * ``GetImplType`` stays in the parent ``CEngineServiceMgr_UnregisterLoopMode`` body, so it
    is decompiled from the de-inlined parent reference.
  * ``GetLoopModeType`` and ``Shutdown`` move into the standalone
    ``UnregisterLoopModeFactory`` helper (located by ``find-UnregisterLoopModeFactory``), so
    they are decompiled from the helper reference.

This is the de-inlined link of an inline/noinline decompile fallback pair.  Its output is
``optional`` so that on inlined builds -- where the helper is absent and its reference
cannot be resolved -- it soft-skips and yields to
``find-CEngineServiceMgr_UnregisterLoopMode-inlined`` (which decompiles the fully inlined
parent).  It is gated ``platform: linux`` because the de-inline only happens on Linux; on
Windows the ``-inlined`` fallback handles the (inlined) parent directly.

The GENERATE_YAML_DESIRED_FIELDS are kept byte-for-byte identical to the ``-inlined`` link
so the three symbols' output shape does not depend on which path wins.
"""

from ida_analyze_util import preprocess_common_skill

TARGET_FUNCTION_NAMES = [
    "CLoopTypeBase_GetImplType",
    "ILoopModeFactory_GetLoopModeType",
    "ILoopModeFactory_Shutdown",
]

LLM_DECOMPILE = [
    {
        "symbol_name": "CLoopTypeBase_GetImplType",
        "prompt_path": "prompt/call_llm_decompile.md",
        "reference_yaml_paths": [
            "references/engine/CEngineServiceMgr_UnregisterLoopMode-noinline.{platform}.yaml",
        ],
        "expected_result_sections": ["found_vcall"],
        "dependency_policy": {
            "CEngineServiceMgr_UnregisterLoopMode.{platform}.yaml": "required",
        },
    },
    {
        "symbol_name": "ILoopModeFactory_GetLoopModeType",
        "prompt_path": "prompt/call_llm_decompile.md",
        "reference_yaml_paths": [
            "references/engine/UnregisterLoopModeFactory.{platform}.yaml",
        ],
        "expected_result_sections": ["found_vcall"],
        "dependency_policy": {
            "UnregisterLoopModeFactory.{platform}.yaml": "optional",
        },
    },
    {
        "symbol_name": "ILoopModeFactory_Shutdown",
        "prompt_path": "prompt/call_llm_decompile.md",
        "reference_yaml_paths": [
            "references/engine/UnregisterLoopModeFactory.{platform}.yaml",
        ],
        "expected_result_sections": ["found_vcall"],
        "dependency_policy": {
            "UnregisterLoopModeFactory.{platform}.yaml": "optional",
        },
    },
]

FUNC_VTABLE_RELATIONS = [
    # (func_name, vtable_class)
    ("CLoopTypeBase_GetImplType", "CLoopTypeBase"),
    ("ILoopModeFactory_GetLoopModeType", "ILoopModeFactory"),
    ("ILoopModeFactory_Shutdown", "ILoopModeFactory"),
]

GENERATE_YAML_DESIRED_FIELDS = [
    # (symbol_name, generate_yaml_fields)
    (
        "CLoopTypeBase_GetImplType",
        [
            "func_name",
            "vfunc_sig",
            "vfunc_offset",
            "vfunc_index",
            "vtable_name",
        ],
    ),
    (
        "ILoopModeFactory_GetLoopModeType",
        [
            "func_name",
            "vfunc_sig",
            "vfunc_offset",
            "vfunc_index",
            "vtable_name",
        ],
    ),
    (
        "ILoopModeFactory_Shutdown",
        [
            "func_name",
            "vfunc_sig",
            "vfunc_sig_allow_across_function_boundary:true",
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
    """Collect the loop-mode vcalls for the de-inlined UnregisterLoopMode layout via LLM decompile."""
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
