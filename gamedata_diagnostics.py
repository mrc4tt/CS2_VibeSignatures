from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class GamedataDiagnostic:
    reason: str
    severity: str
    module: str
    symbol: str
    category: str
    platform: str
    canonical_path: str
    attempted_paths: tuple[str, ...] = ()
    detail: str | None = None


@dataclass
class AggregatedDiagnostic:
    diagnostic: GamedataDiagnostic
    contexts: set[str] = field(default_factory=set)
    observation_count: int = 0


def diagnostic_key(diagnostic: GamedataDiagnostic) -> tuple:
    return (
        diagnostic.reason,
        diagnostic.module,
        diagnostic.symbol,
        diagnostic.category,
        diagnostic.platform,
        diagnostic.canonical_path,
        diagnostic.attempted_paths,
    )


def diagnostic_sort_key(diagnostic: GamedataDiagnostic) -> tuple:
    severity_order = {"error": 0, "warning": 1, "info": 2}
    return (
        severity_order.get(diagnostic.severity, 99),
        diagnostic.reason,
        diagnostic.module,
        diagnostic.symbol,
        diagnostic.platform,
        diagnostic.canonical_path,
        diagnostic.attempted_paths,
    )


def unique_diagnostics(diagnostics) -> list[GamedataDiagnostic]:
    unique = {}
    for diagnostic in diagnostics:
        unique.setdefault(diagnostic_key(diagnostic), diagnostic)
    return sorted(unique.values(), key=diagnostic_sort_key)


def diagnostic_delta(current, baseline) -> list[GamedataDiagnostic]:
    baseline_keys = {diagnostic_key(item) for item in baseline}
    return [item for item in unique_diagnostics(current) if diagnostic_key(item) not in baseline_keys]


class DiagnosticAggregator:
    def __init__(self) -> None:
        self._aggregates: dict[tuple, AggregatedDiagnostic] = {}

    def add(self, context: str, diagnostics) -> None:
        for diagnostic in diagnostics:
            key = diagnostic_key(diagnostic)
            aggregate = self._aggregates.setdefault(key, AggregatedDiagnostic(diagnostic))
            aggregate.contexts.add(context)
            aggregate.observation_count += 1

    def aggregates(self) -> list[AggregatedDiagnostic]:
        return sorted(self._aggregates.values(), key=lambda item: diagnostic_sort_key(item.diagnostic))

    def warning_aggregates(self) -> list[AggregatedDiagnostic]:
        return [item for item in self.aggregates() if item.diagnostic.severity == "warning"]

    @property
    def unique_warning_count(self) -> int:
        return len(self.warning_aggregates())

    @property
    def warning_observation_count(self) -> int:
        return sum(item.observation_count for item in self.warning_aggregates())

    @property
    def duplicate_warning_count(self) -> int:
        return self.warning_observation_count - self.unique_warning_count


def _warning_diagnostics(diagnostics) -> list[GamedataDiagnostic]:
    return [item for item in unique_diagnostics(diagnostics) if item.severity == "warning"]


def print_overlay_diagnostics(diagnostics) -> None:
    warnings = _warning_diagnostics(diagnostics)
    if not warnings:
        return
    print(f"  Overlay YAML diagnostics: {len(warnings)}")
    for diagnostic in warnings:
        print(f"    - {diagnostic.canonical_path}")


def print_resolved_diagnostics(diagnostics) -> None:
    warnings = _warning_diagnostics(diagnostics)
    if not warnings:
        return
    print(f"  Overlay-resolved YAML diagnostics: {len(warnings)}")
    for diagnostic in warnings:
        print(f"    - {diagnostic.canonical_path}")


def print_diagnostic_summary(aggregator: DiagnosticAggregator, *, debug: bool) -> None:
    print("\nYAML diagnostic summary:")
    print(f"  Unique warning diagnostics: {aggregator.unique_warning_count}")
    print(f"  Warning observations: {aggregator.warning_observation_count}")
    print(f"  Duplicate observations suppressed: {aggregator.duplicate_warning_count}")
    if not debug:
        return
    for aggregate in aggregator.aggregates():
        diagnostic = aggregate.diagnostic
        attempted = diagnostic.attempted_paths or (diagnostic.canonical_path,)
        print(
            f"  - [{diagnostic.severity}/{diagnostic.reason}] {diagnostic.canonical_path} "
            f"(contexts: {', '.join(sorted(aggregate.contexts))}; observations: {aggregate.observation_count})"
        )
        if len(attempted) > 1:
            print(f"    attempted: {', '.join(attempted)}")
        if diagnostic.detail:
            print(f"    detail: {diagnostic.detail}")
