#!/usr/bin/env python3
"""Preprocess script for find-SC_DumpWorld_CommandHandler skill."""

from ida_preprocessor_scripts._registerconcommand import (
    preprocess_registerconcommand_skill,
)


TARGET_FUNCTION_NAMES = [
    "SC_DumpWorld_CommandHandler",
]

COMMAND_NAME = "sc_dumpworld"
HELP_STRING = "Dump a list of the objects in a sceneworld (Usage: sc_dumpworld <world_index>)"
SEARCH_WINDOW_BEFORE_CALL = 96
SEARCH_WINDOW_AFTER_XREF = 96

GENERATE_YAML_DESIRED_FIELDS = [
    (
        "SC_DumpWorld_CommandHandler",
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
    _ = skill_name, old_yaml_map
    return await preprocess_registerconcommand_skill(
        session=session,
        expected_outputs=expected_outputs,
        new_binary_dir=new_binary_dir,
        platform=platform,
        image_base=image_base,
        target_name=TARGET_FUNCTION_NAMES[0],
        generate_yaml_desired_fields=GENERATE_YAML_DESIRED_FIELDS,
        command_name=COMMAND_NAME,
        help_string=HELP_STRING,
        rename_to=TARGET_FUNCTION_NAMES[0],
        search_window_before_call=SEARCH_WINDOW_BEFORE_CALL,
        search_window_after_xref=SEARCH_WINDOW_AFTER_XREF,
        debug=debug,
    )
