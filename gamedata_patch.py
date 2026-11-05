#!/usr/bin/env python3
"""Replace stale values in a user's gamedata file, byte for byte, leaving the rest alone.

The Python twin of pages/src/features/checkfile/patch.ts, so the site's "fix my file"
and user_gamedata.py's update of a stored file place a value the same way. Text
surgery, not parse-and-reserialise: a hand-maintained file keeps its comments and
layout. A value that cannot be placed exactly once inside its own key's braces, under
its own platform's name, is refused and reported rather than guessed.
"""

import json
import re

PLATFORM_NAMES = {"linux": ("linux", "linuxsteamrt64"), "windows": ("windows", "win64")}
VTABLE_INDEX_NAMES = {"linux": ("linux_index",), "windows": ("windows_index",)}
VTABLE_KEY_SUFFIX = ".vtable"


def key_window(text, key, start=0):
    """(from, to) of the key's own block, braces counted, or None."""
    at = text.find(f'"{key}"', start)
    if at < 0:
        return None
    opening = text.find("{", at + len(key) + 2)
    if opening < 0:
        return None
    depth = 0
    for index in range(opening, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return at, index + 1
    return at, len(text)


def verdict_window(text, key):
    if not key.endswith(VTABLE_KEY_SUFFIX):
        return key_window(text, key)
    entry = key_window(text, key[: -len(VTABLE_KEY_SUFFIX)])
    if not entry:
        return None
    inner = key_window(text[entry[0]:entry[1]], "vtable")
    return (entry[0] + inner[0], entry[0] + inner[1]) if inner else None


def _render(value):
    return f'"{value}"' if isinstance(value, str) else json.dumps(value)


def to_kv_escapes(pattern):
    r"""'48 8B ?? 05' -> '\x48\x8B\x2A\x05', SourceMod's convention (\x2A is the wildcard)."""
    out = []
    for byte in str(pattern).split():
        out.append("\\x2A" if byte.strip("?") == "" else "\\x" + byte.upper().zfill(2))
    return "".join(out)


def _kv_normal(raw):
    out = []
    for byte in re.findall(r"\\x([0-9A-Fa-f]{2})", raw):
        out.append("??" if byte.upper() == "2A" else byte.upper())
    return " ".join(out)


def _replace_escaped(text, window, alternatives, old, new):
    r"""A KeyValues file writes a signature as \x escapes, which the verifier reads as a
    spaced pattern: find the value whose escapes read as `old`, write `new` escaped."""
    start, end = window
    piece = text[start:end]
    pattern = re.compile(rf'("(?:{alternatives})"\s+)("((?:[^"\\]|\\.)*)")')
    hits = [hit for hit in pattern.finditer(piece)
            if "\\x" in hit.group(3) and _kv_normal(hit.group(3)) == " ".join(str(old).split()).upper()]
    if not hits:
        return text, "notFound"
    if len(hits) > 1:
        return text, "ambiguous"
    hit = hits[0]
    patched = piece[: hit.start(2)] + '"' + to_kv_escapes(new) + '"' + piece[hit.end(2):]
    return text[:start] + patched + text[end:], "applied"


def replace_in_window(text, window, platform, old, new, names=PLATFORM_NAMES):
    """-> (text, outcome) with outcome applied / notFound / ambiguous."""
    start, end = window
    piece = text[start:end]
    alternatives = "|".join(re.escape(name) for name in names[platform])
    if isinstance(old, str) and isinstance(new, str) and "\\x" in piece and "\\x" not in old:
        return _replace_escaped(text, window, alternatives, old, new)
    body = f'"{re.escape(str(old))}"' if isinstance(old, str) else rf"{re.escape(str(old))}\b"
    # JSON and JSONC write `"linux": value`; KeyValues writes `"linux"  "value"`.
    pattern = re.compile(rf'("(?:{alternatives})"\s*(?::\s*|\s+))({body})')
    hits = list(pattern.finditer(piece))
    if not hits:
        return text, "notFound"
    if len(hits) > 1:
        return text, "ambiguous"
    hit = hits[0]
    patched = piece[: hit.start(2)] + _render(new) + piece[hit.end(2):]
    return text[:start] + patched + text[end:], "applied"


def apply_fixes(text, fixes):
    """fixes: [{key, platform, from, to}] -> (text, applied, skipped[{key, platform, reason}])."""
    out, applied, skipped = text, 0, []
    for fix in fixes:
        window = verdict_window(out, fix["key"])
        if not window:
            skipped.append({"key": fix["key"], "platform": fix["platform"], "reason": "notFound"})
            continue
        names = VTABLE_INDEX_NAMES if fix["key"].endswith(VTABLE_KEY_SUFFIX) else PLATFORM_NAMES
        out, outcome = replace_in_window(out, window, fix["platform"], fix["from"], fix["to"], names)
        if outcome == "applied":
            applied += 1
        else:
            skipped.append({"key": fix["key"], "platform": fix["platform"], "reason": outcome})
    return out, applied, skipped
