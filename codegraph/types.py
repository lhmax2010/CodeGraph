"""Public dataclasses and enums for CodeGraph query results."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

from .credibility import Credibility


Path = str


@dataclass(frozen=True)
class Pos:
    line: int
    character: int


@dataclass(frozen=True)
class Range:
    start: Pos
    end: Pos


@dataclass(frozen=True)
class SymbolId:
    usr: str | None
    name: str
    file: Path
    pos: Pos


class QueryStatus(str, Enum):
    OK = "ok"
    NOT_FOUND = "not_found"
    UNRESOLVED = "unresolved"
    FAILED = "failed"
    INVALID_REQUEST = "invalid_request"


class IssueCode(str, Enum):
    ENGINE_TIMEOUT = "engine_timeout"
    ENGINE_UNAVAILABLE = "engine_unavailable"
    CALLHIERARCHY_UNSUPPORTED = "callhierarchy_unsupported"
    TREE_SITTER_UNAVAILABLE = "tree_sitter_unavailable"
    INVALID_INPUT = "invalid_input"
    PATH_TRAVERSAL_BLOCKED = "path_traversal_blocked"
    INDEX_INCOMPLETE = "index_incomplete"
    INDEX_UNKNOWN = "index_unknown"
    INDEX_SHARD_EXT_FALLBACK = "index_shard_ext_fallback"
    DEPENDENCY_INCOMPLETE = "dependency_incomplete"
    SYMBOL_AMBIGUOUS = "symbol_ambiguous"
    FALLBACK_DISABLED = "fallback_disabled"
    FALLBACK_SUPPRESSED_BY_SCORE = "fallback_suppressed_by_score"
    NOT_IMPLEMENTED_MVP = "not_implemented_mvp"
    SOFT_WARNING = "soft_warning"


@dataclass(frozen=True)
class QueryMeta:
    kind: str
    symbol: str
    build_config_id: str
    file: Path | None = None
    pos: Pos | None = None


@dataclass
class Note:
    code: IssueCode
    detail: str = ""


@dataclass
class LocationResult:
    symbol_id: SymbolId
    range: Range
    kind: str


@dataclass
class ReferenceResult:
    range: Range
    file: Path
    kind: str


@dataclass
class CallEdgeResult:
    from_symbol: SymbolId
    to_symbol: SymbolId
    call_site: Range


@dataclass
class ImpactResult:
    affected_symbol: SymbolId
    distance: int


ResultData = LocationResult | ReferenceResult | CallEdgeResult | ImpactResult
CandidateData = LocationResult | ReferenceResult


@dataclass
class Result:
    data: ResultData
    credibility: Credibility


@dataclass
class Candidate:
    data: CandidateData
    credibility: Credibility
    relevance_score: int | None
    consumer_warning: Literal["not_evidence"] = "not_evidence"


@dataclass
class QueryResult:
    query: QueryMeta
    status: QueryStatus
    status_credibility: Credibility
    semantic_results: list[Result] = field(default_factory=list)
    syntactic_candidates: list[Candidate] = field(default_factory=list)
    index_health: Literal["complete", "incomplete", "unknown"] = "unknown"
    total_hits: int | None = None
    notes: list[Note] = field(default_factory=list)
