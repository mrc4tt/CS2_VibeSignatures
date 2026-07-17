#!/usr/bin/env python3
"""Preprocess script for find-UnregisterLoopModeFactory skill (deinline-fix chain, link 1/3).

``UnregisterLoopModeFactory`` is the helper that ``CEngineServiceMgr::UnregisterLoopMode``
tail-calls when the located loop type's ``GetImplType() == 1`` (the ILoopModeFactory case).
It holds the ``ILoopModeFactory::GetLoopModeType`` (vtable +0x20) and
``ILoopModeFactory::Shutdown`` (vtable +0x8) vcalls.

On Linux 14168 this helper is de-inlined out of ``CEngineServiceMgr_UnregisterLoopMode``
(the parent merely ``jmp``s to it), so those two vcalls leave the parent body and the
original ``find-CEngineServiceMgr_UnregisterLoopMode-inlined`` decompile can no longer find
them.  This skill locates the standalone helper by decompiling the parent
(``CEngineServiceMgr_UnregisterLoopMode``) and reporting the ``found_call`` to it, so
``find-CEngineServiceMgr_UnregisterLoopMode-noinline`` can then decompile the helper.

The helper is a separate function only on the de-inlined platform (Linux); on Windows (and
older inlined Linux builds) the parent inlines it and there is no tail-call to report, so
this skill's output is optional and it soft-skips.  It is therefore gated ``platform: linux``
and its output YAML is deliberately NOT registered as a gamedata symbol -- it is an
intermediate consumed only by the ``-noinline`` decompile link.  Skipped whenever the three
final vcall outputs already exist.
"""

from ida_analyze_util import preprocess_common_skill

TARGET_FUNCTION_NAMES = [
    "UnregisterLoopModeFactory",
]

LLM_DECOMPILE = [
    {
        "symbol_name": "UnregisterLoopModeFactory",
        "prompt_path": "prompt/call_llm_decompile.md",
        "reference_yaml_paths": [
            "references/engine/CEngineServiceMgr_UnregisterLoopMode-noinline.{platform}.yaml",
        ],
        "expected_result_sections": ["found_call"],
    },
]

GENERATE_YAML_DESIRED_FIELDS = [
    # (symbol_name, generate_yaml_fields)
    (
        "UnregisterLoopModeFactory",
        ["func_name", "func_sig", "func_va", "func_rva", "func_size"],
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
    """Locate the de-inlined UnregisterLoopModeFactory helper by decompiling CEngineServiceMgr_UnregisterLoopMode."""
    return await preprocess_common_skill(
        session=session,
        expected_outputs=expected_outputs,
        old_yaml_map=old_yaml_map,
        new_binary_dir=new_binary_dir,
        platform=platform,
        image_base=image_base,
        func_names=TARGET_FUNCTION_NAMES,
        llm_decompile_specs=LLM_DECOMPILE,
        llm_config=llm_config,
        generate_yaml_desired_fields=GENERATE_YAML_DESIRED_FIELDS,
        debug=debug,
    )
