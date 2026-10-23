#!/usr/bin/env python3
"""Preprocess script for find-CPlayer_ObserverServices_IsValidObserverTarget skill.

Relocation constrained by the class's vtable. The function carries no string of its
own (no profiling scope, no message), so there is nothing to xref; what pins it is
its slot in CPlayer_ObserverServices. FUNC_VTABLE_RELATIONS makes the slot
enrichment fail - and the relocation with it - when the relocated address is not an
entry of that vtable, so a stale sig that lands on another function is rejected
instead of shipped.

Fork-owned with no earlier baseline: the 14192 artifacts were written with
emit_artifact.py from the plugin's own signatures, confirmed first (rule 12):
  linux   0x17c3620,   unique match, slot 35 of the primary CPlayer_ObserverServices
          vtable (39 entries)
  windows 0x180c7df70, unique match, slot 34 (38 entries) - MSVC one lower, and the
          table one shorter, as the class's other virtuals
The decompile is the observer-target test: null target, the target's own virtual
alive check, not the observer's own pawn, EF_NODRAW (0x20) rejected, observer mode
and a death-time + 6.0 s window, then the mp_forcecamera team rule.

The plugin key is the alias CPlayer_ObserverServices::IsValidObserverTarget.
"""

from ida_analyze_util import preprocess_common_skill

TARGET_FUNCTION_NAMES = [
    "CPlayer_ObserverServices_IsValidObserverTarget",
]

FUNC_VTABLE_RELATIONS = [
    # (func_name, vtable_class)
    ("CPlayer_ObserverServices_IsValidObserverTarget", "CPlayer_ObserverServices"),
]

GENERATE_YAML_DESIRED_FIELDS = [
    # (symbol_name, generate_yaml_fields)
    (
        "CPlayer_ObserverServices_IsValidObserverTarget",
        [
            "func_name",
            "func_va",
            "func_rva",
            "func_size",
            "func_sig",
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
    """Reuse previous gamever func_sig to locate target function(s) and write YAML."""
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
