#!/usr/bin/env python3
"""Auto-generate relocation preprocessor scripts for symbols with baselines.

For every symbol that has an artifact in a previous gamever but NO preprocessor
script in ida_preprocessor_scripts/, this tool generates a thin relocation
preprocessor (the same pattern as upstream's find-CBasePlayerController_
HandleCommand_JoinTeam.py). The preprocessor takes the old sig, searches the
new binary, and writes the artifact — deterministic, free, seconds.

Usage:
  uv run ensure_seed_preprocessors.py                          # newest gamever
  uv run ensure_seed_preprocessors.py -config configs/14181.yaml
  uv run ensure_seed_preprocessors.py -module server           # specific module
"""

import argparse
import glob
import os
import re

import yaml

TEMPLATE = '''#!/usr/bin/env python3
"""Preprocess script for find-{symbol} skill (auto-generated)."""

from ida_analyze_util import preprocess_common_skill

TARGET_FUNCTION_NAMES = [
    "{symbol}",
]

GENERATE_YAML_DESIRED_FIELDS = [
    (
        "{symbol}",
        [
            "func_name",
            "func_sig",
            "func_va",
            "func_rva",
            "func_size",
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
    """Reuse previous gamever func_sig to locate target function and write YAML."""
    return await preprocess_common_skill(
        session=session,
        expected_outputs=expected_outputs,
        old_yaml_map=old_yaml_map,
        new_binary_dir=new_binary_dir,
        platform=platform,
        image_base=image_base,
        func_names=TARGET_FUNCTION_NAMES,
        generate_yaml_desired_fields=GENERATE_YAML_DESIRED_FIELDS,
        debug=debug,
    )
'''

# symboler med structmember-artefakter faar en anden skabelon (ingen func-sig)
STRUCT_TEMPLATE = '''#!/usr/bin/env python3
"""Preprocess script for find-{symbol} skill (auto-generated, structmember)."""

from ida_analyze_util import preprocess_gen_struct_member_via_mcp

TARGET_FUNCTION_NAMES = [
    "{symbol}",
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
    """Reuse previous gamever struct member offset to locate and write YAML."""
    return await preprocess_gen_struct_member_via_mcp(
        session=session,
        expected_outputs=expected_outputs,
        old_yaml_map=old_yaml_map,
        new_binary_dir=new_binary_dir,
        platform=platform,
        image_base=image_base,
        target_name="{symbol}",
        debug=debug,
    )
'''


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-config", help="analysis config (default: newest)")
    ap.add_argument("-module", help="only this module")
    args = ap.parse_args()

    config_path = args.config
    if not config_path:
        numeric = [c for c in glob.glob("configs/*.yaml") if re.fullmatch(r"configs/\d+[a-z]?\.yaml", c)]
        config_path = max(numeric, key=lambda p: (len(p), p)) if numeric else None
    if not config_path or not os.path.exists(config_path):
        print("  ingen config — springer over"); return

    gamever = os.path.basename(config_path).replace(".yaml", "")
    cfg = yaml.safe_load(open(config_path))

    # find alle tasks uden preprocessor-script
    pp_dir = "ida_preprocessor_scripts"
    generated = 0
    skipped = 0

    for module in cfg.get("modules", []):
        mod_name = module.get("name", "?")
        if args.module and mod_name != args.module:
            continue

        # find baseline-artefakter for dette modul i aeldre gamevers
        for task in module.get("skills", []):
            name = task.get("name", "")
            if not name.startswith("find-"):
                continue
            short = name[len("find-"):]
            if short.endswith(("-decompiles", "-inlined", "-noinline")):
                continue  # mellemtrin — ikke basiske symboler

            pp_path = os.path.join(pp_dir, f"find-{short}.py")
            if os.path.exists(pp_path):
                skipped += 1
                continue

            # har vi en baseline fra en anden gamever?
            has_baseline = False
            is_struct = False
            for d in glob.glob(f"bin_artifacts/*/{mod_name}"):
                ver = os.path.basename(os.path.dirname(d))
                if ver == gamever:
                    continue
                p = os.path.join(d, f"{short}.linux.yaml")
                if os.path.exists(p):
                    has_baseline = True
                    content = open(p).read()
                    is_struct = "struct_name:" in content and "func_sig:" not in content
                    break

            if not has_baseline:
                continue  # kan ikke relocat'e uden baseline

            template = STRUCT_TEMPLATE if is_struct else TEMPLATE
            script = template.format(symbol=short)
            with open(pp_path, "w") as f:
                f.write(script)
            generated += 1
            kind = "structmember" if is_struct else "func"
            print(f"  + find-{short}.py ({kind}, {mod_name})")

    print(f"\n  preprocessors genereret: {generated} | havde allerede: {skipped}")
    if generated:
        print(f"  → næste run_linux/run_windows bruger dem automatisk (sekunder, 0 tokens)")


if __name__ == "__main__":
    main()
