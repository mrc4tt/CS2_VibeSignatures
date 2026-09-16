#!/usr/bin/env python3
"""Preprocess script for find-CBaseEntity_EmitSoundFilter_SoundName skill.

ModSharp-only overload: CBaseEntity::EmitSoundFilter(IRecipientFilter&, int, const char* soundname,
float volume, ...). Distinct from CBaseEntity_EmitSoundFilter (sret, EmitSound_t&). Anchored on its
own head bytes per platform; abi_guard.py enforces the identity.
"""

from abi_guard import make_llm_result_validator
from ida_analyze_util import preprocess_common_skill

TARGET_FUNCTION_NAMES = [
    "CBaseEntity_EmitSoundFilter_SoundName",
]

# Per-platform head-byte anchors (signatures differ per platform; selected in preprocess_skill).
FUNC_XREFS_BY_PLATFORM = {
    "linux": [
        {
            "func_name": "CBaseEntity_EmitSoundFilter_SoundName",
            "xref_strings": [],
            "xref_gvs": [],
            "xref_signatures": ["55 48 89 E5 41 57 66 41 0F 7E C7 41 56 4D 89 C6"],
            "xref_funcs": [],
            "exclude_funcs": [],
            "exclude_strings": [],
            "exclude_gvs": [],
            "exclude_signatures": [],
        },
    ],
    "windows": [
        {
            "func_name": "CBaseEntity_EmitSoundFilter_SoundName",
            "xref_strings": [],
            "xref_gvs": [],
            "xref_signatures": ["48 89 5C 24 ?? 48 89 74 24 ?? 57 48 83 EC ?? 48 8B DA 49 8B F9"],
            "xref_funcs": [],
            "exclude_funcs": [],
            "exclude_strings": [],
            "exclude_gvs": [],
            "exclude_signatures": [],
        },
    ],
}
FUNC_XREFS = FUNC_XREFS_BY_PLATFORM["linux"]  # kept for recipe importers; preprocess_skill picks per platform

GENERATE_YAML_DESIRED_FIELDS = [
    # (symbol_name, generate_yaml_fields)
    (
        "CBaseEntity_EmitSoundFilter_SoundName",
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
        func_xrefs=FUNC_XREFS_BY_PLATFORM.get(platform, FUNC_XREFS),
        # ABI guard: reject LLM-fallback candidates with a known-bad function head (see abi_guard.py)
        llm_result_validator=make_llm_result_validator(
            "CBaseEntity_EmitSoundFilter_SoundName", platform, new_binary_dir
        ),
        generate_yaml_desired_fields=GENERATE_YAML_DESIRED_FIELDS,
        debug=debug,
    )
