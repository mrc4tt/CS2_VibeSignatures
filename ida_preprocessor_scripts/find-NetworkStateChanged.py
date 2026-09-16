#!/usr/bin/env python3
"""Preprocess script for find-NetworkStateChanged skill.

ANCHOR WARNING (IDA-verified 14181): the xref_strings anchor ("light_omni"/"light_capsule")
resolves to the light-entity method that *calls* NetworkStateChanged (linux 0xa882e0), not to
NetworkStateChanged itself (CEntityInstance::NetworkStateChanged, linux 0x216a990, head
`48 8B 07 48 85 C0 74 ?? 48 8B 50`). Only the func_sig relocation path yields the right
function; abi_guard.py re-seeds the artifact if the xref path wins. See SKILL.md.
"""

from abi_guard import make_llm_result_validator
from ida_analyze_util import preprocess_common_skill

TARGET_FUNCTION_NAMES = [
    "NetworkStateChanged",
]

# Per-platform anchors. The old xref_strings anchor ("light_omni"/"light_capsule") selected the
# light-entity method that *calls* NetworkStateChanged (IDA-verified 14181). NetworkStateChanged
# itself (the non-virtual CEntityInstance dispatcher CS# expects) has no strings, so anchor on its
# own head bytes: xref_signatures yields the function *containing* the pattern. Signatures are
# platform-specific, so the spec is selected per platform in preprocess_skill.
FUNC_XREFS_BY_PLATFORM = {
    "linux": [
        {
            "func_name": "NetworkStateChanged",
            "xref_strings": [],
            "xref_gvs": [],
            "xref_signatures": ["48 8B 07 48 85 C0 74 ?? 48 8B 50"],
            "xref_funcs": [],
            "exclude_funcs": [],
            "exclude_strings": ["light_omni", "light_capsule"],
            "exclude_gvs": [],
            "exclude_signatures": [],
        },
    ],
    "windows": [
        {
            "func_name": "NetworkStateChanged",
            "xref_strings": [],
            "xref_gvs": [],
            "xref_signatures": ["4C 8B C2 48 8B D1 48 8B 09"],
            "xref_funcs": [],
            "exclude_funcs": [],
            "exclude_strings": ["light_omni", "light_capsule"],
            "exclude_gvs": [],
            "exclude_signatures": [],
        },
    ],
}
FUNC_XREFS = FUNC_XREFS_BY_PLATFORM["linux"]  # kept for recipe importers; preprocess_skill picks per platform

GENERATE_YAML_DESIRED_FIELDS = [
    # (symbol_name, generate_yaml_fields)
    (
        "NetworkStateChanged",
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
        llm_result_validator=make_llm_result_validator("NetworkStateChanged", platform, new_binary_dir),
        generate_yaml_desired_fields=GENERATE_YAML_DESIRED_FIELDS,
        debug=debug,
    )
