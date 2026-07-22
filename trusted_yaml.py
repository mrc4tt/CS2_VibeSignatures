"""Fast, safe YAML loading for trusted repository and generated artifacts."""

from __future__ import annotations

import copy
import os
import threading
from pathlib import Path
from typing import Any

import yaml


SAFE_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)

_CACHE_LOCK = threading.RLock()
_FILE_CACHE: dict[tuple[str, int, int], Any] = {}
_FILE_CACHE_KEY_BY_PATH: dict[str, tuple[str, int, int]] = {}
_MISSING = object()


def load_yaml(data) -> Any:
    """Load trusted YAML with LibYAML when available and SafeLoader otherwise."""
    return yaml.load(data, Loader=SAFE_LOADER)


def _file_identity(path: Path) -> tuple[str, int, int]:
    resolved = path.resolve()
    stat = resolved.stat()
    return os.fspath(resolved), stat.st_mtime_ns, stat.st_size


def load_yaml_file(path, *, cache: bool = False, copy_result: bool = True) -> Any:
    """Load a YAML file, optionally caching it by resolved path and file identity."""
    resolved = Path(path).resolve()
    if not cache:
        return load_yaml(resolved.read_bytes())

    with _CACHE_LOCK:
        cache_key = _file_identity(resolved)
        cached = _FILE_CACHE.get(cache_key, _MISSING)
        if cached is _MISSING:
            payload = load_yaml(resolved.read_bytes())
            previous_key = _FILE_CACHE_KEY_BY_PATH.get(cache_key[0])
            if previous_key is not None and previous_key != cache_key:
                _FILE_CACHE.pop(previous_key, None)
            _FILE_CACHE[cache_key] = payload
            _FILE_CACHE_KEY_BY_PATH[cache_key[0]] = cache_key
            cached = payload
        return copy.deepcopy(cached) if copy_result else cached


def clear_yaml_file_cache(path=None) -> None:
    """Clear all cached YAML files, or only the entry for one resolved path."""
    with _CACHE_LOCK:
        if path is None:
            _FILE_CACHE.clear()
            _FILE_CACHE_KEY_BY_PATH.clear()
            return
        resolved = os.fspath(Path(path).resolve())
        cache_key = _FILE_CACHE_KEY_BY_PATH.pop(resolved, None)
        if cache_key is not None:
            _FILE_CACHE.pop(cache_key, None)
