"""manual_todo.py - the list of symbols left for a person, shared by the run and the IDA plugin.

manual_todo/<gamever>/<module>.<platform>.txt, one line per symbol:
    <Symbol>  <task>  <category> | best <va> (<score>) | <why>
The run (ida_analyze_bin) writes what its hunter and agent could not prove; Ctrl-Alt-D in
IDA writes what its own automatic pass could not. An entry drops out as soon as its
artifact exists, so the file is always what is still left. No dependencies: IDA loads it.
"""
import os

MANUAL_TODO_DIRNAME = "manual_todo"


def manual_todo_path(gamever, module_name, platform, repo_root=None):
    repo = repo_root or os.path.dirname(os.path.abspath(__file__))
    return os.path.join(repo, MANUAL_TODO_DIRNAME, str(gamever), f"{module_name}.{platform}.txt")


def describe_unresolved(row):
    """One line for the manual list: why the hunter stopped, and where to look first."""
    candidates = row.get("candidates") or []
    best = ""
    if candidates:
        first = candidates[0]
        score = first.get("score")
        best = f"best {first.get('va')}" + (f" ({score})" if score is not None else "") + " | "
    return f"{row.get('category', '?')} | {best}{row.get('why', '')}"


def update_manual_todo(path, artifact_dir, platform, entries):
    """Merge {symbol: (task, detail)} into the manual list; entries whose artifact now
    exists drop out, so the file is always what is still left to do."""
    rows = {}
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip() or line.startswith("#"):
                    continue
                parts = line.rstrip("\n").split(None, 2)
                if len(parts) >= 2:
                    rows[parts[0]] = (parts[1], parts[2] if len(parts) > 2 else "")
    rows.update(entries)
    rows = {
        symbol: value for symbol, value in rows.items()
        if not os.path.isfile(os.path.join(artifact_dir, f"{symbol}.{platform}.yaml"))
    }
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(
            "# Left for a person: symbol  task  category | best candidate | why the hunter stopped.\n"
            "# Ctrl-Alt-D in IDA reads this file (jumps to each candidate); push the YAMLs you make.\n"
        )
        for symbol in sorted(rows):
            task, detail = rows[symbol]
            handle.write(f"{symbol:<60} {task:<60} {detail}\n")
    return len(rows)


