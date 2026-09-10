#!/usr/bin/env python3
"""Ensure EVERY config find-task has an agent-fallback SKILL.md.

Upstream tasks are preprocessor-only by design: when their preprocessor cannot
resolve a new gamever's binary, the pipeline falls back to the agent — which
needs .claude/skills/find-<task>/SKILL.md. Without it the task hard-fails until
upstream re-anchors. This tool writes a generic, category-aware skill for every
task lacking one, making new-gamever runs self-healing without upstream.

Idempotent: existing skills are never touched.

Usage:
  uv run ensure_agent_fallback_skills.py                       # newest config
  uv run ensure_agent_fallback_skills.py -config configs/14180.yaml
"""

import argparse
import glob
import os
import re

SKILLS_DIR = ".claude/skills"
SUFFIXES = ("-decompiles", "-inlined", "-noinline", "-engine", "-server", "-linux", "-windows")

TEMPLATE = '''---
name: find-{task}
description: |
  Agent fallback for {task} (auto-generated, category: {category}). Locate
  {display} in the CS2 {module} module via IDA Pro MCP and emit a fresh,
  minimal-unique artifact. The deterministic preprocessor could not resolve this
  symbol on the current gamever - your job is the re-sign.
  Trigger: {task}, {display}
disable-model-invocation: true
---

# Find {task}

Target: `{display}` ({category}) in the module loaded in THIS session.

> The old artifact/preprocessor anchors no longer match this build. Use anchors
> only to *locate* candidates; derive the artifact from the ACTUAL bytes you read.
> Produce ONLY this session's platform output. NEVER open another binary.

## Method

{method}

## Mandatory self-check before emitting

The pipeline re-reads the bytes at your `func_va` and regenerates `func_sig` from
them - a mismatch aborts the run. Therefore: read the real bytes via IDA MCP,
derive the artifact FROM those bytes (wildcard relocated operands as `??`), start
at the TRUE function head, and only then write the YAML. A mismatch is always a
bug in YOUR output.

## Output schema (STRICT)

Write `<task>.{{platform}}.yaml` with EXACTLY these fields:

{schema}

## Verification

1. Decompile and confirm the behavior matches the symbol's semantics.
2. Uniqueness: the pattern must match exactly ONE location in the loaded binary.
3. If no candidate can be confirmed, report the shortlist - a skipped symbol is
   safer than a wrong signature.
'''

FUNC_SCHEMA = """```yaml
func_name: <TASK>
func_va: "<hex virtual address>"
func_rva: "<hex rva>"
func_size: "<hex size>"
func_sig: "<byte pattern, ?? wildcards, function head, minimal-unique>"
```
NEVER include vfunc_* or struct fields."""

VFUNC_SCHEMA = """```yaml
func_name: <TASK>
func_va: "<hex virtual address>"
func_rva: "<hex rva>"
func_size: "<hex size>"
vtable_name: <owning class RTTI name>
vfunc_offset: "<hex vtable byte offset>"
vfunc_index: <decimal slot index>
```
NEVER include func_sig."""

MEMBER_SCHEMA = """```yaml
struct_name: <owning class name>
member_name: <member name>
offset: "<hex byte offset as string>"
size: <member size in bytes, decimal>
offset_sig: "<short byte pattern of an instruction touching the offset>"
```
NEVER include func_* or vfunc_* fields."""

METHODS = {
    "func": (
        "Locate via distinctive constants/strings in the body, cross-references from\n"
        "known callers/callees, or the owning class vtable (RTTI) if virtual. Verify by\n"
        "decompilation before committing to a candidate."
    ),
    "vfunc": (
        "Resolve the owning class vtable via RTTI (typeinfo-name string -> _ZTI object\n"
        "-> vtable). Identify the slot by xrefs from expected call sites. Slots commonly\n"
        "differ between platforms - never assume identical indices."
    ),
    "structmember": (
        "Resolve the class layout via the schema/network system or instructions that\n"
        "dereference the member. Verify natural alignment and cross-check with\n"
        "constructor/accessor functions."
    ),
}


def _gamever_sort_key(path):
    # gamever first as a number, then the optional letter suffix - sorting on
    # path length instead makes 14178b (19 chars) outrank 14181 (18 chars)
    m = re.fullmatch(r"configs/(\d+)([a-z]?)\.yaml", path)
    return (int(m.group(1)), m.group(2))


def newest_config():
    numeric = [c for c in glob.glob("configs/*.yaml") if re.fullmatch(r"configs/\d+[a-z]?\.yaml", c)]
    return max(numeric, key=_gamever_sort_key) if numeric else None


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-config", help="analysis config (default: newest)")
    args = ap.parse_args()
    cfg_path = args.config or newest_config()
    if not cfg_path or not os.path.exists(cfg_path):
        print(f"  warning: no config ({cfg_path}); skipping")
        return

    import yaml
    cfg = yaml.safe_load(open(cfg_path))

    written = 0
    for module in cfg.get("modules", []):
        mod_name = module.get("name", "?")
        symbols = {s.get("name"): s for s in module.get("symbols", [])}
        for task in module.get("skills", []):
            task_name = task.get("name", "")
            if not task_name.startswith("find-"):
                continue
            short = task_name[len("find-"):]
            skill_path = os.path.join(SKILLS_DIR, task_name, "SKILL.md")
            if os.path.exists(skill_path):
                continue

            entry = symbols.get(short)
            if entry is None:
                base = short
                for suf in SUFFIXES:
                    if base.endswith(suf):
                        base = base[: -len(suf)]
                entry = symbols.get(base)
            category = (entry or {}).get("category") or "func"
            if category not in METHODS:
                category = "func"
            struct = (entry or {}).get("struct", "")
            member = (entry or {}).get("member", "")
            display = f"{struct}::{member}" if category == "structmember" and struct else short

            schema = {"func": FUNC_SCHEMA, "vfunc": VFUNC_SCHEMA, "structmember": MEMBER_SCHEMA}[category]
            body = TEMPLATE.format(task=short, display=display, category=category,
                                   module=mod_name, method=METHODS[category], schema=schema)
            os.makedirs(os.path.dirname(skill_path), exist_ok=True)
            with open(skill_path, "w", encoding="utf-8") as f:
                f.write(body)
            written += 1
    print(f"  agent-fallback skills skrevet: {written} (config: {cfg_path})")


if __name__ == "__main__":
    main()
