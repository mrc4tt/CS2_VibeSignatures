class SnapshotError(Exception):
    """Base error for snapshot operations."""


class SnapshotConfigError(SnapshotError):
    """Configuration or CLI contract error (exit code 2)."""


class SnapshotSchemaError(SnapshotConfigError):
    """Unsupported or unsafe snapshot schema error."""


class SnapshotMismatchError(SnapshotError):
    """Snapshot data or workspace mismatch (exit code 1)."""
