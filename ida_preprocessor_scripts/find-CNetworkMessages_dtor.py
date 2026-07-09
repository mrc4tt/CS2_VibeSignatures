#!/usr/bin/env python3
"""Preprocess script for find-CNetworkMessages_dtor skill.

Virtual function (last vtable slots). Primary path reuses the previous gamever's
func_sig / vfunc metadata to relocate. Fallback: the destructor writes its own
class vtable pointer, so xref the CNetworkMessages vtable global to recover it.
FUNC_VTABLE_RELATIONS supplies the vtable_name metadata for the output YAML.
"""

import os

try:
    import yaml
except ImportError:
    yaml = None

from ida_analyze_util import preprocess_common_skill

TARGET_FUNCTION_NAMES = [
    "CNetworkMessages_dtor",
]

FUNC_VTABLE_RELATIONS = [
    # (func_name, vtable_class)
    ("CNetworkMessages_dtor", "CNetworkMessages"),
]

GENERATE_YAML_DESIRED_FIELDS = [
    # (symbol_name, generate_yaml_fields)
    (
        "CNetworkMessages_dtor",
        [
            "func_name",
            "func_sig",
            "func_va",
            "func_rva",
            "func_size",
            "vtable_name",
            "vfunc_offset",
            "vfunc_index",
        ],
    ),
]


def _read_vtable_va(yaml_path):
    """Read vtable_va from a vtable YAML file, returning it as a hex string or None."""
    if yaml is None:
        return None
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
    """Reuse old func_sig/vfunc metadata first; fallback to vtable-ptr xref."""
    _ = skill_name

    # Fallback anchor: the dtor writes *this = CNetworkMessages_vtable, so it
    # references the vtable global. On Linux that reference points at the
    # _ZTV symbol = vtable_va - 0x10; on Windows it is the vtable_va directly.
    func_xrefs = None
    vtable_yaml_path = os.path.join(
        new_binary_dir, "CNetworkMessages_vtable.%s.yaml" % platform
    )
    vtable_va = _read_vtable_va(vtable_yaml_path)
    if vtable_va:
        xref_va = (
            vtable_va
            if platform == "windows"
            else hex(int(vtable_va, 16) - 0x10)
        )
        func_xrefs = [
            {
                "func_name": "CNetworkMessages_dtor",
                "xref_strings": [],
                "xref_gvs": [xref_va],
                "xref_signatures": [],
                "xref_funcs": [],
                "exclude_funcs": [],
                "exclude_strings": [],
                "exclude_gvs": [],
                "exclude_signatures": [],
            },
        ]
    elif debug:
        print("    Preprocess: CNetworkMessages_vtable vtable_va not found, "
              "relying on func_sig reuse only")

    return await preprocess_common_skill(
        session=session,
        expected_outputs=expected_outputs,
        old_yaml_map=old_yaml_map,
        new_binary_dir=new_binary_dir,
        platform=platform,
        image_base=image_base,
        func_names=TARGET_FUNCTION_NAMES,
        func_xrefs=func_xrefs,
        func_vtable_relations=FUNC_VTABLE_RELATIONS,
        generate_yaml_desired_fields=GENERATE_YAML_DESIRED_FIELDS,
        debug=debug,
    )
