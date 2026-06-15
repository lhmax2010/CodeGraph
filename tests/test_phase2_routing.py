from __future__ import annotations

import pytest

from codegraph.credibility import (
    ActiveConfig,
    Certainty,
    Coverage,
    Credibility,
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
)
from codegraph.engines.protocol import EngineDiagnostics, EngineObservationResult
from codegraph.routing import (
    QueryResultInvariantError,
    _candidate_data,
    check_query_result_invariants,
    route_engine_call,
    route_observation,
    validate_query_result,
)
from codegraph.types import (
    CallEdgeResult,
    Candidate,
    ImpactResult,
    IssueCode,
    LocationResult,
    Pos,
    QueryMeta,
    QueryResult,
    QueryStatus,
    Range,
    ReferenceResult,
    Result,
    SymbolId,
)

DEP_OK = DependencyScope.complete()
BUILD = "arm"


class FakeSyntacticProvider:
    def __init__(
        self,
        candidates: tuple[Candidate, ...] = (),
        preproc: frozenset[tuple[str, int]] = frozenset(),
    ):
        self.candidates = candidates
        self.preproc = preproc

    def search_candidates(
        self,
        symbol: str,
        *,
        kind_filter: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[Candidate, ...]:
        return self.candidates[offset : offset + limit]

    def candidates_near(
        self, symbol: str, file: str, pos: Pos, *, limit: int = 100
    ) -> tuple[Candidate, ...]:
        return self.candidates[:limit]

    def is_preprocessor_location(self, file: str, pos: Pos) -> bool:
        return (file, pos.line) in self.preproc


def q(kind: QueryKind = QueryKind.ENTITY, *, file: str | None = None) -> QueryMeta:
    pos = Pos(1, 0) if file else None
    return QueryMeta(kind.value, "fn", BUILD, file=file, pos=pos)


def loc(
    line: int = 1, *, kind: str = SymbolKind.ORDINARY_FUNCTION.value
) -> LocationResult:
    pos = Pos(line, 0)
    return LocationResult(
        SymbolId(f"usr:{line}", "fn", "/tmp/a.c", pos),
        Range(pos, Pos(line, 2)),
        kind,
    )


def ref(line: int = 1, file: str = "/tmp/a.c") -> ReferenceResult:
    return ReferenceResult(Range(Pos(line, 0), Pos(line, 2)), file, "reference")


def edge(line: int = 1) -> CallEdgeResult:
    caller = SymbolId("usr:caller", "caller", "/tmp/caller.c", Pos(0, 0))
    callee = SymbolId("usr:fn", "fn", "/tmp/callee.c", Pos(10, 0))
    return CallEdgeResult(caller, callee, Range(Pos(line, 4), Pos(line, 8)))


def impact() -> ImpactResult:
    symbol = SymbolId("usr:affected", "affected", "/tmp/impact.c", Pos(20, 0))
    return ImpactResult(symbol, 1)


def cred(
    *,
    qk: QueryKind = QueryKind.ENTITY,
    source: Source = Source.CLANGD,
    certainty: Certainty = Certainty.SEMANTIC,
    relation: Relation = Relation.NA,
    resolved: Resolved = Resolved.RESOLVED,
    build: str = BUILD,
) -> Credibility:
    return Credibility(
        source,
        certainty,
        relation,
        resolved,
        qk,
        DEP_OK if source == Source.CLANGD else DependencyScope.not_applicable(),
        Coverage(
            IndexScope.INDEXED_PROJECT,
            resolved == Resolved.NOT_FOUND,
            (
                NegativeScope.CURRENT_TU
                if resolved == Resolved.NOT_FOUND
                else NegativeScope.NONE
            ),
        ),
        ActiveConfig.UNKNOWN,
        build,
        SymbolKind.ORDINARY_FUNCTION,
        IndexHealth.COMPLETE,
    )


def unresolved(qk: QueryKind = QueryKind.ENTITY) -> Credibility:
    return Credibility(
        Source.CLANGD,
        Certainty.SYNTACTIC,
        Relation.NA,
        Resolved.UNRESOLVED,
        qk,
        DEP_OK,
        Coverage(IndexScope.EXTERNAL_UNKNOWN),
        build_config_id=BUILD,
        blind_spot_affects_result=True,
    )


def cand(
    qk: QueryKind = QueryKind.ENTITY,
    *,
    relation: Relation | None = None,
    score: int | None = 20,
    build: str = BUILD,
) -> Candidate:
    relation = relation or (Relation.NA if qk == QueryKind.ENTITY else Relation.MAY)
    data = loc() if qk == QueryKind.ENTITY else ref()
    return Candidate(
        data,
        Credibility(
            Source.TREE_SITTER,
            Certainty.SYNTACTIC,
            relation,
            Resolved.RESOLVED,
            qk,
            DependencyScope.not_applicable(),
            Coverage(IndexScope.EXTERNAL_UNKNOWN),
            ActiveConfig.UNKNOWN,
            build,
        ),
        score,
    )


def ok_result() -> QueryResult:
    return QueryResult(
        q(),
        QueryStatus.OK,
        cred(),
        semantic_results=[Result(loc(), cred())],
        index_health=IndexHealth.COMPLETE.value,
    )


def codes(result: QueryResult) -> set[IssueCode]:
    return {note.code for note in result.notes}


def assert_qr(code: str, result: QueryResult) -> None:
    with pytest.raises(QueryResultInvariantError) as exc:
        check_query_result_invariants(result)
    assert exc.value.code == code


def test_container_qr_core_rejections():
    result = ok_result()
    result.semantic_results = []
    assert_qr("QR1", result)

    result = ok_result()
    result.status = QueryStatus.UNRESOLVED
    result.status_credibility = unresolved()
    assert_qr("QR1", result)

    assert_qr(
        "QR3",
        QueryResult(
            q(),
            QueryStatus.NOT_FOUND,
            cred(resolved=Resolved.NOT_FOUND),
            syntactic_candidates=[cand()],
        ),
    )
    assert_qr(
        "QR4",
        QueryResult(
            q(), QueryStatus.FAILED, unresolved(), syntactic_candidates=[cand()]
        ),
    )
    assert_qr("QR5", QueryResult(q(), QueryStatus.NOT_FOUND, unresolved()))
    assert_qr("QR5", QueryResult(q(), QueryStatus.UNRESOLVED, cred()))

    result = ok_result()
    result.semantic_results[0].credibility = cred(build="x86")
    assert_qr("QR6", result)

    result = ok_result()
    result.query = QueryMeta("bogus", "fn", BUILD)
    assert_qr("QR8", result)

    result = ok_result()
    result.status_credibility = unresolved()
    assert_qr("QR9", result)


def test_qr7_accepts_may_or_na_candidates_and_rejects_other_shapes():
    check_query_result_invariants(
        QueryResult(
            q(), QueryStatus.UNRESOLVED, unresolved(), syntactic_candidates=[cand()]
        )
    )
    check_query_result_invariants(
        QueryResult(
            q(QueryKind.RELATION),
            QueryStatus.UNRESOLVED,
            unresolved(QueryKind.RELATION),
            syntactic_candidates=[cand(QueryKind.RELATION)],
        )
    )

    bad = QueryResult(
        q(), QueryStatus.UNRESOLVED, unresolved(), syntactic_candidates=[cand()]
    )
    bad.syntactic_candidates[0].credibility = Credibility(
        Source.TREE_SITTER,
        Certainty.SYNTACTIC,
        Relation.MUST,
        Resolved.RESOLVED,
        QueryKind.ENTITY,
        DependencyScope.not_applicable(),
        build_config_id=BUILD,
    )
    assert_qr("QR7", bad)

    for changed in (
        {"resolved": Resolved.UNRESOLVED},
        {"certainty": Certainty.SEMANTIC},
    ):
        bad = QueryResult(
            q(), QueryStatus.UNRESOLVED, unresolved(), syntactic_candidates=[cand()]
        )
        old = bad.syntactic_candidates[0].credibility
        bad.syntactic_candidates[0].credibility = Credibility(
            old.source,
            changed.get("certainty", old.certainty),
            old.relation,
            changed.get("resolved", old.resolved),
            old.query_kind,
            old.dependency,
            old.coverage,
            old.active_config,
            old.build_config_id,
        )
        assert_qr("QR7", bad)

    bad = QueryResult(
        q(), QueryStatus.UNRESOLVED, unresolved(), syntactic_candidates=[cand()]
    )
    bad.syntactic_candidates[0].consumer_warning = "evidence"
    assert_qr("QR7", bad)


def test_validate_query_result_runs_single_credibility_invariants():
    result = ok_result()
    result.semantic_results[0].credibility = Credibility(
        Source.TREE_SITTER,
        Certainty.SEMANTIC,
        Relation.NA,
        Resolved.RESOLVED,
        QueryKind.ENTITY,
        DependencyScope.not_applicable(),
        build_config_id=BUILD,
    )
    with pytest.raises(Exception) as exc:
        validate_query_result(result)
    assert "INV1" in str(exc.value)


@pytest.mark.parametrize(
    ("exc", "code"),
    [
        (TimeoutError("slow"), IssueCode.ENGINE_TIMEOUT),
        (NotImplementedError("callHierarchy"), IssueCode.CALLHIERARCHY_UNSUPPORTED),
        (RuntimeError("down"), IssueCode.ENGINE_UNAVAILABLE),
    ],
)
def test_route_engine_exceptions_are_failed_without_fallback(
    exc: Exception, code: IssueCode
):
    result = route_engine_call(
        q(),
        lambda: (_ for _ in ()).throw(exc),
        syntactic_provider=FakeSyntacticProvider((cand(score=99),)),
    )
    assert result.status == QueryStatus.FAILED
    assert result.syntactic_candidates == []
    assert codes(result) == {code, IssueCode.INDEX_UNKNOWN}


def test_route_nonempty_evidence_classification_and_branch_separation():
    assert (
        route_engine_call(
            q(),
            lambda: EngineObservationResult(locations=(loc(),)),
            syntactic_provider=FakeSyntacticProvider(),
        ).status
        == QueryStatus.OK
    )

    dep_bad = route_observation(
        q(),
        EngineObservationResult(
            diagnostics=EngineDiagnostics(file_not_found=("missing.h",)),
            locations=(loc(),),
        ),
    )
    assert dep_bad.status == QueryStatus.UNRESOLVED
    assert (
        dep_bad.syntactic_candidates[0].credibility.dependency.status.value
        == "incomplete"
    )
    assert IssueCode.DEPENDENCY_INCOMPLETE in codes(dep_bad)

    preproc = route_observation(
        q(),
        EngineObservationResult(locations=(loc(2),)),
        syntactic_provider=FakeSyntacticProvider(preproc=frozenset({("/tmp/a.c", 2)})),
    )
    assert preproc.status == QueryStatus.UNRESOLVED
    assert preproc.syntactic_candidates[0].credibility.blind_spot_affects_result is True

    ambiguous = route_observation(
        q(), EngineObservationResult(locations=(loc(1), loc(2)), symbol_ambiguous=True)
    )
    assert ambiguous.status == QueryStatus.UNRESOLVED
    assert len(ambiguous.syntactic_candidates) == 2
    assert [n.code for n in ambiguous.notes].count(IssueCode.SYMBOL_AMBIGUOUS) == 1

    mixed = route_observation(
        q(),
        EngineObservationResult(locations=(loc(1), loc(2))),
        syntactic_provider=FakeSyntacticProvider(preproc=frozenset({("/tmp/a.c", 2)})),
    )
    assert mixed.status == QueryStatus.OK
    assert len(mixed.semantic_results) == len(mixed.syntactic_candidates) == 1

    unknown_index = route_observation(
        q(),
        EngineObservationResult(locations=(loc(),), index_scope_known=False),
        syntactic_provider=FakeSyntacticProvider(),
    )
    assert (
        unknown_index.semantic_results[0].credibility.coverage.index_scope
        == IndexScope.EXTERNAL_UNKNOWN
    )


def test_route_reference_call_edge_and_unknown_kind_edges():
    refs = route_observation(
        q(),
        EngineObservationResult(references=(ref(1), ref(2))),
        syntactic_provider=FakeSyntacticProvider(preproc=frozenset({("/tmp/a.c", 2)})),
    )
    assert refs.status == QueryStatus.OK
    assert len(refs.syntactic_candidates) == 1

    relation = route_observation(
        q(QueryKind.RELATION),
        EngineObservationResult(call_edges=(edge(7),), symbol_ambiguous=True),
    )
    edge_data = relation.syntactic_candidates[0].data
    assert isinstance(edge_data, CallEdgeResult)
    assert edge_data.from_symbol.name == "caller"
    assert edge_data.to_symbol.name == "fn"
    assert relation.syntactic_candidates[0].credibility.relation == Relation.MAY

    weird = loc()
    weird.kind = "compiler_magic"
    result = route_observation(
        q(),
        EngineObservationResult(locations=(weird,)),
        syntactic_provider=FakeSyntacticProvider(),
    )
    assert result.semantic_results[0].credibility.symbol_kind == SymbolKind.UNKNOWN


def test_impact_result_never_enters_candidate_data():
    with pytest.raises(TypeError, match="ImpactResult"):
        _candidate_data(impact())


def test_empty_result_not_found_and_unresolved_boundaries():
    not_found = route_observation(
        q(),
        EngineObservationResult(),
        index_scope=IndexScope.INDEXED_PROJECT,
        index_health=IndexHealth.COMPLETE,
        symbol_kind=SymbolKind.ORDINARY_FUNCTION,
    )
    assert not_found.status == QueryStatus.NOT_FOUND
    assert (
        not_found.status_credibility.coverage.negative_scope == NegativeScope.CURRENT_TU
    )

    global_background = route_observation(
        q(),
        EngineObservationResult(),
        index_scope=IndexScope.GLOBAL,
        index_health=IndexHealth.COMPLETE,
        index_backend=IndexBackend.BACKGROUND_INDEX,
        symbol_kind=SymbolKind.ORDINARY_FUNCTION,
    )
    assert global_background.status == QueryStatus.UNRESOLVED

    fatal = route_observation(
        q(), EngineObservationResult(diagnostics=EngineDiagnostics(fatal=("fatal",)))
    )
    assert fatal.status == QueryStatus.UNRESOLVED
    assert fatal.status_credibility.dependency.status.value == "unknown"


def test_missing_syntax_helper_downgrades_element2_only():
    ordinary = route_observation(q(), EngineObservationResult(locations=(loc(),)))
    assert ordinary.status == QueryStatus.UNRESOLVED
    assert ordinary.semantic_results == []
    assert (
        ordinary.syntactic_candidates[0].credibility.blind_spot_affects_result is True
    )

    macro = route_observation(
        q(), EngineObservationResult(locations=(loc(kind=SymbolKind.MACRO.value),))
    )
    assert macro.status == QueryStatus.UNRESOLVED
    assert macro.semantic_results == []
    assert macro.syntactic_candidates[0].credibility.blind_spot_affects_result is True


def test_index_health_notes_are_structured_and_deduplicated():
    incomplete_index = route_observation(
        q(), EngineObservationResult(), index_health=IndexHealth.INCOMPLETE
    )
    assert incomplete_index.status == QueryStatus.UNRESOLVED
    assert IssueCode.INDEX_INCOMPLETE in codes(incomplete_index)

    unknown_index = route_observation(
        q(), EngineObservationResult(), index_health=IndexHealth.UNKNOWN
    )
    assert unknown_index.status == QueryStatus.UNRESOLVED
    assert [n.code for n in unknown_index.notes].count(IssueCode.INDEX_UNKNOWN) == 1


def test_fallback_thresholds_switches_and_candidate_normalization():
    search = route_observation(
        q(),
        EngineObservationResult(index_scope_known=False),
        syntactic_provider=FakeSyntacticProvider((cand(score=14), cand(score=15))),
        symbol_kind=SymbolKind.FUNC_POINTER,
    )
    assert [c.relevance_score for c in search.syntactic_candidates] == [15]
    assert search.syntactic_candidates[0].credibility.build_config_id == BUILD

    suppressed = route_observation(
        q(),
        EngineObservationResult(index_scope_known=False),
        syntactic_provider=FakeSyntacticProvider((cand(score=14),)),
        symbol_kind=SymbolKind.FUNC_POINTER,
    )
    assert suppressed.syntactic_candidates == []
    assert IssueCode.FALLBACK_SUPPRESSED_BY_SCORE in codes(suppressed)

    disabled = route_observation(
        q(file="/tmp/a.c"),
        EngineObservationResult(index_scope_known=False),
        syntactic_provider=FakeSyntacticProvider((cand(score=99),)),
        symbol_kind=SymbolKind.FUNC_POINTER,
    )
    assert disabled.syntactic_candidates == []
    assert IssueCode.FALLBACK_DISABLED in codes(disabled)

    exact = route_observation(
        q(file="/tmp/a.c"),
        EngineObservationResult(index_scope_known=False),
        syntactic_provider=FakeSyntacticProvider((cand(score=19), cand(score=20))),
        allow_syntactic_fallback=True,
        symbol_kind=SymbolKind.FUNC_POINTER,
    )
    assert [c.relevance_score for c in exact.syntactic_candidates] == [20]

    invalid = route_observation(
        QueryMeta(QueryKind.ENTITY.value, "fn", BUILD, pos=Pos(1, 0)),
        EngineObservationResult(index_scope_known=False),
        syntactic_provider=FakeSyntacticProvider((cand(score=99),)),
        allow_syntactic_fallback=True,
        symbol_kind=SymbolKind.FUNC_POINTER,
    )
    assert IssueCode.INVALID_INPUT in codes(invalid)

    unavailable = route_observation(
        q(),
        EngineObservationResult(index_scope_known=False),
        symbol_kind=SymbolKind.FUNC_POINTER,
    )
    assert IssueCode.TREE_SITTER_UNAVAILABLE in codes(unavailable)

    relation = route_observation(
        q(QueryKind.RELATION),
        EngineObservationResult(index_scope_known=False),
        syntactic_provider=FakeSyntacticProvider((cand(QueryKind.RELATION),)),
        symbol_kind=SymbolKind.FUNC_POINTER,
    )
    assert relation.syntactic_candidates[0].credibility.relation == Relation.MAY
