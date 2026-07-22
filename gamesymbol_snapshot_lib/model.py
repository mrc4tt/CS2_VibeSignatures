from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ChangedPath:
    status: str
    old_path: str | None
    new_path: str | None

    def __post_init__(self) -> None:
        status = self.status.upper()
        if status not in {"A", "M", "D", "R", "C"}:
            raise ValueError(f"unsupported Git change status: {self.status!r}")
        old_path = self._normalize_path(self.old_path)
        new_path = self._normalize_path(self.new_path)
        if status == "A" and (old_path is not None or new_path is None):
            raise ValueError("added path requires only new_path")
        if status == "D" and (old_path is None or new_path is not None):
            raise ValueError("deleted path requires only old_path")
        if status in {"M", "R", "C"} and (old_path is None or new_path is None):
            raise ValueError(f"{status} path requires old_path and new_path")
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "old_path", old_path)
        object.__setattr__(self, "new_path", new_path)

    @staticmethod
    def _normalize_path(path: str | None) -> str | None:
        if path is None:
            return None
        normalized = path.replace("\\", "/").removeprefix("./")
        if not normalized:
            raise ValueError("changed path must not be empty")
        return normalized


@dataclass(frozen=True)
class SkillNode:
    node_id: str
    logical_key: tuple[str, str, str]
    stage_index: int
    module_name: str
    skill_name: str
    platform: str
    required_outputs: frozenset[str]
    optional_outputs: frozenset[str]
    inputs: frozenset[str]
    prerequisites: tuple[str, ...]
    fingerprint: str

    @property
    def outputs(self) -> frozenset[str]:
        return self.required_outputs | self.optional_outputs


@dataclass(frozen=True)
class SnapshotContract:
    game_version: str
    game_root: Path
    config_digest_version: int
    config_sha256: str
    analysis_output_contract_version: int
    required_paths: frozenset[str]
    optional_paths: frozenset[str]
    owners_by_path: dict[str, frozenset[str]]
    nodes: dict[str, SkillNode]

    @property
    def formal_paths(self) -> frozenset[str]:
        return self.required_paths | self.optional_paths


@dataclass(frozen=True)
class SnapshotContext:
    document: dict
    raw_bytes: bytes
    contract: SnapshotContract


@dataclass(frozen=True)
class InvalidationPlan:
    paths: frozenset[str]
    node_ids: frozenset[str]
    reasons: tuple[str, ...]
