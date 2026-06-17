"""Routing core and QueryResult container invariants for Phase 2."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import replace
from typing import Any

from .credibility import (
    ActiveConfig,
    Certainty,
    Coverage,
    Credibility,
    DepStatus,
    DependencyScope,
    IndexBackend,
    IndexHealth,
    IndexScope,
    NegativeScope,
    QueryKind,
    Relation,
    Resolved,
    Source,
    SymbolKind,
    check_invariants,
    validate,
)
from .engines.protocol import EngineObservationResult, SyntacticProvider
from .factories import make_error_credibility
from .types import (
    CallEdgeResult,
    Candidate,
    CandidateData,
    ImpactResult,
    IssueCode,
    LocationResult,
    Note,
    Pos,
    QueryMeta,
    QueryResult,
    QueryStatus,
    ReferenceResult,
    Result,
    ResultData,
)

_NOT_OK = {
    QueryStatus.NOT_FOUND,
    QueryStatus.UNRESOLVED,
    QueryStatus.FAILED,
    QueryStatus.INVALID_REQUEST,
}
_EXHAUSTIVE_KINDS = {
    SymbolKind.ORDINARY_FUNCTION,
    SymbolKind.ORDINARY_VARIABLE,
    SymbolKind.TYPE,
}
_NOT_FOUND_INDEX_SCOPES = {IndexScope.INDEXED_PROJECT, IndexScope.GLOBAL}


class QueryResultInvariantError(ValueError):
    """QueryResult violates a QR container invariant."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"[{code}] {message}")


def check_query_result_invariants(result: QueryResult) -> None:
    """Enforce QR1-QR9 container-level invariants."""

    has_semantic = bool(result.semantic_results)
    if (result.status == QueryStatus.OK) != has_semantic:
        raise QueryResultInvariantError(
            "QR1", "status=OK iff semantic_results is non-empty"
        )
    if result.status in _NOT_OK and has_semantic:
        raise QueryResultInvariantError("QR2", "non-OK status forbids results")
    if result.status == QueryStatus.NOT_FOUND and result.syntactic_candidates:
        raise QueryResultInvariantError("QR3", "NOT_FOUND forbids candidates")
    if result.status in {QueryStatus.FAILED, QueryStatus.INVALID_REQUEST}:
        if result.syntactic_candidates:
            raise QueryResultInvariantError(
                "QR4", "FAILED/INVALID_REQUEST forbids candidates"
            )

    status_resolved = result.status_credibility.resolved
    if result.status == QueryStatus.NOT_FOUND:
        if status_resolved != Resolved.NOT_FOUND:
            raise QueryResultInvariantError(
                "QR5", "NOT_FOUND requires status credibility not_found"
            )
    elif result.status in {
        QueryStatus.UNRESOLVED,
        QueryStatus.FAILED,
        QueryStatus.INVALID_REQUEST,
    }:
        if status_resolved != Resolved.UNRESOLVED:
            raise QueryResultInvariantError(
                "QR5", "non-OK non-NOT_FOUND requires unresolved credibility"
            )

    for credibility in _item_credibilities(result):
        if credibility.build_config_id != result.query.build_config_id:
            raise QueryResultInvariantError("QR6", "build_config_id mismatch")

    for candidate in result.syntactic_candidates:
        c = candidate.credibility
        if c.resolved != Resolved.RESOLVED:
            raise QueryResultInvariantError("QR7", "candidate must be resolved")
        if c.relation not in {Relation.MAY, Relation.NA}:
            raise QueryResultInvariantError("QR7", "candidate relation must not must")
        if c.certainty != Certainty.SYNTACTIC:
            raise QueryResultInvariantError("QR7", "candidate must be syntactic")
        if candidate.consumer_warning != "not_evidence":
            raise QueryResultInvariantError("QR7", "candidate must be not_evidence")

    query_kind = _query_kind(result.query)
    for credibility in _item_credibilities(result):
        if credibility.query_kind != query_kind:
            raise QueryResultInvariantError("QR8", "query_kind mismatch")

    if result.status == QueryStatus.OK and status_resolved != Resolved.RESOLVED:
        raise QueryResultInvariantError("QR9", "OK requires resolved summary")


def validate_query_result(result: QueryResult) -> QueryResult:
    """Run single credibility invariants and QR1-QR9."""

    check_invariants(result.status_credibility)
    for credibility in _item_credibilities(result):
        check_invariants(credibility)
    check_query_result_invariants(result)
    return result


def route_engine_call(
    query: QueryMeta,
    engine_call: Callable[[], EngineObservationResult],
    *,
    syntactic_provider: SyntacticProvider | None = None,
    allow_syntactic_fallback: bool = False,
    kind_filter: str | None = None,
    limit: int = 100,
    offset: int = 0,
    index_scope: IndexScope = IndexScope.INDEXED_PROJECT,
    index_health: IndexHealth = IndexHealth.COMPLETE,
    index_backend: IndexBackend = IndexBackend.BACKGROUND_INDEX,
    active_config: ActiveConfig = ActiveConfig.UNKNOWN,
    symbol_kind: SymbolKind = SymbolKind.ORDINARY_FUNCTION,
    total_hits: int | None = None,
) -> QueryResult:
    """Route a semantic-engine call; exceptions are FAILED without fallback."""

    try:
        observation = engine_call()
    except Exception as exc:  # noqa: BLE001 - adapter failures are branch 0.
        return _failed_result(query, exc)
    return route_observation(
        query,
        observation,
        syntactic_provider=syntactic_provider,
        allow_syntactic_fallback=allow_syntactic_fallback,
        kind_filter=kind_filter,
        limit=limit,
        offset=offset,
        index_scope=index_scope,
        index_health=index_health,
        index_backend=index_backend,
        active_config=active_config,
        symbol_kind=symbol_kind,
        total_hits=total_hits,
    )


def route_observation(
    query: QueryMeta,
    observation: EngineObservationResult,
    *,
    syntactic_provider: SyntacticProvider | None = None,
    allow_syntactic_fallback: bool = False,
    kind_filter: str | None = None,
    limit: int = 100,
    offset: int = 0,
    index_scope: IndexScope = IndexScope.INDEXED_PROJECT,
    index_health: IndexHealth = IndexHealth.COMPLETE,
    index_backend: IndexBackend = IndexBackend.BACKGROUND_INDEX,
    active_config: ActiveConfig = ActiveConfig.UNKNOWN,
    symbol_kind: SymbolKind = SymbolKind.ORDINARY_FUNCTION,
    total_hits: int | None = None,
) -> QueryResult:
    """Classify a clangd observation into a validated QueryResult."""

    qk = _query_kind(query)
    data = _observation_data(observation)
    dep = _dependency_from_diagnostics(observation)
    notes = (
        [Note(IssueCode.DEPENDENCY_INCOMPLETE)]
        if dep.status != DepStatus.COMPLETE
        else []
    )

    def cred(**kwargs: Any) -> Credibility:
        return _cred(
            qk,
            dep,
            build_config_id=query.build_config_id,
            coverage=kwargs.pop("coverage", Coverage(index_scope=index_scope)),
            active_config=active_config,
            symbol_kind=kwargs.pop("symbol_kind", symbol_kind),
            index_health=index_health,
            index_backend=index_backend,
            **kwargs,
        )

    if data:
        semantic_results: list[Result] = []
        candidates: list[Candidate] = []
        for item in data:
            item_kind = _symbol_kind_for_data(item, symbol_kind)
            blind_spot_affects = _has_preprocessor_blind_spot(syntactic_provider, item)
            coverage = _positive_coverage(observation, index_scope)
            if observation.symbol_ambiguous:
                _append_note_once(notes, IssueCode.SYMBOL_AMBIGUOUS)

            if (
                dep.status == DepStatus.COMPLETE
                and not blind_spot_affects
                and not observation.symbol_ambiguous
            ):
                relation = Relation.NA if qk == QueryKind.ENTITY else Relation.MUST
                semantic_results.append(
                    Result(
                        item,
                        cred(
                            relation=relation,
                            coverage=coverage,
                            symbol_kind=item_kind,
                        ),
                    )
                )
                continue

            candidates.append(
                Candidate(
                    _candidate_data(item),
                    cred(
                        source=Source.CLANGD,
                        certainty=Certainty.SYNTACTIC,
                        relation=(
                            Relation.NA if qk == QueryKind.ENTITY else Relation.MAY
                        ),
                        coverage=coverage,
                        symbol_kind=item_kind,
                        blind_spot_affects_result=blind_spot_affects,
                    ),
                    relevance_score=None,
                )
            )

        if semantic_results:
            return _query_result(
                query,
                QueryStatus.OK,
                cred(
                    relation=Relation.NA,
                    coverage=_positive_coverage(observation, index_scope),
                ),
                semantic_results=semantic_results,
                syntactic_candidates=candidates,
                index_health=index_health,
                total_hits=total_hits if total_hits is not None else len(data),
                notes=notes,
            )

        unresolved = cred(
            certainty=(
                Certainty.SYNTACTIC
                if any(c.credibility.blind_spot_affects_result for c in candidates)
                else Certainty.SEMANTIC
            ),
            resolved=Resolved.UNRESOLVED,
            coverage=Coverage(index_scope=IndexScope.EXTERNAL_UNKNOWN),
            blind_spot_affects_result=any(
                c.credibility.blind_spot_affects_result for c in candidates
            ),
        )
        return _query_result(
            query,
            QueryStatus.UNRESOLVED,
            unresolved,
            syntactic_candidates=candidates,
            index_health=index_health,
            total_hits=total_hits if total_hits is not None else len(data),
            notes=notes,
        )

    if _can_assert_not_found(
        dep, observation, index_scope, index_health, index_backend, symbol_kind
    ):
        return _query_result(
            query,
            QueryStatus.NOT_FOUND,
            _not_found_cred(
                qk,
                dep,
                build_config_id=query.build_config_id,
                index_scope=index_scope,
                active_config=active_config,
                symbol_kind=symbol_kind,
                index_health=index_health,
                index_backend=index_backend,
            ),
            index_health=index_health,
            total_hits=0 if total_hits is None else total_hits,
            notes=notes,
        )

    fallback_candidates, fallback_notes = _fallback_candidates(
        query,
        syntactic_provider,
        allow_syntactic_fallback=allow_syntactic_fallback,
        kind_filter=kind_filter,
        limit=limit,
        offset=offset,
        index_health=index_health,
    )
    notes.extend(fallback_notes)
    return _query_result(
        query,
        QueryStatus.UNRESOLVED,
        cred(
            certainty=Certainty.SYNTACTIC,
            resolved=Resolved.UNRESOLVED,
            coverage=Coverage(index_scope=IndexScope.EXTERNAL_UNKNOWN),
            blind_spot_affects_result=True,
        ),
        syntactic_candidates=fallback_candidates,
        index_health=index_health,
        total_hits=0 if total_hits is None else total_hits,
        notes=notes,
    )


def _query_result(
    query: QueryMeta,
    status: QueryStatus,
    status_credibility: Credibility,
    *,
    semantic_results: Iterable[Result] = (),
    syntactic_candidates: Iterable[Candidate] = (),
    index_health: IndexHealth = IndexHealth.UNKNOWN,
    total_hits: int | None = None,
    notes: Iterable[Note] = (),
) -> QueryResult:
    normalized_notes = list(notes)
    _append_index_health_note(normalized_notes, index_health)
    return validate_query_result(
        QueryResult(
            query=query,
            status=status,
            status_credibility=status_credibility,
            semantic_results=list(semantic_results),
            syntactic_candidates=list(syntactic_candidates),
            index_health=index_health.value,
            total_hits=total_hits,
            notes=normalized_notes,
        )
    )


def _cred(
    query_kind: QueryKind,
    dependency: DependencyScope,
    *,
    build_config_id: str,
    source: Source = Source.CLANGD,
    certainty: Certainty = Certainty.SEMANTIC,
    relation: Relation = Relation.NA,
    resolved: Resolved = Resolved.RESOLVED,
    coverage: Coverage = Coverage(),
    active_config: ActiveConfig = ActiveConfig.UNKNOWN,
    symbol_kind: SymbolKind = SymbolKind.UNKNOWN,
    index_health: IndexHealth = IndexHealth.UNKNOWN,
    index_backend: IndexBackend = IndexBackend.BACKGROUND_INDEX,
    blind_spot_affects_result: bool = False,
) -> Credibility:
    return validate(
        Credibility(
            source=source,
            certainty=certainty,
            relation=relation,
            resolved=resolved,
            query_kind=query_kind,
            dependency=dependency,
            coverage=coverage,
            active_config=(
                ActiveConfig.UNKNOWN if source == Source.TREE_SITTER else active_config
            ),
            build_config_id=build_config_id,
            symbol_kind=symbol_kind,
            index_health=index_health,
            index_backend=index_backend,
            blind_spot_affects_result=blind_spot_affects_result,
        )
    )


def _not_found_cred(
    query_kind: QueryKind,
    dependency: DependencyScope,
    *,
    build_config_id: str,
    index_scope: IndexScope,
    active_config: ActiveConfig,
    symbol_kind: SymbolKind,
    index_health: IndexHealth,
    index_backend: IndexBackend,
) -> Credibility:
    negative_scope = (
        NegativeScope.CURRENT_TU
        if index_backend == IndexBackend.BACKGROUND_INDEX
        else NegativeScope.INDEXED_PROJECT
    )
    return _cred(
        query_kind,
        dependency,
        build_config_id=build_config_id,
        resolved=Resolved.NOT_FOUND,
        coverage=Coverage(
            index_scope=index_scope,
            is_exhaustive_within_scope=True,
            negative_scope=negative_scope,
        ),
        active_config=active_config,
        symbol_kind=symbol_kind,
        index_health=index_health,
        index_backend=index_backend,
    )


def _failed_result(query: QueryMeta, exc: Exception) -> QueryResult:
    return _query_result(
        query,
        QueryStatus.FAILED,
        make_error_credibility(_query_kind(query)),
        index_health=IndexHealth.UNKNOWN,
        notes=[Note(_issue_for_exception(exc), type(exc).__name__)],
    )


def _issue_for_exception(exc: Exception) -> IssueCode:
    if isinstance(exc, TimeoutError):
        return IssueCode.ENGINE_TIMEOUT
    if isinstance(exc, NotImplementedError):
        return IssueCode.CALLHIERARCHY_UNSUPPORTED
    return IssueCode.ENGINE_UNAVAILABLE


def _item_credibilities(result: QueryResult) -> tuple[Credibility, ...]:
    return tuple(r.credibility for r in result.semantic_results) + tuple(
        c.credibility for c in result.syntactic_candidates
    )


def _query_kind(query: QueryMeta) -> QueryKind:
    try:
        return QueryKind(query.kind)
    except ValueError as exc:
        raise QueryResultInvariantError(
            "QR8", f"query.kind must be entity or relation, got {query.kind!r}"
        ) from exc


def _observation_data(observation: EngineObservationResult) -> tuple[ResultData, ...]:
    return (
        tuple(observation.locations)
        + tuple(observation.references)
        + tuple(observation.call_edges)
    )


def _dependency_from_diagnostics(
    observation: EngineObservationResult,
) -> DependencyScope:
    if observation.diagnostics.file_not_found:
        return DependencyScope.incomplete(tuple(observation.diagnostics.file_not_found))
    if observation.diagnostics.fatal:
        return DependencyScope.unknown()
    return DependencyScope.complete()


def _positive_coverage(
    observation: EngineObservationResult, index_scope: IndexScope
) -> Coverage:
    return (
        Coverage(index_scope=index_scope)
        if observation.index_scope_known
        else Coverage(index_scope=IndexScope.EXTERNAL_UNKNOWN)
    )


def _has_preprocessor_blind_spot(
    syntactic_provider: SyntacticProvider | None,
    data: ResultData,
) -> bool:
    if syntactic_provider is None:
        return True
    file, pos = _file_and_pos(data)
    return (
        True
        if file is None or pos is None
        else syntactic_provider.is_preprocessor_location(file, pos)
    )


def _file_and_pos(data: ResultData) -> tuple[str | None, Pos | None]:
    if isinstance(data, LocationResult):
        return data.symbol_id.file, data.symbol_id.pos
    if isinstance(data, ReferenceResult):
        return data.file, data.range.start
    if isinstance(data, CallEdgeResult):
        return data.from_symbol.file, data.call_site.start
    if isinstance(data, ImpactResult):
        return data.affected_symbol.file, data.affected_symbol.pos
    return None, None


def _symbol_kind_for_data(data: ResultData, default: SymbolKind) -> SymbolKind:
    if not isinstance(data, (LocationResult, ReferenceResult)):
        return default
    try:
        return SymbolKind(data.kind)
    except ValueError:
        return SymbolKind.UNKNOWN


def _candidate_data(data: ResultData) -> CandidateData:
    if isinstance(data, (LocationResult, ReferenceResult, CallEdgeResult)):
        return data
    raise TypeError(
        f"Unsupported candidate data for Phase 2 routing: {type(data).__name__}"
    )


def _can_assert_not_found(
    dependency: DependencyScope,
    observation: EngineObservationResult,
    index_scope: IndexScope,
    index_health: IndexHealth,
    index_backend: IndexBackend,
    symbol_kind: SymbolKind,
) -> bool:
    if (
        index_backend == IndexBackend.BACKGROUND_INDEX
        and index_scope == IndexScope.GLOBAL
    ):
        return False
    return (
        dependency.status == DepStatus.COMPLETE
        and observation.index_scope_known
        and index_scope in _NOT_FOUND_INDEX_SCOPES
        and index_health == IndexHealth.COMPLETE
        and symbol_kind in _EXHAUSTIVE_KINDS
    )


def _fallback_candidates(
    query: QueryMeta,
    syntactic_provider: SyntacticProvider | None,
    *,
    allow_syntactic_fallback: bool,
    kind_filter: str | None,
    limit: int,
    offset: int,
    index_health: IndexHealth,
) -> tuple[list[Candidate], list[Note]]:
    if not (_is_search_query(query) or allow_syntactic_fallback):
        return [], [Note(IssueCode.FALLBACK_DISABLED)]
    if syntactic_provider is None:
        return [], [Note(IssueCode.TREE_SITTER_UNAVAILABLE)]
    if _is_search_query(query):
        raw = syntactic_provider.search_candidates(
            query.symbol, kind_filter=kind_filter, limit=limit, offset=offset
        )
        threshold = 15
    else:
        if query.file is None or query.pos is None:
            return [], [Note(IssueCode.INVALID_INPUT)]
        raw = syntactic_provider.candidates_near(
            query.symbol, query.file, query.pos, limit=limit
        )
        threshold = 20

    kept = [
        _normalize_fallback_candidate(query, candidate, index_health)
        for candidate in raw
        if candidate.relevance_score is not None
        and candidate.relevance_score >= threshold
    ]
    return kept, (
        [Note(IssueCode.FALLBACK_SUPPRESSED_BY_SCORE)] if raw and not kept else []
    )


def _normalize_fallback_candidate(
    query: QueryMeta, candidate: Candidate, index_health: IndexHealth
) -> Candidate:
    query_kind = _query_kind(query)
    return replace(
        candidate,
        credibility=_cred(
            query_kind,
            DependencyScope.not_applicable(),
            build_config_id=query.build_config_id,
            source=Source.TREE_SITTER,
            certainty=Certainty.SYNTACTIC,
            relation=Relation.NA if query_kind == QueryKind.ENTITY else Relation.MAY,
            coverage=Coverage(index_scope=IndexScope.EXTERNAL_UNKNOWN),
            symbol_kind=candidate.credibility.symbol_kind,
            index_health=index_health,
        ),
        consumer_warning="not_evidence",
    )


def _is_search_query(query: QueryMeta) -> bool:
    return query.file is None and query.pos is None


def _append_note_once(notes: list[Note], code: IssueCode) -> None:
    if not any(note.code == code for note in notes):
        notes.append(Note(code))


def _append_index_health_note(notes: list[Note], index_health: IndexHealth) -> None:
    if index_health == IndexHealth.INCOMPLETE:
        _append_note_once(notes, IssueCode.INDEX_INCOMPLETE)
    elif index_health == IndexHealth.UNKNOWN:
        _append_note_once(notes, IssueCode.INDEX_UNKNOWN)
