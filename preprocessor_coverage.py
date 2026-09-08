"""Report configured skill-to-preprocessor coverage without importing IDA scripts."""

import argparse
import ast
import json
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parent


def inspect_script(path):
    if not path.is_file():
        return "missing_py"
    try:
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    except (SyntaxError, UnicodeError) as exc:
        return f"invalid_python: {exc}"
    if not any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "preprocess_skill"
        for node in tree.body
    ):
        return "entrypoint_not_declared"
    return "present"


def coverage(root, config, platform=None):
    document = yaml.safe_load(config.read_text(encoding="utf-8"))
    rows = []
    for module in document["modules"]:
        for skill in module.get("skills", []):
            restricted = skill.get("platform")
            if platform and restricted and restricted != platform:
                continue
            name = skill["name"]
            if Path(name).name != name or name in (".", "..") or "\\" in name:
                raise ValueError(f"Invalid skill name: {name!r}")
            script = root / "ida_preprocessor_scripts" / f"{name}.py"
            source = root / ".claude/skills" / name / "SKILL.md"
            rows.append(
                {
                    "module": module["name"],
                    "skill": name,
                    "platform": restricted or "windows,linux",
                    "status": inspect_script(script),
                    "skill_md": str(source.relative_to(root)) if source.is_file() else None,
                    "python": str(script.relative_to(root)),
                    "expected_outputs": skill.get("expected_output", []),
                }
            )
    return sorted(rows, key=lambda row: (row["module"], row["skill"], row["platform"]))


def markdown(rows, gamever):
    missing = [row for row in rows if row["status"] == "missing_py"]
    lines = [
        f"# Preprocessor coverage: {gamever}",
        "",
        "Static inventory from config; presence does not prove runtime success or platform support.",
        "Counts are configured module/skill entries, not symbols or binary files.",
        "`entrypoint_not_declared` requires review (the entrypoint may be imported dynamically).",
        "",
        f"Total: {len(rows)}. Missing Python: {len(missing)}. "
        f"Missing Python with SKILL.md: {sum(bool(row['skill_md']) for row in missing)}.",
        "",
        "| Module | Entries | Python present | Missing Python | Other issues |",
        "|---|---:|---:|---:|---:|",
    ]
    for module in sorted({row["module"] for row in rows}):
        group = [row for row in rows if row["module"] == module]
        ready = sum(row["status"] == "present" for row in group)
        absent = sum(row["status"] == "missing_py" for row in group)
        lines.append(f"| {module} | {len(group)} | {ready} | {absent} | {len(group) - ready - absent} |")
    for module in sorted({row["module"] for row in rows}):
        pending = [row for row in rows if row["module"] == module and row["status"] != "present"]
        if not pending:
            continue
        lines.extend(["", f"## {module}", ""])
        for row in pending:
            source = row["skill_md"] or "NO SKILL.md — needs investigation, not conversion"
            lines.append(
                f"- `{row['skill']}` ({row['platform']}): **{row['status']}**; "
                f"source: `{source}`; target: `{row['python']}`"
            )
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gamever", required=True)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--platform", choices=["windows", "linux"])
    parser.add_argument("--output", type=Path, help="Markdown file; defaults to stdout")
    parser.add_argument("--json", type=Path, help="Full machine-readable inventory")
    args = parser.parse_args()
    config = args.config or ROOT / "configs" / f"{args.gamever}.yaml"
    try:
        rows = coverage(ROOT, config, args.platform)
        report = markdown(rows, args.gamever)
        for path, content in ((args.output, report), (args.json, json.dumps(rows, indent=2) + "\n")):
            if path:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
        if not args.output:
            print(report, end="")
    except (OSError, ValueError, yaml.YAMLError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
