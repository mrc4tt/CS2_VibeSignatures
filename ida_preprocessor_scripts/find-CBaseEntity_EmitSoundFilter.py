#!/usr/bin/env python3
"""Preprocess script for find-CBaseEntity_EmitSoundFilter skill.

ABI NOTE: consumers call this with sret ABI (out-struct in rdi/rcx). The correct
target's head is `48 B8 00 00 00 00 FF FF FF FF 55 48 89 E5 ...` (writes [rdi]).
The `55 48 89 E5 41 57 41 56 49 89 F6 BE ...` / `48 89 74 24 ?? 57 41 56 41 57 ...`
candidate is a different `this`-method and crashes every consumer - see SKILL.md.
"""

from abi_guard import make_llm_result_validator
from ida_analyze_util import preprocess_common_skill

TARGET_FUNCTION_NAMES = [
    "CBaseEntity_EmitSoundFilter",
]

LLM_DECOMPILE = [
    {
        "symbol_name": "CBaseEntity_EmitSoundFilter",
        "prompt_path": "prompt/call_llm_decompile.md",
        "reference_yaml_paths": [
            "references/server/CPlayer_MovementServices_PlayWaterStepSound.{platform}.yaml",
        ],
        "expected_result_sections": ["found_call"],
        "dependency_policy": {
            "CPlayer_MovementServices_PlayWaterStepSound.{platform}.yaml": "required",
        },
    },
]

GENERATE_YAML_DESIRED_FIELDS = [
    # (symbol_name, generate_yaml_fields)
    (
        "CBaseEntity_EmitSoundFilter",
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
        # ABI guard: reject LLM-fallback candidates with a known-bad function head (see abi_guard.py)
        llm_result_validator=make_llm_result_validator("CBaseEntity_EmitSoundFilter", platform, new_binary_dir),
        generate_yaml_desired_fields=GENERATE_YAML_DESIRED_FIELDS,
        debug=debug,
    )
