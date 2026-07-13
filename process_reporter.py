"""Pure domain models shared by process reporter implementations."""

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class RunStatus(str, Enum):
    QUEUED = "queued"
    STARTING = "starting"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    ABORTED = "aborted"
    STALE = "stale"


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
    ABORTED = "aborted"


class ProcessPhase(str, Enum):
    PREFLIGHT = "preflight"
    WAITING_FOR_MCP = "waiting_for_mcp"
    VALIDATING_BINARY = "validating_binary"
    VALIDATING_INPUTS = "validating_inputs"
    PREPROCESSING = "preprocessing"
    VALIDATING_OUTPUTS = "validating_outputs"
    AGENT_FALLBACK = "agent_fallback"
    VCALL_EXPORT = "vcall_export"
    POSTPROCESSING = "postprocessing"
    FINISHED = "finished"


class ProcessEventType(str, Enum):
    RUN_INITIALIZED = "run.initialized"
    RUN_STATUS_CHANGED = "run.status_changed"
    TASK_STATUS_CHANGED = "task.status_changed"
    SKILL_PROGRESS = "skill.progress"
    HEARTBEAT = "heartbeat"


class ProcessReason(str, Enum):
    EXISTING_OUTPUTS = "existing_outputs"
    SKIP_IF_EXISTS = "skip_if_exists"
    PLATFORM_MISMATCH = "platform_mismatch"
    MISSING_BINARY = "missing_binary"
    MISSING_INPUT = "missing_input"
    INVALID_INPUT = "invalid_input"
    PREPROCESS_ABSENT = "preprocess_absent"
    OPTIONAL_OUTPUT_ABSENT = "optional_output_absent"
    PREPROCESS_FAILED = "preprocess_failed"
    AGENT_FAILED = "agent_failed"
    MCP_UNAVAILABLE = "mcp_unavailable"
    BINARY_VERIFICATION_FAILED = "binary_verification_failed"
    UPSTREAM_ABORTED = "upstream_aborted"
    GRAPH_INVALID = "graph_invalid"
    UNKNOWN_ERROR = "unknown_error"


class EdgeType(str, Enum):
    ARTIFACT = "artifact"
    PREREQUISITE = "prerequisite"
    CROSS_STAGE_ARTIFACT = "cross_stage_artifact"
    STAGE_ORDER = "stage_order"


class PlanNodeType(str, Enum):
    SKILL = "skill"
    VCALL_TARGET = "vcall_target"
    POST_PROCESS = "post_process"


@dataclass(frozen=True)
class SkillEdge:
    source: str
    target: str
    edge_type: EdgeType
    artifact: str | None = None


@dataclass(frozen=True)
class SkillGraph:
    nodes: dict[str, dict[str, Any]]
    edges: list[SkillEdge]
    order: list[str]
    layers: dict[str, int]
    cycles: list[list[str]]
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ExecutionStage:
    id: str
    stage_index: int
    module_name: str


@dataclass(frozen=True)
class ExecutionJob:
    id: str
    stage_id: str
    stage_index: int
    module_name: str
    platform: str
    binary_path: str | None


@dataclass(frozen=True)
class ExecutionNode:
    id: str
    job_id: str
    stage_id: str
    name: str
    node_type: PlanNodeType
    order: int
    layer: int
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecutionEdge:
    source: str
    target: str
    edge_type: EdgeType
    artifact: str | None = None


@dataclass(frozen=True)
class ExecutionPlan:
    stages: list[ExecutionStage] = field(default_factory=list)
    jobs: list[ExecutionJob] = field(default_factory=list)
    nodes: list[ExecutionNode] = field(default_factory=list)
    edges: list[ExecutionEdge] = field(default_factory=list)
    warnings: list[str | ProcessReason] = field(default_factory=list)
    schema_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        """Return the stable JSON-compatible API representation."""
        return _serialize(asdict(self))


def _serialize(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialize(item) for item in value]
    return value


def _validate_id_part(value: object, label: str) -> str:
    normalized = str(value).strip()
    if not normalized or "/" in normalized:
        raise ValueError(f"{label} must be non-empty and cannot contain '/'")
    return normalized


def build_stage_id(stage_index: int, module_name: str) -> str:
    """Build an ID that remains unique when module names repeat."""
    if stage_index < 0:
        raise ValueError("stage_index must be non-negative")
    return f"stage-{stage_index:04d}-{_validate_id_part(module_name, 'module_name')}"


def build_job_id(stage_id: str, platform: str) -> str:
    return f"{_validate_id_part(stage_id, 'stage_id')}-{_validate_id_part(platform, 'platform')}"


def build_task_id(job_id: str, task_name: str) -> str:
    return f"{_validate_id_part(job_id, 'job_id')}/{_validate_id_part(task_name, 'task_name')}"


def build_vcall_task_id(job_id: str, target_name: str) -> str:
    job_part = _validate_id_part(job_id, "job_id")
    return f"{job_part}/vcall/{_validate_id_part(target_name, 'target_name')}"


def build_post_process_task_id(job_id: str) -> str:
    return f"{_validate_id_part(job_id, 'job_id')}/post-process"


_TASK_TRANSITIONS = {
    TaskStatus.PENDING: {
        TaskStatus.RUNNING,
        TaskStatus.SKIPPED,
        TaskStatus.ABORTED,
    },
    TaskStatus.RUNNING: {
        TaskStatus.SUCCEEDED,
        TaskStatus.FAILED,
        TaskStatus.ABORTED,
    },
}

_RUN_TRANSITIONS = {
    RunStatus.QUEUED: {RunStatus.STARTING, RunStatus.FAILED, RunStatus.ABORTED},
    RunStatus.STARTING: {RunStatus.RUNNING, RunStatus.FAILED, RunStatus.ABORTED, RunStatus.STALE},
    RunStatus.RUNNING: {RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.ABORTED, RunStatus.STALE},
    RunStatus.STALE: {RunStatus.RUNNING, RunStatus.FAILED, RunStatus.ABORTED},
}


def is_valid_task_transition(current: TaskStatus, target: TaskStatus) -> bool:
    """Accept idempotent writes and reject transitions out of terminal states."""
    return current == target or target in _TASK_TRANSITIONS.get(current, set())


def is_valid_run_transition(current: RunStatus, target: RunStatus) -> bool:
    """Accept idempotent writes and allow a stale run to recover."""
    return current == target or target in _RUN_TRANSITIONS.get(current, set())
