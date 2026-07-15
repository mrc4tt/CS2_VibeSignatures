#!/usr/bin/env python3
"""Preprocess script for find-CBaseEntity_NetworkStateChanged-inlined skill (deinline-fix chain, link 3/3).

Resolves ``CBaseEntity::NetworkStateChanged`` from ``CFlashbangProjectile_Spawn``
itself on builds where the network-state-changed notification is INLINED into the
Spawn body (e.g. Linux): the inlined block fetches the entity vtable slot with a
``mov reg, [reg+vfunc_offset]`` load and compares it against the default
implementation. This is the LLM_DECOMPILE replacement for the previous
FUNC_XREFS-based finder, so the skill no longer depends on
``CNetworkTransmitComponent_StateChanged``. Runs when the ``-noinline`` link did
not already produce the output (``skip_if_exists``).
"""

from ida_analyze_util import preprocess_common_skill

TARGET_FUNCTION_NAMES = [
    "CBaseEntity_NetworkStateChanged",
]

LLM_DECOMPILE = [
    # (symbol_name, path_to_prompt, path_to_reference)
    (
        "CBaseEntity_NetworkStateChanged",
        "prompt/call_llm_decompile.md",
        "references/server/CFlashbangProjectile_Spawn.{platform}.yaml",
    ),
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
    # same field set on the -noinline link so the output shape never flips per build.
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
    """Locate CBaseEntity_NetworkStateChanged from the inlined vtable fetch inside CFlashbangProjectile_Spawn."""
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
