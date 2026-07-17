#!/usr/bin/env python3
"""Preprocess script for find-CFlashbangProjectile_Spawn_NetworkStateChangedNotify skill (deinline-fix chain, link 1/3).

Resolves the de-inlined "network state changed" notify helper that
``CFlashbangProjectile_Spawn`` tail-calls on builds where that notification is
NOT inlined into the Spawn body (e.g. Windows). The helper is the predecessor
whose body carries the ``CBaseEntity::NetworkStateChanged`` vtable call, so the
``-noinline`` link decompiles it next. On inlined builds (e.g. Linux) the helper
does not exist as a standalone function, so this skill soft-skips
(``optional_output``) and the ``-inlined`` link resolves the vfunc directly.
"""

from ida_analyze_util import preprocess_common_skill

TARGET_FUNCTION_NAMES = [
    "CFlashbangProjectile_Spawn_NetworkStateChangedNotify",
]

LLM_DECOMPILE = [
    {
        "symbol_name": "CFlashbangProjectile_Spawn_NetworkStateChangedNotify",
        "prompt_path": "prompt/call_llm_decompile.md",
        "reference_yaml_paths": [
            "references/server/CFlashbangProjectile_Spawn.{platform}.yaml",
        ],
        "expected_result_sections": ["found_call"],
    },
]

GENERATE_YAML_DESIRED_FIELDS = [
    # (symbol_name, generate_yaml_fields)
    (
        "CFlashbangProjectile_Spawn_NetworkStateChangedNotify",
        ["func_name", "func_sig", "func_va", "func_rva", "func_size"],
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
    """Locate the de-inlined NetworkStateChanged notify helper by decompiling CFlashbangProjectile_Spawn."""
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
