#!/usr/bin/env python3
<<<<<<< HEAD
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
=======
"""Deterministic preprocessor for the CNetworkMessages destructor vfunc."""

import os
from pathlib import Path

from ida_analyze_util import preprocess_gen_func_sig_via_mcp, write_func_yaml
from trusted_yaml import load_yaml_file

TARGET_FUNCTION_NAMES = ["CNetworkMessages_dtor"]
VTABLE_CLASS = "CNetworkMessages"

GENERATE_YAML_DESIRED_FIELDS = [
>>>>>>> upstream/main
    (
        "CNetworkMessages_dtor",
        [
            "func_name",
<<<<<<< HEAD
            "func_sig",
            "func_va",
            "func_rva",
            "func_size",
=======
            "func_va",
            "func_rva",
            "func_size",
            "func_sig",
>>>>>>> upstream/main
            "vtable_name",
            "vfunc_offset",
            "vfunc_index",
        ],
    ),
]


<<<<<<< HEAD
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
=======
def _resolve_destructor_slot(vtable_payload, platform):
    if not isinstance(vtable_payload, dict) or vtable_payload.get("vtable_class") != VTABLE_CLASS:
        return None
    if platform not in {"windows", "linux"}:
        return None

    try:
        count = int(vtable_payload["vtable_numvfunc"])
        entries = {int(index): int(str(address), 0) for index, address in vtable_payload["vtable_entries"].items()}
    except (AttributeError, KeyError, TypeError, ValueError):
        return None
    if count < 3 or set(entries) != set(range(count)):
        return None

    # MSVC exposes the scalar-deleting destructor in the final slot. The
    # Itanium ABI exposes the complete and deleting destructors as the final
    # pair; the source-owned symbol represents the complete destructor.
    index = count - 1 if platform == "windows" else count - 2
    func_va = entries.get(index)
    if func_va is None or func_va <= 0:
        return None
    return index, func_va


def _resolve_target_output(expected_outputs, new_binary_dir, platform):
    expected_basename = f"{TARGET_FUNCTION_NAMES[0]}.{platform}.yaml"
    module_root = Path(new_binary_dir).resolve()
    matches = [
        os.fspath(Path(path))
        for path in expected_outputs
        if Path(path).name == expected_basename and Path(path).resolve().parent == module_root
    ]
    return matches[0] if len(matches) == 1 else None
>>>>>>> upstream/main


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
<<<<<<< HEAD
    """Reuse old func_sig/vfunc metadata first; fallback to vtable-ptr xref."""
    _ = skill_name

    # Fallback anchor: the dtor writes *this = CNetworkMessages_vtable, so it
    # references the vtable global. On Linux that reference points at the
    # _ZTV symbol = vtable_va - 0x10; on Windows it is the vtable_va directly.
    func_xrefs = None
    vtable_yaml_path = os.path.join(new_binary_dir, "CNetworkMessages_vtable.%s.yaml" % platform)
    vtable_va = _read_vtable_va(vtable_yaml_path)
    if vtable_va:
        xref_va = vtable_va if platform == "windows" else hex(int(vtable_va, 16) - 0x10)
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
        print("    Preprocess: CNetworkMessages_vtable vtable_va not found, relying on func_sig reuse only")

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
=======
    """Resolve the ABI destructor slot and emit a freshly generated func_sig."""
    _ = skill_name, old_yaml_map
    target_output = _resolve_target_output(expected_outputs, new_binary_dir, platform)
    if target_output is None:
        if debug:
            print("    Preprocess: expected exactly one in-module CNetworkMessages_dtor output")
        return False

    vtable_path = Path(new_binary_dir) / f"{VTABLE_CLASS}_vtable.{platform}.yaml"
    try:
        vtable_payload = load_yaml_file(vtable_path)
    except Exception:
        if debug:
            print(f"    Preprocess: failed to read {vtable_path.name}")
        return False

    resolved = _resolve_destructor_slot(vtable_payload, platform)
    if resolved is None:
        if debug:
            print(f"    Preprocess: invalid {VTABLE_CLASS} ABI destructor layout for {platform}")
        return False
    vfunc_index, func_va = resolved

    generated = await preprocess_gen_func_sig_via_mcp(
        session=session,
        func_va=func_va,
        image_base=image_base,
        allow_across_function_boundary=False,
        debug=debug,
    )
    required_generated_fields = {"func_va", "func_rva", "func_size", "func_sig"}
    if not isinstance(generated, dict) or not required_generated_fields <= generated.keys():
        if debug:
            print(f"    Preprocess: deterministic func_sig generation failed for {hex(func_va)}")
        return False
    try:
        generated_func_va = int(str(generated["func_va"]), 0)
    except (TypeError, ValueError):
        return False
    if generated_func_va != func_va or not generated.get("func_sig"):
        return False

    payload = {
        "func_name": TARGET_FUNCTION_NAMES[0],
        **generated,
        "vtable_name": VTABLE_CLASS,
        "vfunc_offset": hex(vfunc_index * 8),
        "vfunc_index": vfunc_index,
    }
    write_func_yaml(target_output, payload)
    return True
>>>>>>> upstream/main
