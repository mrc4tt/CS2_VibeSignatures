#!/usr/bin/env python3
"""Preprocess script for find-CCSPointScript_OnCustomHudClicked skill.

Hand-written (not the seed template): the relocation chain slid onto the wrong function
at 14181 and carried it to 14185. CCSPointScript::OnCustomHudClicked(player, layout,
buttonId) is the virtual that fires the script event; point_script.OnCustomHudClicked
(callback) is the JS binding that only registers a callback, and it prints the same name.
Both load an "OnCustomHudClicked" literal, so the anchor adds the event's own argument
name and excludes the binding's "point_script". abi_guard's ABI_GUARDS entry discards a
relocation that lands on the binding, which is what lets this fallback run.
"""

from ida_analyze_util import preprocess_common_skill

TARGETS = [
    "CCSPointScript_OnCustomHudClicked",
]

FUNC_XREFS = [
    {
        "func_name": "CCSPointScript_OnCustomHudClicked",
        "xref_strings": ["OnCustomHudClicked", "buttonId"],
        "xref_gvs": [],
        "xref_signatures": [],
        "xref_funcs": [],
        "exclude_funcs": [],
        "exclude_strings": ["point_script"],
        "exclude_gvs": [],
        "exclude_signatures": [],
    },
]

GENERATE_YAML_DESIRED_FIELDS = [
    (
        "CCSPointScript_OnCustomHudClicked",
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
    """Relocate from the previous gamever, falling back to the string anchor."""
    return await preprocess_common_skill(
        session=session,
        expected_outputs=expected_outputs,
        old_yaml_map=old_yaml_map,
        new_binary_dir=new_binary_dir,
        platform=platform,
        image_base=image_base,
        func_names=TARGETS,
        func_xrefs=FUNC_XREFS,
        generate_yaml_desired_fields=GENERATE_YAML_DESIRED_FIELDS,
        debug=debug,
    )
