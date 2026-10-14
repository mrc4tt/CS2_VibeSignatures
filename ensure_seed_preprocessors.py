#!/usr/bin/env python3
"""Auto-generate relocation preprocessor scripts for symbols with baselines.

For every symbol that has an artifact in a previous gamever but NO preprocessor
script in ida_preprocessor_scripts/, this tool generates a thin relocation
preprocessor. The preprocessor takes the old artifact, searches the new binary
and writes the new one - deterministic, free, seconds.

The category comes from the ANALYSIS CONFIG, which is authoritative. Sniffing it
out of the artifact instead (as this tool used to) produced preprocessors whose
schema disagreed with the config - struct members emitted as functions and a
vfunc emitted as a struct member.

Usage:
  uv run ensure_seed_preprocessors.py                          # newest gamever
  uv run ensure_seed_preprocessors.py -config configs/14181.yaml
  uv run ensure_seed_preprocessors.py -module server           # specific module
  uv run ensure_seed_preprocessors.py -force                   # rewrite auto-generated ones
"""

import argparse
import glob
import os
import re

import yaml

from source_artifact_schema import SYMBOL_ARTIFACT_FIELD_ORDER

MARKER = "auto-generated"

# preprocess_common_skill dispatches per target kind; func_names also covers
# vfunc (preprocess_func_sig_via_mcp falls back to vfunc_sig internally).
CATEGORY_KWARG = {
    "func": "func_names",
    "vfunc": "func_names",
    "gv": "gv_names",
    "patch": "patch_names",
    "structmember": "struct_member_names",
    "vtable": "vtable_class_names",
}

TEMPLATE = '''#!/usr/bin/env python3
"""Preprocess script for find-@SYMBOL@ skill (@MARKER@, @CATEGORY@)."""

from ida_analyze_util import preprocess_common_skill

TARGETS = [
    "@TARGET@",
]
@MANGLED@
GENERATE_YAML_DESIRED_FIELDS = [
    (
        "@FIELDS_KEY@",
        [
@FIELDS@
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
    """Relocate the previous gamever's @CATEGORY@ artifact onto this build."""
    return await preprocess_common_skill(
        session=session,
        expected_outputs=expected_outputs,
        old_yaml_map=old_yaml_map,
        new_binary_dir=new_binary_dir,
        platform=platform,
        image_base=image_base,
        @KWARG@=TARGETS,
@MANGLED_KWARG@        generate_yaml_desired_fields=GENERATE_YAML_DESIRED_FIELDS,
        debug=debug,
    )
'''


def _gamever_sort_key(text):
    """Gamever as a number plus its optional letter suffix (14181 > 14178b)."""
    m = re.fullmatch(r"(\d+)([a-z]?)", text)
    return (int(m.group(1)), m.group(2)) if m else (-1, text)


def newest_config():
    numeric = [c for c in glob.glob("configs/*.yaml") if re.fullmatch(r"configs/\d+[a-z]?\.yaml", c)]
    return max(numeric, key=lambda p: _gamever_sort_key(os.path.basename(p)[:-5])) if numeric else None


def existing_preprocessor(pp_dir, short):
    """A platform-suffixed or staged variant counts as covered."""
    for suffix in ("", "-linux", "-windows", "-decompiles", "-inlined", "-noinline"):
        path = os.path.join(pp_dir, f"find-{short}{suffix}.py")
        if os.path.exists(path):
            return path
    return None


def newest_baseline(module, short, gamever):
    """Newest artifact for this symbol in any OTHER gamever, either platform."""
    found = {}
    for directory in glob.glob(f"bin_artifacts/*/{module}"):
        version = os.path.basename(os.path.dirname(directory))
        if version == gamever:
            continue
        for platform in ("linux", "windows"):
            path = os.path.join(directory, f"{short}.{platform}.yaml")
            if os.path.exists(path):
                found.setdefault(version, []).append(path)
    if not found:
        return None, []
    version = max(found, key=_gamever_sort_key)
    return version, sorted(found[version])


# The fields that DEFINE each category. Taking the field list from whatever the
# baseline artifact happens to carry is a ratchet: one run that fails to resolve
# a vtable writes an artifact without vfunc_index, the next regeneration of this
# preprocessor stops asking for it, and the field can never come back. That is
# how vtidx_DropWeapon went from a verified linux 29 / windows 28 on 14178b to
# shipping the template's stale 24/25 on 14180 and 14181 with nothing failing.
# These are floored in regardless of the baseline, so a category always asks for
# what makes it that category.
CATEGORY_REQUIRED_FIELDS = {
    "func": ("func_name", "func_va", "func_sig"),
    # func_va/func_sig are NOT floored for a vfunc: a slot-only virtual (an empty stub,
    # a two-instruction thunk identical to its twin) cannot be uniquely signatured, and
    # upstream records that decision in the field list. Flooring them made -force add a
    # signature request to 7 slot-only tasks (vtidx_PlayerRunCommand, IGameSystem_vdtor,
    # ...) that the preprocessor then cannot satisfy. The slot fields are what define it.
    "vfunc": ("func_name", "vtable_name", "vfunc_offset", "vfunc_index"),
    "gv": ("gv_name", "gv_va", "gv_sig"),
    "structmember": ("struct_name", "member_name", "offset"),
    "patch": ("patch_name", "patch_va", "patch_sig"),
    "vtable": ("vtable_class", "vtable_va"),
}


def desired_fields(paths, category):
    """Canonically ordered fields present in the baseline, plus the category's own."""
    present = set()
    for path in paths:
        try:
            doc = yaml.safe_load(open(path, encoding="utf-8")) or {}
        except Exception:
            continue
        if isinstance(doc, dict):
            present.update(doc.keys())
    present.update(CATEGORY_REQUIRED_FIELDS.get(category, ()))
    # A struct member's offset is read from ONE instruction inside offset_sig; without
    # offset_sig_disp naming it, relocation falls back to whichever instruction carries the
    # previous build's value - and once that value is wrong it stays wrong. linux
    # CServerSideClient m_Server/m_SteamID/m_NetChannel/m_nEntityIndex shipped a
    # neighbour's offset from 14182 to 14190 that way.
    if category == "structmember" and "offset_sig" in present:
        present.add("offset_sig_disp")
    order = SYMBOL_ARTIFACT_FIELD_ORDER.get(category, ())
    fields = [field for field in order if field in present]
    # A *_allow_across_function_boundary flag is requested as "<field>:true" - the bare
    # name asks for the field without enabling it, and a short body then pins RIP and
    # branch displacements that move every build (CLAUDE.md, find-CFlashbangProjectile_Spawn).
    enabled = set()
    for path in paths:
        try:
            doc = yaml.safe_load(open(path, encoding="utf-8")) or {}
        except Exception:
            continue
        if isinstance(doc, dict):
            enabled |= {k for k, v in doc.items()
                        if k.endswith("_allow_across_function_boundary") and str(v).lower() == "true"}
    return [f"{field}:true" if field in enabled else field for field in fields]


def merge_fields(current, derived, category):
    """`current` plus whatever `derived` adds, in canonical order; ":true" kept from either."""
    def bare(field):
        return field.split(":", 1)[0]
    flagged = {bare(f) for f in current + derived if f.endswith(":true")}
    names = {bare(f) for f in current} | {bare(f) for f in derived}
    order = list(SYMBOL_ARTIFACT_FIELD_ORDER.get(category, ()))
    ordered = [f for f in order if f in names] + sorted(names - set(order))
    merged = [f"{f}:true" if f in flagged else f for f in ordered]
    # nothing to add: keep the file's own order, it may not be canonical
    return current if {bare(f) for f in current} == names and \
        {f for f in current if f.endswith(":true")} == {f for f in merged if f.endswith(":true")} else merged


def existing_fields(path):
    """The field list an existing preprocessor already requests (comments ignored), or None."""
    import ast
    try:
        tree = ast.parse(open(path, encoding="utf-8").read())
    except (OSError, SyntaxError, ValueError):
        return None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "GENERATE_YAML_DESIRED_FIELDS"
                                                for t in node.targets):
            try:
                value = ast.literal_eval(node.value)
                return [list(fields) for _symbol, fields in value]
            except (ValueError, TypeError):
                return None
    return None


def target_name(paths, category, short):
    """vtable targets are addressed by class name, everything else by symbol."""
    if category != "vtable":
        return short
    for path in paths:
        try:
            doc = yaml.safe_load(open(path, encoding="utf-8")) or {}
        except Exception:
            continue
        if isinstance(doc, dict) and doc.get("vtable_class"):
            return str(doc["vtable_class"])
    return short


def mangled_names(paths):
    """The baseline's own vtable symbols, e.g. ``_ZTV30...E`` from ``_ZTV30...E + 0x10``.

    A template class such as CGameSystemReallocatingFactory<CSpawnGroupMgrGameSystem>
    cannot be found from its flattened class name; the hand-written preprocessors pass
    MANGLED_CLASS_NAMES for exactly that, and the baseline already records both.
    """
    names = []
    for path in paths:
        try:
            doc = yaml.safe_load(open(path, encoding="utf-8")) or {}
        except Exception:
            continue
        symbol = str(doc.get("vtable_symbol") or "").split(" + ")[0].strip() if isinstance(doc, dict) else ""
        if symbol and symbol not in names:
            names.append(symbol)
    return names


def render(short, category, fields, target, mangled=()):
    body = "\n".join(f'            "{field}",' for field in fields)
    mangled_decl = mangled_kwarg = ""
    if category == "vtable" and mangled:
        listed = "".join(f'        "{name}",\n' for name in mangled)
        mangled_decl = f"\nMANGLED_CLASS_NAMES = {{\n    \"{target}\": [\n{listed}    ],\n}}\n"
        mangled_kwarg = "        mangled_class_names=MANGLED_CLASS_NAMES,\n"
    # preprocess_common_skill looks a vtable's field list up by its CLASS name
    # (the target), not by the artifact stem; "<class>_vtable" there reads as
    # "unknown desired-fields symbol" and the preprocessor can never succeed.
    fields_key = target if category == "vtable" else short
    return (TEMPLATE
            .replace("@MANGLED@", mangled_decl)
            .replace("@MANGLED_KWARG@", mangled_kwarg)
            .replace("@FIELDS_KEY@", fields_key)
            .replace("@SYMBOL@", short)
            .replace("@TARGET@", target)
            .replace("@CATEGORY@", category)
            .replace("@KWARG@", CATEGORY_KWARG[category])
            .replace("@FIELDS@", body)
            .replace("@MARKER@", MARKER))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-config", help="analysis config (default: newest)")
    ap.add_argument("-module", help="only this module")
    ap.add_argument("-force", action="store_true",
                    help="also rewrite existing auto-generated scripts (never hand-written ones)")
    args = ap.parse_args()

    config_path = args.config or newest_config()
    if not config_path or not os.path.exists(config_path):
        print("  ingen config - springer over")
        return

    gamever = os.path.basename(config_path).replace(".yaml", "")
    cfg = yaml.safe_load(open(config_path, encoding="utf-8"))
    categories = {
        symbol["name"]: symbol.get("category", "func")
        for module in cfg.get("modules", [])
        for symbol in module.get("symbols", [])
    }

    pp_dir = "ida_preprocessor_scripts"
    generated = rewritten = skipped = 0
    unsupported, no_baseline, undeclared = [], [], []

    for module in cfg.get("modules", []):
        mod_name = module.get("name", "?")
        if args.module and mod_name != args.module:
            continue
        for task in module.get("skills", []):
            name = task.get("name", "")
            if not name.startswith("find-"):
                continue
            short = name[len("find-"):]
            if short.endswith(("-decompiles", "-inlined", "-noinline")):
                continue  # staged intermediates, not base symbols

            # A task may carry a role or platform suffix that the symbol does not:
            # find-INetworkSystem_CloseSocket-linux declares the symbol
            # INetworkSystem_CloseSocket. Matching on the full task name left every
            # such task in "undeclared", so no relocation preprocessor was ever
            # generated for it and the artifact would go missing on the next gamever.
            symbol = short
            if symbol not in categories and "-" in symbol:
                stem = symbol.rsplit("-", 1)[0]
                if stem in categories:
                    symbol = stem

            existing = existing_preprocessor(pp_dir, short)
            hand_written = False
            if existing:
                hand_written = MARKER not in open(existing, encoding="utf-8").read()
                if hand_written or not args.force:
                    skipped += 1
                    continue

            category = categories.get(symbol)
            if category is None:
                undeclared.append(short)
                continue
            if category not in CATEGORY_KWARG:
                unsupported.append((short, category))
                continue

            version, paths = newest_baseline(mod_name, symbol, gamever)
            if not paths:
                no_baseline.append(short)
                continue
            fields = desired_fields(paths, category)
            if not fields:
                no_baseline.append(short)
                continue

            # -force only ever ADDS requested fields. A field the existing preprocessor
            # asks for is a decision (find-CGameSystemReallocatingFactory_..._CreateGameSystem
            # requests func_sig with a boundary-crossing flag although its baseline has
            # none), and dropping it because one baseline lacks it is the ratchet the
            # floor above exists to stop. An unchanged list keeps the file byte for byte,
            # so the comments people add beside a field survive.
            current = existing_fields(existing) if existing else None
            if current is not None and len(current) == 1:
                fields = merge_fields(current[0], fields, category)
                if fields == current[0]:
                    skipped += 1
                    continue

            path = existing or os.path.join(pp_dir, f"find-{short}.py")
            with open(path, "w", encoding="utf-8") as handle:
                # filnavnet foelger TASKEN, indholdet foelger SYMBOLET
                handle.write(render(symbol, category, fields,
                                    target_name(paths, category, symbol), mangled_names(paths)))
            if existing:
                rewritten += 1
                print(f"  ~ {os.path.basename(path)} ({category}, {mod_name}, baseline {version})")
            else:
                generated += 1
                print(f"  + {os.path.basename(path)} ({category}, {mod_name}, baseline {version})")

    print(f"\n  genereret: {generated} | omskrevet: {rewritten} | havde allerede: {skipped}")
    if no_baseline:
        print(f"  uden baseline (kan ikke relocates): {len(no_baseline)}")
    if undeclared:
        print(f"  find-task uden symbol-erklaering i configen: {len(undeclared)} -> {undeclared[:5]}")
    if unsupported:
        print(f"  kategori uden relocation-skabelon: {unsupported[:5]}")
    if generated or rewritten:
        print("  -> naeste run_linux/run_windows bruger dem automatisk (sekunder, 0 tokens)")


if __name__ == "__main__":
    main()
