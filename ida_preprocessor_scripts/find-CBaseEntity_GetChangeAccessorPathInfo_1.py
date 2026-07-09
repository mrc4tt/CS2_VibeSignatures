#!/usr/bin/env python3
"""Preprocess script for find-CBaseEntity_GetChangeAccessorPathInfo_1 skill.

Virtual function whose body is byte-for-byte identical to
CBaseEntity_GetChangeAccessorPathInfo_2 (so no unique func_sig can be emitted);
it is distinguished only by occupying a different CBaseEntity vtable slot within
+/-2 of _2. There is no CEntityInstance_GetChangeAccessorPathInfo_1 base to
inherit from, so the discovery is the neighbor-slot / ICF-fold heuristic in
SKILL.md, which is not mechanically reproducible here.

This preprocess therefore reuses the previous gamever's vfunc metadata
(vfunc_index -> same slot in the new CBaseEntity vtable) when a prior YAML
exists. On the first run (no prior YAML) it will fail and the runner falls back
to the agent SKILL.md.
"""

from ida_analyze_util import preprocess_common_skill

TARGET_FUNCTION_NAMES = [
    "CBaseEntity_GetChangeAccessorPathInfo_1",
]

FUNC_VTABLE_RELATIONS = [
    # (func_name, vtable_class)
    ("CBaseEntity_GetChangeAccessorPathInfo_1", "CBaseEntity"),
]

GENERATE_YAML_DESIRED_FIELDS = [
    # (symbol_name, generate_yaml_fields)
    (
        "CBaseEntity_GetChangeAccessorPathInfo_1",
        [
            "func_name",
            "func_va",
            "func_rva",
            "func_size",
            # func_sig omitted: identical body to _2, cannot generate a unique sig
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
    debug=False,
):
    """Reuse old vfunc metadata (slot index) to relocate via the new vtable."""
    _ = skill_name

    return await preprocess_common_skill(
        session=session,
        expected_outputs=expected_outputs,
        old_yaml_map=old_yaml_map,
        new_binary_dir=new_binary_dir,
        platform=platform,
        image_base=image_base,
        func_names=TARGET_FUNCTION_NAMES,
        func_vtable_relations=FUNC_VTABLE_RELATIONS,
        generate_yaml_desired_fields=GENERATE_YAML_DESIRED_FIELDS,
        debug=debug,
    )
