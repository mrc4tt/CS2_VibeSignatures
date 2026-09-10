#!/usr/bin/env python3
"""Preprocess script for find-CFlashbangProjectile_Spawn-decompiles skill."""

from ida_analyze_util import preprocess_common_skill

TARGET_FUNCTION_NAMES = [
    "CBaseModelEntity_SetModel",
    "CBaseEntity_SetGravityScale",
]

LLM_DECOMPILE = [
    {
        "symbol_name": "CBaseModelEntity_SetModel",
        "prompt_path": "prompt/call_llm_decompile.md",
        "reference_yaml_paths": [
            "references/server/CFlashbangProjectile_Spawn.{platform}.yaml",
        ],
        "expected_result_sections": ["found_call"],
        "dependency_policy": {
            "CFlashbangProjectile_Spawn.{platform}.yaml": "required",
        },
    },
    {
        "symbol_name": "CBaseEntity_SetGravityScale",
        "prompt_path": "prompt/call_llm_decompile.md",
        "reference_yaml_paths": [
            "references/server/CFlashbangProjectile_Spawn.{platform}.yaml",
        ],
        "expected_result_sections": ["found_call"],
        "dependency_policy": {
            "CFlashbangProjectile_Spawn.{platform}.yaml": "required",
        },
    },
]

GENERATE_YAML_DESIRED_FIELDS = [
    # (symbol_name, generate_yaml_fields)
    (
        "CBaseModelEntity_SetModel",
        [
            "func_name",
            "func_sig",
            # Function body is only 0x2c/0x31 bytes with a generic prologue, so a
            # body-only signature is not unique and the generator falls back to
            # un-wildcarding RIP-relative displacement bytes -- which break on
            # every rebuild. Crossing the boundary keeps the displacement fully
            # wildcarded and reaches padding + the next function head instead.
            "func_sig_allow_across_function_boundary:true",
            "func_va",
            "func_rva",
            "func_size",
        ],
    ),
    (
        "CBaseEntity_SetGravityScale",
        [
            "func_name",
            "func_sig",
            "func_va",
            "func_rva",
            "func_size",
            # same short-body reason as CBaseModelEntity_SetModel above
            "func_sig_allow_across_function_boundary:true",
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
    """Reuse previous gamever func_sig to locate target function(s) and write YAML."""
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
