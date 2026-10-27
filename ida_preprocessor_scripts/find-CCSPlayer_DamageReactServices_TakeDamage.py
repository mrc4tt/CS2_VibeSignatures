#!/usr/bin/env python3
"""Preprocess script for find-CCSPlayer_DamageReactServices_TakeDamage skill.

cs2-menus hooks this as "OnTakeDamagePre" (services, CTakeDamageInfo*): it reads the
pawn from [rdi+0x38] and returns early on a flag at pawn+0x1880. The plugin's own
comment calls it CBaseEntity::TakeDamageOld, but that string's function is the
caller; this is the damage-react services handler it reaches.

No string of its own, so this relocates the previous gamever's func_sig. When that
fails, the anchor for the agent fallback is the only reference: a tail-call `jmp`
from the function laid out just before CCSPlayerPawn_OnTakeDamage_Alive's body
(14183 linux: target 0x157f5a0, jmp at 0x1598b47). No artifact exists yet on either
platform - the first baseline has to come from a hunt / IDA session (emit_artifact.py).
"""

from ida_analyze_util import preprocess_common_skill

TARGET_FUNCTION_NAMES = [
    "CCSPlayer_DamageReactServices_TakeDamage",
]

GENERATE_YAML_DESIRED_FIELDS = [
    # (symbol_name, generate_yaml_fields)
    (
        "CCSPlayer_DamageReactServices_TakeDamage",
        [
            "func_name",
            "func_va",
            "func_rva",
            "func_size",
            "func_sig",
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
    debug=False,
):
    """Reuse previous gamever func_sig to locate the target function and write YAML."""
    return await preprocess_common_skill(
        session=session,
        expected_outputs=expected_outputs,
        old_yaml_map=old_yaml_map,
        new_binary_dir=new_binary_dir,
        platform=platform,
        image_base=image_base,
        func_names=TARGET_FUNCTION_NAMES,
        generate_yaml_desired_fields=GENERATE_YAML_DESIRED_FIELDS,
        debug=debug,
    )
