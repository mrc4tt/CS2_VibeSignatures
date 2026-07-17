#!/usr/bin/env python3
"""Preprocess script for find-CBaseEntity_NetworkStateChanged-noinline skill (deinline-fix chain, link 2/3).

Resolves ``CBaseEntity::NetworkStateChanged`` from the de-inlined notify helper
(``CFlashbangProjectile_Spawn_NetworkStateChangedNotify``): its body issues the
``call qword ptr [reg+vfunc_offset]`` into the entity vtable slot. Used on builds
where the notify logic is a separate function (e.g. Windows). Soft-skips
(``optional_output``) when the helper is absent (inlined builds), yielding to the
``-inlined`` link.
"""

from ida_analyze_util import preprocess_common_skill

TARGET_FUNCTION_NAMES = [
    "CBaseEntity_NetworkStateChanged",
]

LLM_DECOMPILE = [
    {
        "symbol_name": "CBaseEntity_NetworkStateChanged",
        "prompt_path": "prompt/call_llm_decompile.md",
        "reference_yaml_paths": [
            "references/server/CFlashbangProjectile_Spawn_NetworkStateChangedNotify.{platform}.yaml",
        ],
        "expected_result_sections": ["found_vcall"],
    },
]

FUNC_VTABLE_RELATIONS = [
    # (func_name, vtable_class)
    ("CBaseEntity_NetworkStateChanged", "CBaseEntity"),
]

GENERATE_YAML_DESIRED_FIELDS = [
    # (symbol_name, generate_yaml_fields)
    # CBaseEntity_NetworkStateChanged is a GENUINE vtable member with a real body,
    # discovered via a vcall through the entity vtable. Use func_sig (of the
    # resolved body) + FUNC_VTABLE_RELATIONS (Pattern D shape), NOT vfunc_sig:
    # the vcall SITE (e.g. the inlined `mov [reg+0xE8]` load on Linux) is not a
    # unique anchor, whereas the resolved function body signs uniquely. Keep the
    # same field set on the inlined link so the output shape never flips per build.
    (
        "CBaseEntity_NetworkStateChanged",
        [
            "func_name",
            "func_va",
            "func_rva",
            "func_size",
            "func_sig",
            "vtable_name",
            "vfunc_offset",
            "vfunc_index",
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
    """Locate CBaseEntity_NetworkStateChanged as the vtable call inside the de-inlined notify helper."""
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
