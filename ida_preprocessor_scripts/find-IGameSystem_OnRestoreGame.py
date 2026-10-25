#!/usr/bin/env python3
"""Preprocess script for find-IGameSystem_OnRestoreGame skill."""

from ida_preprocessor_scripts._igamesystem_dispatch_common import (
    preprocess_igamesystem_dispatch_skill,
)


SOURCE_YAML_STEM = "CSource2Server_OnStreamEntitiesFromFileCompleted"
TARGET_SPECS = [
    # windows carries a func_sig across the boundary (the body is `ret 0`) since 14185
    {
        "target_name": "IGameSystem_OnRestoreGame",
        "rename_to": "GameSystem_OnRestoreGame",
        "func_sig_platforms": ["windows"],
    },
]
VIA_INTERNAL_WRAPPER = False
INTERNAL_RENAME_TO = None
MULTI_ORDER = "scan"
# CSource2Server_OnStreamEntitiesFromFileCompleted, the upstream source, is a bare `ret` by
# 14185, so the dispatch (linux `mov esi, 0x199` + IGameSystem dispatch call, windows a
# callback doing `jmp [rax+0x198]`) is found in the function that prints its own name:
# CEntity2SaveRestore's EndRestoreEntities (14192: linux 0x170d090, windows 0x180bfa370).
# Both reference this string alone and carry exactly one dispatch, slot 51.
SOURCE_STRING = '%s:  EndRestoreEntities( %s%s )\n'


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
