from __future__ import annotations

ARTIFACT_CATEGORIES = frozenset({"func", "gv", "vfunc", "vtable", "patch", "structmember"})
SUPPORTED_CATEGORIES = frozenset({*ARTIFACT_CATEGORIES, "struct"})
SUPPORTED_PLATFORMS = ("windows", "linux")

PATCH_COMPAT_ALIASES = {
    "CCSPlayer_MovementServices_FullWalkMove_SpeedClamp": ("ServerMovementUnlock",),
    "CCSPlayer_MovementServices_CheckJumpButton_WaterPatch": (
        "CheckJumpButtonWater",
        "FixWaterFloorJump",
    ),
    "CCSBotManager_AddBot_BotNavIgnore": ("BotNavIgnore",),
}


def normalize_alias_input(value) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(value)


def downstream_aliases(symbol_name: str, symbol: dict) -> tuple[str, ...]:
    aliases = normalize_alias_input(symbol.get("alias"))
    if symbol.get("category") == "patch":
        aliases = (*aliases, *PATCH_COMPAT_ALIASES.get(symbol_name, ()))
    return tuple(dict.fromkeys(aliases))


def source_candidate_names(symbol_name: str, symbol: dict) -> tuple[str, ...]:
    aliases = normalize_alias_input(symbol.get("source_alias"))
    if symbol.get("category") == "patch":
        aliases = (*aliases, *PATCH_COMPAT_ALIASES.get(symbol_name, ()))
    return tuple(dict.fromkeys((symbol_name, *aliases)))
