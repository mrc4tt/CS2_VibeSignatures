class SnapshotError(Exception):
    """Base error for snapshot operations."""


class SnapshotConfigError(SnapshotError):
    """Configuration or CLI contract error (exit code 2)."""


class SnapshotSchemaError(SnapshotConfigError):
    """Unsupported or unsafe snapshot schema error."""

    def __init__(self, message: str, *, reason: str = "snapshot_contract_mismatch"):
        super().__init__(message)
        self.reason = reason


class SnapshotMismatchError(SnapshotError):
    """Snapshot data or workspace mismatch (exit code 1)."""

    def __init__(self, message: str, *, reason: str | None = None):
        super().__init__(message)
        self.reason = reason


class SnapshotUntrustedError(SnapshotError):
    """Snapshot content cannot be trusted as a disposable PR baseline (exit code 3)."""

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason
