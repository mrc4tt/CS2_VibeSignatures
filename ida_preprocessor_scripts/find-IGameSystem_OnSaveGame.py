#!/usr/bin/env python3
"""Preprocess script for find-IGameSystem_OnSaveGame skill."""

from ida_preprocessor_scripts._igamesystem_dispatch_common import (
    preprocess_igamesystem_dispatch_skill,
)

SOURCE_YAML_STEM = "CEntitySaveRestoreBlockHandler_PreSave"
TARGET_SPECS = [
    {"target_name": "IGameSystem_OnSaveGame", "rename_to": "GameSystem_OnSaveGame"},
]
VIA_INTERNAL_WRAPPER = False
INTERNAL_RENAME_TO = None
MULTI_ORDER = "scan"
# CEntitySaveRestoreBlockHandler_PreSave, the upstream source, no longer dispatches it;
# CEntity2SaveRestore::StreamEntitiesToFile does (14192: linux 0x1752250, windows
# 0x180c32b30). Both reference this string alone and carry exactly one dispatch, slot 50.
SOURCE_STRING = "%s:  StreamEntitiesToFile:  '%s' [%d entities]\n"


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
    """Resolve target function(s) via IGameSystem dispatch and write YAML."""
    _ = skill_name, old_yaml_map
    return await preprocess_igamesystem_dispatch_skill(
        session=session,
        expected_outputs=expected_outputs,
        new_binary_dir=new_binary_dir,
        platform=platform,
        image_base=image_base,
        source_yaml_stem=SOURCE_YAML_STEM,
        target_specs=TARGET_SPECS,
        via_internal_wrapper=VIA_INTERNAL_WRAPPER,
        internal_rename_to=INTERNAL_RENAME_TO,
        multi_order=MULTI_ORDER,
        source_string=SOURCE_STRING,
        debug=debug,
    )
