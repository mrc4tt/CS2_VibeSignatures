def _short(value, limit=240):
    text = repr(value)
    return text if len(text) <= limit else f"{text[: limit - 3]}..."


def _field_changes(expected, actual, prefix="", limit=8):
    changes = []
    if isinstance(expected, dict) and isinstance(actual, dict):
        for key in sorted(set(expected) | set(actual), key=str):
            field = f"{prefix}.{key}" if prefix else str(key)
            if key not in expected:
                changes.append((field, "<missing>", actual[key]))
            elif key not in actual:
                changes.append((field, expected[key], "<missing>"))
            elif expected[key] != actual[key]:
                changes.extend(_field_changes(expected[key], actual[key], field, limit - len(changes)))
            if len(changes) >= limit:
                break
    elif expected != actual:
        changes.append((prefix or "<root>", expected, actual))
    return changes[:limit]


def format_mismatch(expected_files: dict, actual_files: dict) -> str:
    expected_paths = set(expected_files)
    actual_paths = set(actual_files)
    lines = ["Snapshot mismatch:"]
    sections = (
        ("Added in actual", sorted(actual_paths - expected_paths)),
        ("Missing from actual", sorted(expected_paths - actual_paths)),
    )
    for title, paths in sections:
        if paths:
            lines.extend([f"  {title}:", *(f"    {path}" for path in paths), ""])
    modified = sorted(path for path in expected_paths & actual_paths if expected_files[path] != actual_files[path])
    if modified:
        lines.append("  Modified:")
        for path in modified[:20]:
            lines.append(f"    {path}")
            for field, expected, actual in _field_changes(expected_files[path], actual_files[path]):
                lines.append(f"      {field}:")
                lines.append(f"        snapshot: {_short(expected)}")
                lines.append(f"        actual:   {_short(actual)}")
    return "\n".join(lines).rstrip()
