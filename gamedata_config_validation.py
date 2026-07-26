from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from gamedata_symbol_config import (
    ARTIFACT_CATEGORIES,
    SUPPORTED_CATEGORIES,
    SUPPORTED_PLATFORMS,
    source_candidate_names,
)


class GamedataConfigValidationError(ValueError):
    pass


@dataclass(frozen=True)
class GamedataConfigFinding:
    code: str
    module: str
    symbol: str
    field: str
    message: str


def finding_key(finding: GamedataConfigFinding) -> tuple[str, ...]:
    return (finding.code, finding.module, finding.symbol, finding.field, finding.message)


def finding_delta(current, baseline) -> list[GamedataConfigFinding]:
    baseline_keys = {finding_key(item) for item in baseline}
    return sorted((item for item in current if finding_key(item) not in baseline_keys), key=finding_key)


def _context(module_name, symbol_name, field) -> str:
    return ".".join(item for item in (module_name, symbol_name, field) if item)


def _validate_alias_field(errors, *, module_name, symbol_name, symbol, field) -> None:
    if field not in symbol:
        return
    value = symbol[field]
    values = (value,) if isinstance(value, str) else tuple(value) if isinstance(value, list) else None
    context = _context(module_name, symbol_name, field)
    if values is None or any(not isinstance(item, str) or not item.strip() for item in values):
        errors.append(f"{context}: expected a non-empty string or list of non-empty strings")
        return
    if len(values) != len(set(values)):
        errors.append(f"{context}: duplicate values are not allowed")


def _validate_shape(config) -> tuple[list[dict], list[str]]:
    errors = []
    if not isinstance(config, dict):
        return [], ["config: top-level value must be a mapping"]
    modules = config.get("modules")
    if not isinstance(modules, list):
        return [], ["modules: expected a list of mappings"]
    for stage_index, module in enumerate(modules):
        if not isinstance(module, dict):
            errors.append(f"modules[{stage_index}]: expected a mapping")
            continue
        module_name = module.get("name")
        if not isinstance(module_name, str) or not module_name.strip():
            errors.append(f"modules[{stage_index}].name: expected a non-empty string")
        symbols = module.get("symbols", [])
        if not isinstance(symbols, list):
            errors.append(f"modules[{stage_index}].symbols: expected a list of mappings")
    return modules, errors


def _validate_symbols(modules, errors) -> list[tuple[str, dict]]:
    validated = []
    struct_names = defaultdict(set)
    for module in modules:
        if not isinstance(module, dict) or not isinstance(module.get("name"), str):
            continue
        module_name = module["name"]
        for symbol in module.get("symbols", []) if isinstance(module.get("symbols"), list) else []:
            if isinstance(symbol, dict) and symbol.get("category") == "struct":
                name = symbol.get("name")
                if isinstance(name, str) and name.strip():
                    struct_names[module_name].add(name)
    for stage_index, module in enumerate(modules):
        if not isinstance(module, dict) or not isinstance(module.get("name"), str):
            continue
        module_name = module["name"]
        seen_names = set()
        symbols = module.get("symbols", []) if isinstance(module.get("symbols"), list) else []
        for symbol_index, symbol in enumerate(symbols):
            if not isinstance(symbol, dict):
                errors.append(f"{module_name}.symbols[{symbol_index}]: expected a mapping")
                continue
            symbol_name = symbol.get("name")
            if not isinstance(symbol_name, str) or not symbol_name.strip():
                errors.append(f"{module_name}.symbols[{symbol_index}].name: expected a non-empty string")
                continue
            if symbol_name in seen_names:
                errors.append(f"{module_name}.{symbol_name}.name: duplicate symbol in module stage {stage_index}")
            seen_names.add(symbol_name)
            category = symbol.get("category")
            if category not in SUPPORTED_CATEGORIES:
                errors.append(f"{module_name}.{symbol_name}.category: unsupported category {category!r}")
            platform = symbol.get("platform")
            if platform is not None and platform not in SUPPORTED_PLATFORMS:
                errors.append(f"{module_name}.{symbol_name}.platform: unsupported platform {platform!r}")
            _validate_alias_field(
                errors, module_name=module_name, symbol_name=symbol_name, symbol=symbol, field="alias"
            )
            _validate_alias_field(
                errors, module_name=module_name, symbol_name=symbol_name, symbol=symbol, field="source_alias"
            )
            if category == "struct":
                if "source_alias" in symbol:
                    errors.append(
                        f"{module_name}.{symbol_name}.source_alias: metadata-only structs cannot load artifacts"
                    )
            elif category == "structmember":
                for field in ("struct", "member"):
                    value = symbol.get(field)
                    if not isinstance(value, str) or not value.strip():
                        errors.append(f"{module_name}.{symbol_name}.{field}: expected a non-empty string")
                struct_name = symbol.get("struct")
                if (
                    isinstance(struct_name, str)
                    and struct_name.strip()
                    and struct_name not in struct_names[module_name]
                ):
                    errors.append(
                        f"{module_name}.{symbol_name}.struct: {struct_name!r} is not a declared struct in this module"
                    )
            validated.append((module_name, symbol))
    return validated


def _build_producer_index(modules, errors) -> dict[tuple[str, str], set[str]]:
    from ida_analyze_bin import _skill_runs_on_platform, expand_skill_output_paths

    producer_platforms = defaultdict(set)
    validation_root = (Path.cwd() / ".gamedata-config-validation").resolve()
    for module in modules:
        if not isinstance(module, dict) or not isinstance(module.get("name"), str):
            continue
        module_name = module["name"]
        for skill in module.get("skills", []) or []:
            if not isinstance(skill, dict):
                continue
            for platform in SUPPORTED_PLATFORMS:
                if not module.get(f"path_{platform}") or not _skill_runs_on_platform(skill, platform):
                    continue
                try:
                    required, optional, _combined = expand_skill_output_paths(
                        str(validation_root / module_name), skill, platform
                    )
                except (OSError, TypeError, ValueError) as exc:
                    errors.append(f"{module_name}.{skill.get('name', '<unnamed>')}.expected_output: {exc}")
                    continue
                for output_path in (*required, *optional):
                    path = Path(output_path).resolve()
                    try:
                        relative = path.relative_to(validation_root)
                    except ValueError:
                        continue
                    if len(relative.parts) != 2:
                        continue
                    output_module, filename = relative.parts
                    suffix = f".{platform}.yaml"
                    if filename.endswith(suffix):
                        producer_platforms[(output_module, filename[: -len(suffix)])].add(platform)
    return producer_platforms


def _validate_source_collisions(validated_symbols, errors) -> None:
    owners = defaultdict(set)
    for module_name, symbol in validated_symbols:
        category = symbol.get("category")
        symbol_name = symbol.get("name")
        if category not in ARTIFACT_CATEGORIES or not isinstance(symbol_name, str):
            continue
        platforms = (symbol["platform"],) if symbol.get("platform") in SUPPORTED_PLATFORMS else SUPPORTED_PLATFORMS
        try:
            candidates = source_candidate_names(symbol_name, symbol)
        except TypeError:
            continue
        for platform in platforms:
            for candidate in candidates:
                owners[(module_name, category, platform, candidate)].add(symbol_name)
    for (module, category, platform, candidate), symbols in sorted(owners.items()):
        if len(symbols) > 1:
            errors.append(
                f"{module}.{candidate}.source_alias: collision for {category}/{platform} between "
                f"{', '.join(sorted(symbols))}"
            )


def _platform_findings(validated_symbols, producer_platforms, errors) -> list[GamedataConfigFinding]:
    findings = []
    for module_name, symbol in validated_symbols:
        category = symbol.get("category")
        symbol_name = symbol.get("name")
        if category not in ARTIFACT_CATEGORIES or not isinstance(symbol_name, str):
            continue
        candidates = source_candidate_names(symbol_name, symbol)
        known_platforms = set()
        for candidate in candidates:
            known_platforms.update(producer_platforms.get((module_name, candidate), ()))
        explicit_platform = symbol.get("platform")
        if explicit_platform in SUPPORTED_PLATFORMS and known_platforms and explicit_platform not in known_platforms:
            errors.append(
                f"{module_name}.{symbol_name}.platform: {explicit_platform!r} contradicts producer platforms "
                f"{', '.join(sorted(known_platforms))}"
            )
        elif not known_platforms:
            findings.append(
                GamedataConfigFinding(
                    "producer_not_found",
                    module_name,
                    symbol_name,
                    "platform",
                    "no configured skill declares a canonical or source-alias artifact",
                )
            )
        elif explicit_platform is None and len(known_platforms) == 1:
            platform = next(iter(known_platforms))
            findings.append(
                GamedataConfigFinding(
                    "implicit_single_platform",
                    module_name,
                    symbol_name,
                    "platform",
                    f"all configured producers run only on {platform}",
                )
            )
    return sorted(findings, key=finding_key)


def validate_gamedata_config(config) -> list[GamedataConfigFinding]:
    modules, errors = _validate_shape(config)
    validated_symbols = _validate_symbols(modules, errors)
    producer_platforms = _build_producer_index(modules, errors)
    _validate_source_collisions(validated_symbols, errors)
    findings = _platform_findings(validated_symbols, producer_platforms, errors)
    if errors:
        raise GamedataConfigValidationError("invalid gamedata symbol config:\n- " + "\n- ".join(sorted(set(errors))))
    return findings


def print_config_findings(findings, *, title: str, debug: bool) -> None:
    if not findings:
        return
    print(f"{title}: {len(findings)}")
    if not debug:
        return
    for finding in sorted(findings, key=finding_key):
        print(f"  - [{finding.code}] {finding.module}.{finding.symbol}.{finding.field}: {finding.message}")
