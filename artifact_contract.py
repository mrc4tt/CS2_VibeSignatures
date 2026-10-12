"""The fields a symbol artifact may carry, and the check that holds a producer to them.

GENERATE_YAML_DESIRED_FIELDS in each preprocessor is the durability contract
(CLAUDE.md rule 18): a deterministic run writes exactly those fields. An agent, the
hunter, a review-issue confirmation or a hand edit can write anything, and a wrong
record still resolves cleanly in the binary, so neither validate_artifacts nor
validate_expected_input_artifacts sees it. This is checked in two places:
ida_analyze_bin rejects such an output from the hunter or an agent (the agent is
told why and retries), and audit_artifact_contract.py checks a whole gamever in
the verification battery and the autopilot gate.
"""

from __future__ import annotations

import ast
import functools
import os
from pathlib import Path

import yaml


def _symbol_of(path, platform):
    name = os.path.basename(str(path))
    suffix = f".{platform}.yaml"
    if name.endswith(suffix):
        return name[: -len(suffix)]
    return name[:-5] if name.endswith(".yaml") else name


# Fields that name what an artifact IS. A producer may move a symbol to a new
# address, never turn it into another symbol or another class's slot.
_ARTIFACT_NAME_KEYS = ("func_name", "gv_name", "patch_name")
_ARTIFACT_IDENTITY_KEYS = ("vtable_name", "struct_name", "member_name")
# Internal metadata a producer may leave out (0x0 / absent means unknown, rule 14).
_ARTIFACT_SHAPE_IGNORED_KEYS = frozenset({"func_size"})
# Flags that describe how a signature was generated, not what the record is. The
# generator writes them whenever the signature needed them, declared or not, and
# a signature that crossed a boundary must keep saying so.
_SIGNATURE_FLAG_SUFFIXES = ("_allow_across_function_boundary", "_max_match")


def _is_signature_flag(key):
    return key.endswith(_SIGNATURE_FLAG_SUFFIXES)


def _load_yaml_dict(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            doc = yaml.safe_load(handle)
    except (OSError, UnicodeError, yaml.YAMLError):
        return None
    return doc if isinstance(doc, dict) else None


def strip_undeclared_fields(paths, platform, declared=None):
    """Remove fields the symbol's task does not declare, in place.

    A deterministic run writes exactly GENERATE_YAML_DESIRED_FIELDS; the hunter
    and agents may add more (a func_sig on a virtual whose task asks only for its
    slot). Those extra fields are not wrong so much as unowned - nothing keeps them
    current - and the next deterministic run drops them anyway. Removing them
    keeps the record the task would have written; rejecting it instead lost
    CEntitySystem_Activate.linux, which the hunter had found correctly.
    Only symbols with a declared contract are touched. Returns {path: [removed]}.
    """
    declared = declared_artifact_fields() if declared is None else declared
    removed = {}
    for path in paths:
        if not os.path.isfile(path):
            continue
        contract = declared.get(_symbol_of(path, platform))
        doc = _load_yaml_dict(path)
        if contract is None or doc is None:
            continue
        allowed = set(contract[0]) | set(contract[1]) | _ARTIFACT_SHAPE_IGNORED_KEYS
        extra = [key for key in doc if key not in allowed and not _is_signature_flag(key)]
        if not extra:
            continue
        for key in extra:
            del doc[key]
        with open(path, "w", encoding="utf-8") as handle:
            yaml.safe_dump(doc, handle, sort_keys=False, allow_unicode=True)
        removed[path] = sorted(extra)
    return removed


@functools.lru_cache(maxsize=1)
def declared_artifact_fields():
    """symbol -> (required, optional) fields, from every preprocessor's
    GENERATE_YAML_DESIRED_FIELDS. Read with ast, so no script is imported.

    ``name?`` and ``name:value`` entries are optional: a ``?`` field is written
    when it applies, and ``*_allow_across_function_boundary:true`` only when the
    signature needed it.
    """
    declared = {}
    scripts_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ida_preprocessor_scripts")
    for script in sorted(Path(scripts_dir).glob("*.py")):
        try:
            tree = ast.parse(script.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, SyntaxError):
            continue
        for node in tree.body:
            if not isinstance(node, ast.Assign) or not any(
                getattr(target, "id", None) == "GENERATE_YAML_DESIRED_FIELDS" for target in node.targets
            ):
                continue
            try:
                entries = ast.literal_eval(node.value)
            except (ValueError, SyntaxError):
                continue
            for entry in entries:
                if not (isinstance(entry, (tuple, list)) and len(entry) == 2 and isinstance(entry[0], str)):
                    continue
                required, optional = declared.setdefault(entry[0], (set(), set()))
                for field in entry[1] or ():
                    if not isinstance(field, str):
                        continue
                    if field.endswith("?") or ":" in field:
                        optional.add(field.rstrip("?").split(":", 1)[0])
                    else:
                        required.add(field)
    return {symbol: (frozenset(req), frozenset(opt)) for symbol, (req, opt) in declared.items()}


def artifact_contract_issues(produced_paths, platform, old_artifact_dir, declared=None):
    """What an agent or hunter wrote that the deterministic producer never would.

    validate_expected_input_artifacts cannot see any of this, because a wrong
    record still resolves cleanly in the binary. Four checks:
    - the record names its own symbol (func_name/gv_name/patch_name equal to the
      filename's symbol, or to the previous gamever's value, which keeps upstream's
      historical renames such as CLoopTypeBase_FrameUpdate -> CLoopTypeBase_Update);
    - vtable/struct/member are the previous gamever's: the class does not move;
    - no field outside the task's GENERATE_YAML_DESIRED_FIELDS (the previous
      gamever's fields when no task declares the symbol);
    - no field dropped that the previous gamever carried and the task still asks for.
    A field the task asks for but neither build has is not reported: a two-instruction
    thunk cannot be signatured, and deterministic producers leave those out too.
    14190 shipped what this rejects: CBaseEntity_OnTakeDamage.windows filed as
    CBasePlayerPawn_OnTakeDamage on CBasePlayerPawn's vtable, and eight virtuals
    whose declared vfunc_sig was replaced by func_va/func_sig - all from an agent.
    """
    declared = declared_artifact_fields() if declared is None else declared
    issues = []
    for path in produced_paths:
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as handle:
                current = yaml.safe_load(handle) or {}
        except (OSError, UnicodeError, yaml.YAMLError):
            continue  # finalize already reports an unreadable artifact
        if not isinstance(current, dict):
            continue
        name = os.path.basename(path)
        symbol = _symbol_of(path, platform)
        previous = None
        if old_artifact_dir:
            old_path = os.path.join(old_artifact_dir, name)
            if os.path.isfile(old_path):
                try:
                    with open(old_path, "r", encoding="utf-8") as handle:
                        previous = yaml.safe_load(handle)
                except (OSError, UnicodeError, yaml.YAMLError):
                    previous = None
        previous = previous if isinstance(previous, dict) else None

        for key in _ARTIFACT_NAME_KEYS:
            if key not in current:
                continue
            allowed = {symbol}
            if previous and previous.get(key):
                allowed.add(previous[key])
            if current[key] not in allowed:
                issues.append(
                    f"{name}: {key} is {current[key]!r}, but this file is {symbol!r} - "
                    "write the symbol the file is named after, not a neighbouring one"
                )
        if previous:
            for key in _ARTIFACT_IDENTITY_KEYS:
                if key in previous and key in current and current[key] != previous[key]:
                    issues.append(
                        f"{name}: {key} is {current[key]!r}, the previous gamever has {previous[key]!r} - "
                        "the class does not change between builds"
                    )

        keys = set(current) - _ARTIFACT_SHAPE_IGNORED_KEYS
        contract = declared.get(symbol)
        if contract is not None:
            required, optional = contract
            allowed_keys = set(required) | set(optional)
            expected = set(required)
        elif previous:
            allowed_keys = expected = set(previous)
        else:
            continue
        unexpected = sorted(k for k in keys - allowed_keys - _ARTIFACT_SHAPE_IGNORED_KEYS if not _is_signature_flag(k))
        dropped = sorted((set(previous or ()) & expected) - keys - _ARTIFACT_SHAPE_IGNORED_KEYS)
        if unexpected or dropped:
            detail = "; ".join(
                part
                for part in (
                    f"not declared: {', '.join(unexpected)}" if unexpected else "",
                    f"dropped since the previous gamever: {', '.join(dropped)}" if dropped else "",
                )
                if part
            )
            want = sorted((set(previous or ()) & allowed_keys) or expected)
            issues.append(f"{name}: fields do not match the task's contract ({detail}) - write: {', '.join(want)}")
    return issues
