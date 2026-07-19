from dataclasses import dataclass
from pathlib import Path


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
