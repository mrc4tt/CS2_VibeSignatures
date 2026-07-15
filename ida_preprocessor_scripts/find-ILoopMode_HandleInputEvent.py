#!/usr/bin/env python3
"""Preprocess script for find-ILoopMode_HandleInputEvent skill.

ILoopMode::HandleInputEvent is an abstract-interface vfunc dispatched by the
thin thunk CLoopTypeClientServerService_HandleInputEvent, whose body ends in a
single indirect vtable call. The vfunc slot is resolved deterministically by
scanning that thunk for its unique indirect vcall -- no LLM decompile and no
fragile across-boundary vfunc_sig on a short ``jmp [reg+disp8]``.

The dispatch shape differs per platform. Windows/MSVC emits it directly as a
memory-indirect ``jmp qword ptr [rax+28h]``. Linux/GCC instead devirtualizes it
into a speculative guard: it loads the slot (``mov rax, [rax+28h]``), compares
it against the inlined default implementation (``cmp rax, rcx`` / ``jz`` ->
inline ``xor eax, eax; retn``) and only falls through to a register-indirect
``jmp rax`` in the general case. resolve_load_then_branch is enabled so the scan
traces that ``jmp rax`` back over the control-flow graph -- past the guard's
not-taken edge -- to the reaching ``mov rax, [rax+28h]`` load, so both platforms
resolve to the same slot (offset 0x28).
"""

from ida_preprocessor_scripts._indirect_vcall_target_common import (
    preprocess_indirect_vcall_target_skill,
)

SOURCE_FUNCTION_NAME = "CLoopTypeClientServerService_HandleInputEvent"

TARGET_FUNCTION_NAME = "ILoopMode_HandleInputEvent"
VTABLE_CLASS = "ILoopMode"

GENERATE_YAML_DESIRED_FIELDS = [
    # (symbol_name, generate_yaml_fields) -- slot-only output for an abstract interface vfunc
    (
        "ILoopMode_HandleInputEvent",
        [
            "func_name",
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
    """Scan the CLoopTypeClientServerService_HandleInputEvent thunk for its unique indirect vcall."""
    _ = skill_name, old_yaml_map, image_base

    return await preprocess_indirect_vcall_target_skill(
        session=session,
        expected_outputs=expected_outputs,
        new_binary_dir=new_binary_dir,
        platform=platform,
        source_yaml_stem=SOURCE_FUNCTION_NAME,
        target_name=TARGET_FUNCTION_NAME,
        vtable_name=VTABLE_CLASS,
        generate_yaml_desired_fields=GENERATE_YAML_DESIRED_FIELDS,
        resolve_load_then_branch=True,
        debug=debug,
    )
