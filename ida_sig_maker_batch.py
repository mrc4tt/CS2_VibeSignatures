"""Run the cursor-free IDA script over every DLL/SO in one game-version tree."""

import argparse
import ast
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


SCRIPT = Path(__file__).resolve().with_name("ida_sig_maker.py")


def default_queue():
    """Read the user's edited DEFAULT_QUEUE without importing IDAPython."""
    for node in ast.parse(SCRIPT.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "DEFAULT_QUEUE" for target in node.targets
        ):
            return ast.literal_eval(node.value)
    raise ValueError("DEFAULT_QUEUE not found")


def discover(root):
    """Reject output collisions before launching IDA or writing artifacts."""
    jobs, seen = [], set()
    for binary in sorted(root.rglob("*")):
        if not binary.is_file() or binary.suffix.lower() not in (".dll", ".so"):
            continue
        relative = binary.relative_to(root)
        if not binary.resolve().is_relative_to(root.resolve()):
            raise ValueError(f"Binary symlink leaves input root: {binary}")
        module = relative.parts[0] if len(relative.parts) > 1 else binary.stem.removeprefix("lib")
        platform = "windows" if binary.suffix.lower() == ".dll" else "linux"
        key = (module.lower(), platform)
        if key in seen:
            raise ValueError(f"Multiple {platform} binaries map to module {module}; use separate module directories")
        seen.add(key)
        jobs.append((binary, module, platform))
    if not jobs:
        raise ValueError(f"No DLL/SO files under {root}")
    return jobs


def run(args):
    root = args.input.resolve()
    if not root.is_dir():
        raise ValueError(f"Input directory does not exist: {root}")
    jobs = discover(root)
    queue = args.queue.read_text(encoding="utf-8") if args.queue else default_queue()
    if not any(line.strip() and not line.lstrip().startswith("#") for line in queue.splitlines()):
        raise ValueError("Queue is empty")
    rules = json.loads(args.rules.read_text(encoding="utf-8")) if args.rules else {}
    if not isinstance(rules, dict):
        raise ValueError("Rules must be a JSON object keyed by symbol")
    output = args.output.resolve() if args.output else root.parent.parent / "bin_artifacts" / root.name
    report_dir = args.report_dir.resolve() if args.report_dir else root.parent.parent / "sig_maker_reports" / root.name
    ida = shutil.which(args.ida) or (str(Path(args.ida).resolve()) if Path(args.ida).is_file() else None)
    if not args.dry_run and not ida:
        raise ValueError("IDA executable not found; set --ida to IDA Pro 9.1's idat/ida executable")
    if args.timeout <= 0:
        raise ValueError("--timeout must be positive")
    selected_modules = {module for _, module, _ in jobs}
    for entry in queue.splitlines():
        entry = entry.strip()
        if entry and not entry.startswith("#") and "!" in entry:
            owner = entry.split("!", 1)[0]
            if owner not in selected_modules:
                raise ValueError(f"Queue module {owner!r} has no binary under {root}")
    summary = []
    for binary, module, platform in jobs:
        print(f"[batch] {binary} -> {output / module} ({platform})", flush=True)
        if args.dry_run:
            continue
        report_dir.mkdir(parents=True, exist_ok=True)
        # A fresh database prevents destroying or modifying the user's existing IDB.
        with tempfile.TemporaryDirectory(prefix="cs2_sig_maker_") as scratch:
            work = Path(scratch)
            job = {
                "queue": queue,
                "rules": rules,
                "module": module,
                "platform": platform,
                "output_dir": str(output / module),
                "report_path": str(work / "result.json"),
            }
            job_path = work / "job.json"
            job_path.write_text(json.dumps(job), encoding="utf-8")
            env = os.environ.copy()
            env["CS2_SIG_MAKER_JOB"] = str(job_path)
            # A fixed relative script name avoids IDA's separate -S argument quoting parser.
            shutil.copyfile(SCRIPT, work / "runner.py")
            log = report_dir / f"{module}.{platform}.log"
            command = [ida, "-A", f"-L{log}", f"-o{work / 'analysis.i64'}", "-Srunner.py", str(binary)]
            row = {"binary": str(binary), "module": module, "platform": platform}
            try:
                with (report_dir / f"{module}.{platform}.console.log").open("w", encoding="utf-8") as console:
                    process = subprocess.run(
                        command,
                        cwd=work,
                        env=env,
                        stdout=console,
                        stderr=subprocess.STDOUT,
                        timeout=args.timeout,
                        check=False,
                    )
                result_path = work / "result.json"
                if not result_path.is_file():
                    raise ValueError(f"IDA exited {process.returncode} without a result report; inspect {log}")
                result = json.loads(result_path.read_text(encoding="utf-8"))
                row.update(result)
                row["status"] = "ok" if process.returncode == 0 else "failed"
            except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
                row.update(status="failed", reason=str(exc))
            summary.append(row)
            (report_dir / f"{module}.{platform}.json").write_text(json.dumps(row, indent=2) + "\n", encoding="utf-8")
    if not args.dry_run:
        (report_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return int(any(row["status"] != "ok" for row in summary))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="bin/<gamever> directory; searched recursively")
    parser.add_argument("--ida", default=os.environ.get("IDA_EXE", "idat"), help="IDA Pro 9.1 executable")
    parser.add_argument("--queue", type=Path, help="UTF-8 file; one symbol or module!symbol per line")
    parser.add_argument("--rules", type=Path, help="JSON locator rules keyed by symbol")
    parser.add_argument("--output", type=Path, help="Artifact game-version root (contains module folders)")
    parser.add_argument("--report-dir", type=Path)
    parser.add_argument("--timeout", type=float, default=1800, help="Seconds per binary (default: 1800)")
    parser.add_argument(
        "--dry-run", action="store_true", help="List discovered binaries without running IDA or writing"
    )
    args = parser.parse_args()
    try:
        return run(args)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
