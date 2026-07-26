#!/usr/bin/env python3
"""Preprocess script for find-C_GameRules_ctor skill.

C_GameRules_ctor is identified as the function that (a) references the
"CGameRules::CGameRules constructed" debug string and (b) writes the
C_GameRules vtable pointer. The derived C_MultiplayRules constructor also
matches both of those (it chains up to the base ctor when inlined), so
functions that additionally reference the C_MultiplayRules vtable are
excluded via exclude_gvs.
"""

import os

try:
    import yaml
except ImportError:
    yaml = None

from ida_analyze_util import preprocess_common_skill

TARGET_FUNCTION_NAMES = [
    "C_GameRules_ctor",
]

GENERATE_YAML_DESIRED_FIELDS = [
    # (symbol_name, generate_yaml_fields)
    (
        "C_GameRules_ctor",
        [
            "func_name",
            "func_sig",
            "func_va",
            "func_rva",
            "func_size",
        ],
    ),
]


def _read_vtable_va(yaml_path):
    """Read vtable_va from a vtable YAML file, returning it as a hex string or None."""
    try:
        with open(yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if isinstance(data, dict):
            va = data.get("vtable_va")
            if va:
                return str(va)
    except Exception:
        pass
    return None


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
    vtable_yaml_path = os.path.join(new_binary_dir, f"C_GameRules_vtable.{platform}.yaml")
    vtable_va = _read_vtable_va(vtable_yaml_path)
    if not vtable_va:
        if debug:
            print("    Preprocess: C_GameRules_vtable vtable_va not found, cannot resolve xref_gvs")
        return False

    exclude_vtable_yaml_path = os.path.join(new_binary_dir, f"C_MultiplayRules_vtable.{platform}.yaml")
    exclude_vtable_va = _read_vtable_va(exclude_vtable_yaml_path)
    if not exclude_vtable_va:
        if debug:
            print("    Preprocess: C_MultiplayRules_vtable vtable_va not found, cannot resolve exclude_gvs")
        return False

    func_xrefs = [
        {
            "func_name": "C_GameRules_ctor",
            "xref_strings": [
                "%s:  CGameRules::CGameRules constructed",
            ],
            "xref_gvs": [str(vtable_va)],
            "xref_signatures": [],
            "xref_funcs": [],
            "exclude_funcs": [],
            "exclude_strings": [],
            "exclude_gvs": [str(exclude_vtable_va)],
            "exclude_signatures": [],
        },
    ]

    return await preprocess_common_skill(
        session=session,
        expected_outputs=expected_outputs,
        old_yaml_map=old_yaml_map,
        new_binary_dir=new_binary_dir,
        platform=platform,
        image_base=image_base,
        func_names=TARGET_FUNCTION_NAMES,
        func_xrefs=func_xrefs,
        generate_yaml_desired_fields=GENERATE_YAML_DESIRED_FIELDS,
        debug=debug,
    )
