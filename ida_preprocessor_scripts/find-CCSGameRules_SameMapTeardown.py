#!/usr/bin/env python3
"""Preprocess script for find-CCSGameRules_SameMapTeardown skill (hand-written, func).

Relocation of the previous gamever's func_sig is tried first. When the body has
changed (14182: the 14181 head pattern matched nothing), the string anchors below
resolve it deterministically instead of an agent hunt: both format strings are
referenced from exactly one function on every gamever checked (14180, 14181,
14182), and the intersection of the two must be a single function.
"""

from ida_analyze_util import preprocess_common_skill

TARGETS = [
    "CCSGameRules_SameMapTeardown",
]

FUNC_XREFS = [
    {
        "func_name": "CCSGameRules_SameMapTeardown",
        "xref_strings": [
            "NEXTLEVELVOTE: Absolute winner choice %d",
            "CHANGELEVEL: ConVar '%s' is set, next map will be '%s'",
        ],
        "xref_gvs": [],
        "xref_signatures": [],
        "xref_funcs": [],
        "exclude_funcs": [],
        "exclude_strings": [],
        "exclude_gvs": [],
        "exclude_signatures": [],
    },
]

GENERATE_YAML_DESIRED_FIELDS = [
    (
        "CCSGameRules_SameMapTeardown",
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
    """Relocate the previous gamever's func artifact onto this build."""
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
