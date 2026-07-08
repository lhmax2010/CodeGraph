"""Engine-side protocols shared by routing and adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, Sequence

from ..types import (
    Candidate,
    CallEdgeResult,
    LocationResult,
    Pos,
    ReferenceResult,
)


@dataclass(frozen=True)
class EngineDiagnostics:
    file_not_found: tuple[str, ...] = ()
    fatal: tuple[str, ...] = ()
    soft: tuple[str, ...] = ()


@dataclass(frozen=True)
class EngineObservationResult:
    diagnostics: EngineDiagnostics = field(default_factory=EngineDiagnostics)
    locations: tuple[LocationResult, ...] = ()
    references: tuple[ReferenceResult, ...] = ()
    call_edges: tuple[CallEdgeResult, ...] = ()
    symbol_ambiguous: bool = False
    index_scope_known: bool = True
    total_results: int | None = None


class EngineObservation(Protocol):
    """Semantic engine observation interface consumed by the router."""

    def search_symbol(
        self,
        symbol: str,
        *,
        kind_filter: str | None = None,
        limit: int = 100,
        offset: int = 0,
        request_timeout: float | None = None,
    ) -> EngineObservationResult: ...

    def get_definition(
        self,
        symbol: str,
        file: str,
        pos: Pos,
    ) -> EngineObservationResult: ...

    def find_references(
        self,
        symbol: str,
        file: str,
        pos: Pos,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> EngineObservationResult: ...

    def find_callers(
        self,
        symbol: str,
        file: str,
        pos: Pos,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> EngineObservationResult: ...

    def find_callees(
        self,
        symbol: str,
        file: str,
        pos: Pos,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> EngineObservationResult: ...


class SyntacticProvider(Protocol):
    """Syntactic fallback interface whose outputs stay in candidate channel."""

    def search_candidates(
        self,
        symbol: str,
        *,
        kind_filter: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[Candidate]: ...

    def candidates_near(
        self,
        symbol: str,
        file: str,
        pos: Pos,
        *,
        limit: int = 100,
    ) -> Sequence[Candidate]: ...

    def is_preprocessor_location(self, file: str, pos: Pos) -> bool: ...
