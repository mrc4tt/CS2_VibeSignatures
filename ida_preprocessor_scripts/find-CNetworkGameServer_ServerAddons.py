#!/usr/bin/env python3
"""Relocate CNetworkGameServer_ServerAddons from the previous gamever's offset_sig.

The server's addon string (a CUtlString pointer, size 8) that ReplyConnection logs
as "[addons:'%s']"; MultiAddonManager swaps it per client around the original call.
0x178 (376) on both platforms on 14192, read by ReplyConnection at linux 0x515b92
("mov r14, [r12+178h]") and windows 0x1800a5aeb ("mov rax, [r13+178h]").

When relocation fails, the anchor for the agent fallback is that function
(CNetworkGameServerBase_ReplyConnection): the member is the pointer loaded from
`this` and passed as the second %s of "Sending S2C_CONNECTION to %s [addons:'%s']".
"""

from ida_analyze_util import preprocess_common_skill

TARGET_STRUCT_MEMBER_NAMES = ["CNetworkGameServer_ServerAddons"]

GENERATE_YAML_DESIRED_FIELDS = [
    (
        "CNetworkGameServer_ServerAddons",
        ["struct_name", "member_name", "offset", "size", "offset_sig", "offset_sig_disp"],
    )
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
    """Use the shared struct_member relocation and YAML writer for either platform."""
    return await preprocess_common_skill(
        session=session,
        expected_outputs=expected_outputs,
        old_yaml_map=old_yaml_map,
        new_binary_dir=new_binary_dir,
        platform=platform,
        image_base=image_base,
        struct_member_names=TARGET_STRUCT_MEMBER_NAMES,
        generate_yaml_desired_fields=GENERATE_YAML_DESIRED_FIELDS,
        debug=debug,
    )
