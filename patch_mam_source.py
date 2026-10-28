#!/usr/bin/env python3
"""patch_mam_source.py - write the generated MultiAddonManager values into its source.

MultiAddonManager reads no gamedata: its signatures and offsets are `constexpr`
literals in src/multiaddonmanager.cpp, the signatures inside an
`#ifdef PLATFORM_WINDOWS ... #else ... #endif`. deploy_local_plugins.sh runs this to
rewrite those literals from gamedata/<VER>/multiaddonmanager/, then commits and
pushes the one file like every other plugin repo. check_deploy_drift.py uses
`differences()` to say whether the source is behind.

Only the literal between the quotes (or the number) is replaced; every other byte of
the file stays as it is. Trailing wildcards are dropped, as the plugin writes them:
they match anything, so "... 8B 55 ?" and "... 8B 55" find the same address.

An offset is one `constexpr int` for both platforms. If the platforms ever disagree,
this refuses rather than pick one - the source then needs an #ifdef by hand.

  uv run patch_mam_source.py -gamever 14192 -source ~/customGIT/MultiAddonManager/src/multiaddonmanager.cpp
  uv run patch_mam_source.py ... -check     # exit 1 and print what differs, write nothing
"""

import argparse
import json
import os
import re
import sys

GAMEDATA_REL = "multiaddonmanager/gamedata/multiaddonmanager.json"

# source variable -> generated key
SIGNATURES = {
    "g_HostStateRequest_Sig": "CHostStateMgr::StartNewRequest",
    "g_ReplyConnection_Sig": "CNetworkGameServer::ReplyConnection",
    "g_ScriptGetAddon_Sig": "ScriptGetAddon",
}
# None since the plugin's b4353a1 (2026-10-26, upstream d2cc398): the server addon
# string and the client list are read through the SDK's
# CNetworkGameServerBase::m_szAddonName and m_Clients instead of the 376/616 literals,
# so they follow the hl2sdk header (sdk_abi_check.sh), not this file. The generator
# still publishes CNetworkGameServer::ServerAddons/ClientList; requiring the literals
# failed the 14193 deploy with "expected one 'constexpr int g_iServerAddonsOffset'".
OFFSETS = {}


class PatchError(Exception):
    pass


def normalize_sig(sig):
    tokens = sig.split()
    while tokens and tokens[-1] in ("?", "??"):
        tokens.pop()
    return " ".join(tokens)


def wanted_values(gamedata):
    """{(variable, platform or None): value} from the generated file."""
    wanted = {}
    for var, key in SIGNATURES.items():
        sigs = gamedata[key]["signatures"]
        for platform in ("windows", "linux"):
            wanted[(var, platform)] = normalize_sig(sigs[platform])
    for var, key in OFFSETS.items():
        offsets = gamedata[key]["offsets"]
        if offsets["windows"] != offsets["linux"]:
            raise PatchError(
                f"{key}: windows {offsets['windows']} != linux {offsets['linux']}; "
                f"{var} is one constexpr for both platforms - split it with #ifdef by hand"
            )
        wanted[(var, None)] = int(offsets["linux"])
    return wanted


def _platform_blocks(text):
    """(start, end) of the windows and linux halves of the signature #ifdef."""
    match = re.search(
        r"#ifdef PLATFORM_WINDOWS\n(?P<win>(?:constexpr const char \*\w+ = \"[^\"]*\";\n)+)"
        r"#else\n(?P<lin>(?:constexpr const char \*\w+ = \"[^\"]*\";\n)+)#endif",
        text,
    )
    if not match:
        raise PatchError("signature #ifdef PLATFORM_WINDOWS block not found")
    return {"windows": match.span("win"), "linux": match.span("lin")}


def _sig_pattern(var):
    return re.compile(r'(constexpr const char \*%s = ")([^"]*)(";)' % re.escape(var))


def _offset_pattern(var):
    return re.compile(r"(constexpr int %s = )(\d+)(;)" % re.escape(var))


def current_values(text):
    blocks = _platform_blocks(text)
    current = {}
    for var in SIGNATURES:
        for platform, (start, end) in blocks.items():
            match = _sig_pattern(var).search(text, start, end)
            if not match:
                raise PatchError(f"{var} not found in the {platform} block")
            current[(var, platform)] = normalize_sig(match.group(2))
    for var in OFFSETS:
        matches = _offset_pattern(var).findall(text)
        if len(matches) != 1:
            raise PatchError(f"expected one 'constexpr int {var}', found {len(matches)}")
        current[(var, None)] = int(matches[0][1])
    return current


def differences(gamedata, text):
    """[(variable, platform, source value, generated value)] for every literal that differs."""
    wanted = wanted_values(gamedata)
    current = current_values(text)
    return [
        (var, platform, current[(var, platform)], value)
        for (var, platform), value in sorted(wanted.items(), key=lambda kv: (kv[0][0], kv[0][1] or ""))
        if current[(var, platform)] != value
    ]


def patch(gamedata, text):
    wanted = wanted_values(gamedata)
    current_values(text)  # every literal must be found before anything is replaced

    # Replace from the end backwards so the block offsets stay valid.
    edits = []
    for platform, (start, end) in _platform_blocks(text).items():
        for var in SIGNATURES:
            match = _sig_pattern(var).search(text, start, end)
            edits.append((match.start(2), match.end(2), wanted[(var, platform)]))
    for var in OFFSETS:
        match = _offset_pattern(var).search(text)
        edits.append((match.start(2), match.end(2), str(wanted[(var, None)])))
    for start, end, value in sorted(edits, reverse=True):
        text = text[:start] + value + text[end:]
    return text


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-gamever", required=True)
    parser.add_argument("-source", required=True, help="path to src/multiaddonmanager.cpp")
    parser.add_argument("-outputdir", default=None, help="default: gamedata/<gamever>")
    parser.add_argument("-check", action="store_true", help="report differences, write nothing")
    args = parser.parse_args()

    dist = os.path.join(args.outputdir or os.path.join("gamedata", args.gamever), GAMEDATA_REL)
    with open(dist, encoding="utf-8") as handle:
        gamedata = json.load(handle)
    source = os.path.expanduser(args.source)
    with open(source, encoding="utf-8", newline="") as handle:
        text = handle.read()

    try:
        diffs = differences(gamedata, text)
        if args.check or not diffs:
            for var, platform, have, want in diffs:
                print(f"  {var} [{platform or 'both'}]\n      source    {have}\n      generated {want}")
            print(f"  {len(diffs)} literal(s) differ in {source}" if diffs else f"  = in sync: {source}")
            return 1 if diffs else 0
        patched = patch(gamedata, text)
    except PatchError as error:
        print(f"  ❌ {source}: {error}", file=sys.stderr)
        return 2

    with open(source, "w", encoding="utf-8", newline="") as handle:
        handle.write(patched)
    for var, platform, have, want in diffs:
        print(f"  ✔ {var} [{platform or 'both'}]: {have} -> {want}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
