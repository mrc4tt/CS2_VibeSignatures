from pathlib import Path

import yaml


def write_yaml(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def write_config(path: Path, modules) -> None:
    write_yaml(path, {"modules": modules})


def module(name: str, skills, *, windows: bool = True, linux: bool = True):
    value = {"name": name, "skills": skills}
    if windows:
        value["path_windows"] = f"game/bin/win64/{name}.dll"
    if linux:
        value["path_linux"] = f"game/bin/linuxsteamrt64/{name}.so"
    return value


def skill(name: str, outputs, **extra):
    return {"name": name, "expected_output": outputs, **extra}
