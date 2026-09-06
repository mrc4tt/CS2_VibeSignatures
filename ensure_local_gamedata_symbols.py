#!/usr/bin/env python3
"""Ensure every symbol from the local plugin gamedata seeds is analyzable in an
analysis config.

Reads every entry from the seed files below (weaponpaints, matchzy, bot-controller,
bot-hider) and injects into the server module of the given config:

  - a find-task (skills:)        name: find-<symbol>, expected_output <symbol>.{platform}.yaml
  - a symbol entry (symbols:)    category derived from the gamedata entry:
                                     signatures       -> func
                                     offsets + m_*    -> structmember (struct: + member:)
                                     offsets + method -> vfunc
  - an alias for ::-style keys so gamedata key names resolve to symbol names
  - a SKILL.md under .claude/skills/find-<symbol>/ when one does not already exist

Idempotent per symbol: already-present symbols are skipped, so newly added gamedata
entries are picked up on the next run without duplicating existing ones.

Usage:
  uv run ensure_local_gamedata_symbols.py -config configs/14178b.yaml
  uv run ensure_local_gamedata_symbols.py            # newest configs/<GAMEVER>.yaml
"""

import argparse
import glob
import json
import os
import re
import sys

SEEDS = [
    "gamedata-generators/weaponpaints/gamedata/weaponpaints.json",
    "gamedata-generators/matchzy/gamedata/matchzy.json",
    "gamedata-generators/bot-controller/gamedata/bot-controller.json",
    "gamedata-generators/bot-hider/gamedata/bot-hider.json",
]

SKILLS_DIR = ".claude/skills"

# BotProfile er en non-polymorphic POD (ingen vtable) - offset-entries er structmembers.
# Member-navne fra Bot-Improver referencegamedata (IDA-verificeret 14178b: POD, win==linux).
BOTPROFILE_MEMBERS = {
    "Aggression": "m_aggression", "Skill": "m_skill", "Teamwork": "m_teamwork",
    "WeaponPref": "m_weaponPreference", "WeaponPrefCount": "m_weaponPreferenceCount",
    "Cost": "m_cost", "Difficulty": "m_difficultyFlags", "ReactionTime": "m_reactionTime",
    "AttackDelay": "m_attackDelay",
    "LookAngleMaxAccelAttacking": "m_lookAngleMaxAccelAttacking",
    "LookAngleStiffnessAttacking": "m_lookAngleStiffnessAttacking",
    "LookAngleDampingAttacking": "m_lookAngleDampingAttacking",
}

# Renamed engine symbols: old gamedata keys map to the canonical analyzed symbol via
# config aliases instead of separate analysis tasks.
ALIAS_OVERRIDES = {
    "CCSPlayerController_HandleCommandJoinTeam": "CBasePlayerController_HandleCommand_JoinTeam",
    "CCSPlayerController_HandleCommand_JoinTeam": "CBasePlayerController_HandleCommand_JoinTeam",
    # IDA-verified 14178b: matchzy's GetSlot sig targets the same function upstream
    # analyzes as CCSPlayer_WeaponServices_Weapon_GetSlot (pseudocode confirmed).
    "CCSPlayer_WeaponServices::GetSlot": "CCSPlayer_WeaponServices_Weapon_GetSlot",
}


def newest_config():
    candidates = glob.glob("configs/*.yaml")
    numeric = [c for c in candidates if re.fullmatch(r"configs/\d+[a-z]?\.yaml", c)]
    if not numeric:
        return None
    return max(numeric, key=lambda p: (len(p), p))


def load_seed_specs():
    """Derive (symbol_name, category, struct, member, alias, lib) for every seed entry."""
    specs = []
    for seed in SEEDS:
        if not os.path.exists(seed):
            print(f"  warning: seed missing, skipping: {seed}")
            continue
        with open(seed, "r", encoding="utf-8") as f:
            gamedata = json.load(f)
        for key, entry in gamedata.items():
            symbol_name = ALIAS_OVERRIDES.get(key, key.replace("::", "_"))
            alias = key if key != symbol_name else None
            lib = (entry.get("signatures", {}) or {}).get("library") or entry.get("library")
            if "signatures" in entry:
                specs.append((symbol_name, "func", None, None, alias, lib))
                continue
            cls, _, method = key.partition("::")
            if method.startswith("m_"):
                specs.append((symbol_name, "structmember", cls, method, alias, lib))
            elif cls in ("CEntityIdentity", "CMoveData") and method:
                # layout-holder-klasser: offset-entries er structmembers (agent-verificeret 14178b)
                specs.append((symbol_name, "structmember", cls, method, alias, lib))
            elif symbol_name.startswith("BotProfile_") and symbol_name[len("BotProfile_"):] in BOTPROFILE_MEMBERS:
                # BotProfile er en non-polymorphic POD - offset-entries er structmembers
                # (IDA-verificeret 14178b: m_attackDelay +0x5C; Bot-Improver reference).
                specs.append((symbol_name, "structmember", "BotProfile",
                              BOTPROFILE_MEMBERS[symbol_name[len("BotProfile_"):]], alias, lib))
            else:
                specs.append((symbol_name, "vfunc", None, None, alias, lib))
    return specs


def find_task_block(symbol_name):
    return (
        f"      - name: find-{symbol_name}\n"
        f"        expected_output:\n"
        f"          - {symbol_name}.{{platform}}.yaml\n"
    )


def symbol_entry_block(symbol_name, category, struct, member, alias):
    lines = [f"      - name: {symbol_name}", f"        category: {category}"]
    if category == "structmember":
        lines.append(f"        struct: {struct}")
        lines.append(f"        member: {member}")
    if alias:
        lines.append("        alias:")
        lines.append(f"          - {alias}")
    return "".join(line + "\n" for line in lines)


def struct_entry_block(struct):
    return f"      - name: {struct}\n        category: struct\n"


def write_skill(symbol_name, category, struct, alias):
    display = alias or symbol_name
    if category == "func":
        kind_hint = (
            f"This is a non-virtual function - emit a byte signature (func_sig), not an offset.\n"
            f"Locate it via cross-references, distinctive constants/strings in its body, or callers\n"
            f"of related symbols; verify by decompilation before committing to a candidate."
        )
        output = (
            "Write the YAML file `<symbol>.{platform}.yaml` with EXACTLY these fields:\n"
            "```yaml\n"
            "func_name: <SYMBOL_NAME>\n"
            "func_va: \"<hex virtual address>\"\n"
            "func_rva: \"<hex rva>\"\n"
            "func_size: \"<hex size>\"\n"
            "func_sig: \"<byte pattern, ?? wildcards, function head, minimal-unique>\"\n"
            "```\n"
            "NEVER include vfunc_index, vfunc_offset, vfunc_sig or vtable_name."
        )
    elif category == "vfunc":
        kind_hint = (
            f"This gamedata entry is stored as an OFFSET. Determine TRUTHFULLY which of the two\n"
            f"it is: (a) a vtable slot of a POLYMORPHIC class (RTTI/vtable present) -> emit the\n"
            f"vfunc schema, or (b) a plain struct member of a NON-POLYMORPHIC class (no RTTI/vtable;\n"
            f"e.g. config-style POD structs like BotProfile) -> emit the structmember schema.\n"
            f"Never guess: if no vtable exists for the class, it is case (b)."
        )
        output = (
            "Write the YAML file `<symbol>.{platform}.yaml` with EXACTLY these fields:\n"
            "```yaml\n"
            "func_name: <SYMBOL_NAME>\n"
            "func_va: \"<hex virtual address>\"\n"
            "func_rva: \"<hex rva>\"\n"
            "func_size: \"<hex size>\"\n"
            "vtable_name: <owning class RTTI name>\n"
            "vfunc_offset: \"<hex vtable byte offset>\"\n"
            "vfunc_index: <decimal slot index>\n"
            "```\n"
            "NEVER include func_sig."
        )
    else:
        kind_hint = (
            f"This is a STRUCT MEMBER OFFSET (schema netvar), not a function. Resolve the\n"
            f"{struct} class layout via the schema/network system; the member must satisfy\n"
            f"natural alignment. Cross-check with functions that dereference the member."
        )
        output = (
            "Write the YAML file `<symbol>.{platform}.yaml` with EXACTLY these fields:\n"
            "```yaml\n"
            "struct_name: <owning class name>\n"
            "member_name: <member name>\n"
            "offset: \"<hex byte offset as string>\"\n"
            "size: <member size in bytes, decimal>\n"
            "offset_sig: \"<short byte pattern of an instruction touching the offset>\"\n"
            "```\n"
            "NEVER include func_* or vfunc_* fields."
        )

    skill_dir = os.path.join(SKILLS_DIR, f"find-{symbol_name}")
    skill_path = os.path.join(skill_dir, "SKILL.md")
    if os.path.exists(skill_path):
        return
    os.makedirs(skill_dir, exist_ok=True)
    body = f"""---
name: find-{symbol_name}
description: |
  Locate {display} in CS2 server.dll / libserver.so via IDA Pro MCP and emit a fresh, minimal-unique
  signature or offset for the local gamedata entry "{display}" (symbol {symbol_name}). {kind_hint}
  Trigger: {symbol_name}, {display}
disable-model-invocation: true
---

# Find {symbol_name}

Target: `{display}` ({category}) in the CS2 server module.

> Do NOT anchor on raw byte patterns from older releases - they shift. Use anchors only to *locate*
> the function, then generate a fresh minimal-unique function-head signature with relocated bytes
> wildcarded. Produce ONLY the output file(s) listed in this skill's expected outputs, for the binary
> loaded in THIS session (one platform per run). NEVER open or analyze the other platform's binary.

## Method

{kind_hint}

## Mandatory self-check before emitting

The pipeline re-reads the bytes at your `func_va` and deterministically regenerates `func_sig` from
them - if your `func_sig` does not match those bytes EXACTLY (with `??` matching anything), the run
aborts. Therefore:

1. After picking the function, read the actual bytes at `func_va` via the IDA MCP.
2. Derive `func_sig` FROM those bytes: keep stable opcode bytes literally, wildcard relocated or
   variable operands as `??`.
3. `func_sig` MUST start at `func_va` (the true function head).
4. Only then write the YAML. A mismatch is always a bug in YOUR output, never in the pipeline.

## Output schema (STRICT)

{output}

## Verification

1. Decompile the candidate and confirm the behavior matches the purpose above (not a caller or callee).
2. Confirm uniqueness: the generated pattern must match exactly one location in the loaded binary.
3. If a candidate cannot be confirmed, report the shortlist instead of guessing - a skipped symbol is
   safer than a wrong signature.
"""
    with open(skill_path, "w", encoding="utf-8") as f:
        f.write(body)


LIB_MODULE = {"server": "server", "engine2": "engine", "engine": "engine", "client": "client"}
ENGINE_CLASSES = ("CNetworkGameServerBase", "CNetworkGameServer")


def module_for(lib, symbol_name):
    if lib and lib in LIB_MODULE:
        return LIB_MODULE[lib]
    if symbol_name.startswith(ENGINE_CLASSES):
        return "engine"
    return "server"


def inject(text, config_path, specs):
    """Inject specs into the module matching each symbol's library (server/engine/...)."""
    module_matches = list(re.finditer(r"^  - name: ([\w]+)", text, re.M))
    blocks = []  # (name, block_text, start, end)
    for i, m in enumerate(module_matches):
        end = module_matches[i + 1].start() if i + 1 < len(module_matches) else len(text)
        blocks.append((m.group(1), text[m.start():end], m.start(), end))

    new_tasks, new_symbols, new_structs, touched = {}, {}, {}, set()
    for symbol_name, category, struct, member, alias, lib in specs:
        module = module_for(lib, symbol_name)
        block_text = next(btext for name, btext, s, e in blocks if name == module)
        if f"- name: {symbol_name}\n" in block_text:
            continue
        new_tasks.setdefault(module, []).append(find_task_block(symbol_name))
        new_symbols.setdefault(module, []).append(symbol_entry_block(symbol_name, category, struct, member, alias))
        if struct and f"- name: {struct}\n" not in block_text:
            new_structs.setdefault(module, []).append(struct)
        write_skill(symbol_name, category, struct, alias)
        touched.add(module)

    if not touched:
        print(f"  already present: {config_path}")
        return text

    result = text
    for module in sorted(touched):
        btext, m_start, m_end = next((bt, s, e) for name, bt, s, e in blocks if name == module)
        block = result[m_start:m_end]
        skills_match = re.search(r"^    skills:\n", block, re.M)
        symbols_match = re.search(r"^    symbols:\n", block, re.M)
        if not skills_match or not symbols_match:
            print(f"  warning: module {module} mangler skills:/symbols: - skipper")
            continue
        struct_blocks = [struct_entry_block(s) for s in sorted(new_structs.get(module, []))]
        block = (
            block[: skills_match.end()]
            + "".join(new_tasks[module])
            + block[skills_match.end(): symbols_match.end()]
            + "".join(struct_blocks)
            + "".join(new_symbols[module])
            + block[symbols_match.end():]
        )
        result = result[:m_start] + block + result[m_end:]
        print(f"  {module}: +{len(new_tasks[module])} task(s), +{len(new_symbols[module])} symbol(s)")

    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-config", help="analysis config path (default: newest configs/<GAMEVER>.yaml)")
    args = parser.parse_args()

    config_path = args.config or newest_config()
    if not config_path or not os.path.exists(config_path):
        print(f"  warning: no analysis config to patch ({config_path}); skipping")
        return

    specs = load_seed_specs()

    with open(config_path, "r", encoding="utf-8") as f:
        text = f.read()

    patched = inject(text, config_path, specs)
    if patched == text:
        return

    with open(config_path, "w", encoding="utf-8") as f:
        f.write(patched)
    print(f"  updated: {config_path}")


if __name__ == "__main__":
    main()
