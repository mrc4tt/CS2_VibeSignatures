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


def newest_config():
    candidates = glob.glob("configs/*.yaml")
    numeric = [c for c in candidates if re.fullmatch(r"configs/\d+[a-z]?\.yaml", c)]
    if not numeric:
        return None
    return max(numeric, key=lambda p: (len(p), p))


def load_seed_specs():
    """Derive (symbol_name, category, struct, member, alias) for every seed entry."""
    specs = []
    for seed in SEEDS:
        if not os.path.exists(seed):
            print(f"  warning: seed missing, skipping: {seed}")
            continue
        with open(seed, "r", encoding="utf-8") as f:
            gamedata = json.load(f)
        for key, entry in gamedata.items():
            symbol_name = key.replace("::", "_")
            alias = key if key != symbol_name else None
            if "signatures" in entry:
                specs.append((symbol_name, "func", None, None, alias))
                continue
            cls, _, method = key.partition("::")
            if method.startswith("m_"):
                specs.append((symbol_name, "structmember", cls, method, alias))
            else:
                specs.append((symbol_name, "vfunc", None, None, alias))
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
            f"This is a VIRTUAL function - resolve the {display} vtable via RTTI and identify the\n"
            f"slot, then emit the slot. Verify by xrefs from expected call sites. vtable slots\n"
            f"commonly differ between platforms - never assume identical indices."
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


def inject(text, config_path, specs):
    module_match = re.search(r"^  - name: server$", text, re.M)
    if not module_match:
        sys.exit(f"error: {config_path}: no 'server' module found")
    next_module = re.search(r"^  - name: (?!server$)", text[module_match.start() + 1:], re.M)
    block_end = module_match.start() + 1 + next_module.start() if next_module else len(text)
    block = text[module_match.start():block_end]

    skills_match = re.search(r"^    skills:\n", block, re.M)
    symbols_match = re.search(r"^    symbols:\n", block, re.M)
    if not skills_match or not symbols_match:
        sys.exit(f"error: {config_path}: server module lacks skills:/symbols: sections")

    new_tasks = []
    new_symbols = []
    needed_structs = set()
    new_skills = []
    for symbol_name, category, struct, member, alias in specs:
        symbol_present = f"- name: {symbol_name}\n" in block
        task_present = f"- name: find-{symbol_name}\n" in block
        if symbol_present and task_present:
            continue
        if not task_present:
            new_tasks.append(find_task_block(symbol_name))
            # a task without a skill can never run - ensure one exists
            write_skill(symbol_name, category, struct, alias)
            new_skills.append(symbol_name)
        if not symbol_present:
            new_symbols.append(symbol_entry_block(symbol_name, category, struct, member, alias))
            if struct and f"- name: {struct}\n" not in block:
                needed_structs.add(struct)

    if not new_tasks:
        print(f"  already present: {config_path}")
        return text

    struct_blocks = [struct_entry_block(s) for s in sorted(needed_structs)]
    patched = (
        block[: skills_match.end()]
        + "".join(new_tasks)
        + block[skills_match.end(): symbols_match.end()]
        + "".join(struct_blocks)
        + "".join(new_symbols)
        + block[symbols_match.end():]
    )
    print(f"  injected {len(new_tasks)} task(s) + {len(new_symbols)} symbol(s) + {len(struct_blocks)} struct(s) + {len(new_skills)} skill(s)")
    return text[: module_match.start()] + patched + text[block_end:]


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
