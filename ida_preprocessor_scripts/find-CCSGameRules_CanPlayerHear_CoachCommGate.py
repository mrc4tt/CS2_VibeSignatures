#!/usr/bin/env python3
"""Preprocess script for find-CCSGameRules_CanPlayerHear_CoachCommGate.

Patch site in the server's shared voice/text-chat permission core (linux 0x1416be0,
windows 0x1809131f0 on 14196). Both CCSGameRules wrappers call it: the voice one
(linux 0x1416fa0) and the chat one Host_Say reaches for "say_team" (linux 0x14172e0).
For a coach speaker (IsCoach) whose coached team is the listener's team it only
returns true while m_bWarmupPeriod / m_bTerroristTimeOutActive / m_bCTTimeOutActive is
set or m_gamePhase == 4 (halftime) - CS:GO's coach communication restriction, whose
sv_coach_comm_unrestricted bypass CS2 removed.

The site is the first conditional jump (after `cmp byte [gamerules+m_bWarmupPeriod],0`)
to the function's "return true" exit. Making it unconditional (linux 0F 85 -> 90 E9,
windows 75 -> EB; the displacement after the written bytes is kept, so the target does
not change) gives coach -> coached team voice and team chat at all times. Enemies are
still filtered by the team compare before the site. MatchZy applies it at runtime.

Anchor: the shape of the gate itself, the jump followed by the next gamerules flag
compares (`80 B8 <disp32> 00` + jcc). The 14196 baselines came from emit_artifact.py
after a decompile of both binaries (sig maker output, unique on both platforms); later
builds relocate from the previous gamever's patch_sig. emit_artifact wildcards the
schema displacements (0xD9/0xE4/0xE5/0x11C); hand-checked full-offset patterns, each a
single hit on 14196, for re-identifying the site by hand:
  linux   0F 85 ? ? ? ? 80 B8 E4 00 00 00 00 0F 85 ? ? ? ? 80 B8 E5 00 00 00 00
          0F 85 ? ? ? ? 83 B8 1C 01 00 00 04
  windows 75 ? 80 B8 E4 00 00 00 00 75 ? 80 B8 E5 00 00 00 00 75 ? 83 B8 1C 01 00 00 04
"""

from ida_analyze_util import preprocess_common_skill

TARGETS = [
    "CCSGameRules_CanPlayerHear_CoachCommGate",
]

GENERATE_YAML_DESIRED_FIELDS = [
    (
        "CCSGameRules_CanPlayerHear_CoachCommGate",
        [
            "patch_name",
            "patch_va",
            "patch_rva",
            "patch_sig",
            "patch_bytes",
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
    """Relocate the previous gamever's patch artifact onto this build."""
    return await preprocess_common_skill(
        session=session,
        expected_outputs=expected_outputs,
        old_yaml_map=old_yaml_map,
        new_binary_dir=new_binary_dir,
        platform=platform,
        image_base=image_base,
        patch_names=TARGETS,
        generate_yaml_desired_fields=GENERATE_YAML_DESIRED_FIELDS,
        debug=debug,
    )
