#!/usr/bin/env python3
"""Preprocess script for find-CNavPhysicsInterface_vtable_ref skill.

The instruction that loads CNavPhysicsInterface's vtable (a constructor's lea), as a gv record:
CounterStrikeSharp's CNavPhysicsInterface_vtable key ships its gv_sig, and the plugin reads the
RIP-relative displacement at +3. gv_va is checked against the RTTI-resolved
CNavPhysicsInterface_vtable artifact every build and regenerated from it when the old signature
moved, so no baseline or agent is needed (ida_analyze_util.preprocess_vtable_ref_gv_skill).
"""

from ida_analyze_util import preprocess_vtable_ref_gv_skill

GV_NAME = "CNavPhysicsInterface_vtable_ref"
VTABLE_CLASS = "CNavPhysicsInterface"

GENERATE_YAML_DESIRED_FIELDS = [
    # (symbol_name, generate_yaml_fields)
    (
        GV_NAME,
        [
            "gv_name",
            "gv_va",
            "gv_rva",
            "gv_sig",
            "gv_sig_va",
            "gv_inst_offset",
            "gv_inst_length",
            "gv_inst_disp",
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
    return await preprocess_vtable_ref_gv_skill(
        session=session,
        expected_outputs=expected_outputs,
        old_yaml_map=old_yaml_map,
        new_binary_dir=new_binary_dir,
        platform=platform,
        image_base=image_base,
        gv_name=GV_NAME,
        vtable_class=VTABLE_CLASS,
        generate_yaml_desired_fields=GENERATE_YAML_DESIRED_FIELDS,
        debug=debug,
    )
