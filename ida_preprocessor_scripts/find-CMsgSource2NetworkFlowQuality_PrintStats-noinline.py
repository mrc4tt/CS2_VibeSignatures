#!/usr/bin/env python3
"""Preprocess script for find-CMsgSource2NetworkFlowQuality_PrintStats-noinline skill.

Resolves ``CMsgSource2NetworkFlowQuality_PrintStats`` as the thin guard wrapper that
forwards into the standalone ``CMsgSource2NetworkFlowQuality_PrintStatsInternal``.  This
path only applies when the printing body is *de-inlined* into a separate ``PrintStatsInternal``
function AND the ``if (this->m_bReady)`` guard is extracted into its own ~0x15-byte wrapper
function (Linux 14168+):

    CMsgSource2NetworkFlowQuality::PrintStats(this, buf):   ; the wrapper we want
        mov  eax, [rdi+28h]        ; 8B 47 28   -- read the guard flag
        test eax, eax              ; 85 C0
        jnz  short L               ; 75 xx
        retn                       ; C3
    L:  jmp  PrintStatsInternal    ; E9 ..      -- tail call into the body

There the registered ``PrintStats`` symbol is that wrapper (which ``CEngineServer_DumpNetStats``
calls), NOT the string-bearing body.  On such builds the callers of ``PrintStatsInternal`` are
exactly the wrapper and ``CNetworkGameClient_PrintNetStats`` (which calls ``Internal`` directly).

Two candidate sources are intersected so the fused builds soft-skip cleanly:
  * ``xref_funcs: [PrintStatsInternal]`` -- callers of the body.
  * ``xref_signatures: ["8B 47 ?? 85 C0"]`` -- ``mov eax,[rdi+disp8]; test eax,eax``, the guard
    head that is unique to the extracted wrapper.  This is what distinguishes the wrapper from
    the *fused* case: when the guard is inlined into its callers instead of extracted (Linux
    <= 14167, Windows), those callers (e.g. ``CEngineServer_DumpNetStats``) read the flag via a
    different register / with the ``test`` separated from the ``mov`` by a std::function setup,
    so they do NOT contain this contiguous head and drop out of the intersection.
``exclude_funcs: [CNetworkGameClient_PrintNetStats]`` removes the other body caller.

When the body is *inlined into a fused ``PrintStats``* (Windows on all observed builds; Linux
<= 14167 where the guard is inlined into each caller), no extracted wrapper exists:
  * Windows: the ``find-CMsgSource2NetworkFlowQuality_PrintStatsInternal`` helper is
    ``platform: linux`` and does not run, so no ``PrintStatsInternal.windows.yaml`` exists; the
    ``xref_funcs`` callee cannot be resolved and this skill legitimately produces nothing.
  * Linux <= 14167: ``Internal`` resolves to the fused body, whose callers are
    ``DumpNetStats`` and ``PrintNetStats``; neither contains the guard head, so the signature
    intersection is empty and this skill soft-skips.
In both cases ``find-CMsgSource2NetworkFlowQuality_PrintStats-inlined`` runs instead and
resolves the fused body directly from the ``"Bandwidth"`` string.

``PrintStats`` is a regular function (not a vfunc), so ``func_sig`` is its stable
cross-build locator and is retained (the de-inlined wrapper signs uniquely at its head).
"""

from ida_analyze_util import preprocess_common_skill

TARGET_FUNCTION_NAMES = [
    "CMsgSource2NetworkFlowQuality_PrintStats",
]

FUNC_XREFS = [
    {
        "func_name": "CMsgSource2NetworkFlowQuality_PrintStats",
        "xref_strings": [],
        "xref_gvs": [],
        "xref_signatures": ["8B 47 ?? 85 C0"],
        "xref_funcs": ["CMsgSource2NetworkFlowQuality_PrintStatsInternal"],
        "exclude_funcs": ["CNetworkGameClient_PrintNetStats"],
        "exclude_strings": [],
        "exclude_gvs": [],
        "exclude_signatures": [],
    },
]

GENERATE_YAML_DESIRED_FIELDS = [
    # (symbol_name, generate_yaml_fields)
    (
        "CMsgSource2NetworkFlowQuality_PrintStats",
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
