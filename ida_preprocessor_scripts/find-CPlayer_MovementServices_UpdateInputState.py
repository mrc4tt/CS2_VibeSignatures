#!/usr/bin/env python3
"""Preprocess script for find-CPlayer_MovementServices_UpdateInputState skill.

String-anchored rather than relocation-only, because this symbol is fork-owned and
has no baseline in any earlier gamever. The anchor is the function's own profiling
scope name, which it loads together with its source file and line:

    "UpdateInputState", "../../game/shared/player_movementservices.cpp", 276

HvH.gg TeleportFix hooks this function as "RunCommand" (this = movement services,
arg 2 = CUserCmd*), so the downstream key is an alias, not the symbol's name.

Confirmed on 14185 (rule 12 - a unique sig match alone would only prove *a* function
head was found):
  linux   0x17c36c0,   the only xref of the string (lea at 0x17c36d2); the
          CCSPlayer_MovementServices override in vtable slot 24 (0x15d92f0) calls it
          first, and the plugin's own 14181 signature resolves to the function in
          the same position (slot 24 of that build calls it the same way).
  windows 0x180c7ad40, the only xref of the string; called first by the override in
          slot 23 (0x180ae4260) - MSVC is one slot lower in this class, as with
          PlayerRunCommand (26 linux / 25 windows).

`preprocess_common_skill` still tries relocation first, so from the gamever after
the first one this costs nothing; the xref is the fallback for the first run and for
any run whose baseline sig has gone stale.
"""

from ida_analyze_util import preprocess_common_skill

TARGET_FUNCTION_NAMES = [
    "CPlayer_MovementServices_UpdateInputState",
]

FUNC_XREFS = [
    {
        "func_name": "CPlayer_MovementServices_UpdateInputState",
        "xref_strings": [
            "FULLMATCH:UpdateInputState",
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
    # (symbol_name, generate_yaml_fields)
    (
        "CPlayer_MovementServices_UpdateInputState",
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
    """Reuse previous gamever func_sig to locate target function(s) and write YAML."""
    return await preprocess_common_skill(
        session=session,
        expected_outputs=expected_outputs,
        old_yaml_map=old_yaml_map,
        new_binary_dir=new_binary_dir,
        platform=platform,
        image_base=image_base,
        func_names=TARGET_FUNCTION_NAMES,
        func_xrefs=FUNC_XREFS,
        generate_yaml_desired_fields=GENERATE_YAML_DESIRED_FIELDS,
        debug=debug,
    )
