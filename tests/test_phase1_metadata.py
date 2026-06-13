from dataclasses import FrozenInstanceError, is_dataclass

import pytest

from codegraph import factories as F
from codegraph.credibility import (
    ActiveConfig,
    Certainty,
    Coverage,
    Credibility,
    DepScopeLevel,
    DepStatus,
    DependencyScope,
    IndexBackend,
    IndexHealth,
    IndexScope,
    InvariantError,
    NegativeScope,
    QueryKind,
    Relation,
    Resolved,
    Source,
    SymbolKind,
    check_invariants,
)
from codegraph.engines.protocol import (
    EngineDiagnostics,
    EngineObservation,
    EngineObservationResult,
    SyntacticProvider,
)
from codegraph.types import (
    Candidate,
    LocationResult,
    Pos,
    QueryMeta,
    QueryResult,
    QueryStatus,
    Range,
    SymbolId,
)


DEP_OK = DependencyScope.complete()
NF_CURRENT_TU = Coverage(
    index_scope=IndexScope.CURRENT_TU,
    is_exhaustive_within_scope=True,
    negative_scope=NegativeScope.CURRENT_TU,
)


def mk(**kw) -> Credibility:
    base = dict(
        source=Source.CLANGD,
        certainty=Certainty.SEMANTIC,
        relation=Relation.NA,
        resolved=Resolved.RESOLVED,
        query_kind=QueryKind.ENTITY,
        dependency=DEP_OK,
        coverage=Coverage(),
        active_config=ActiveConfig.UNKNOWN,
        build_config_id="arm",
        symbol_kind=SymbolKind.ORDINARY_FUNCTION,
        index_health=IndexHealth.COMPLETE,
        index_backend=IndexBackend.BACKGROUND_INDEX,
    )
    base.update(kw)
    return Credibility(**base)


def assert_violates(code_substr: str, **kw) -> None:
    with pytest.raises(InvariantError) as ei:
        check_invariants(mk(**kw))
    assert code_substr in ei.value.code


def test_inv13_not_found_requires_exhaustive_negative_scope():
    assert_violates(
        "INV13",
        resolved=Resolved.NOT_FOUND,
        coverage=Coverage(
            index_scope=IndexScope.CURRENT_TU,
            is_exhaustive_within_scope=False,
            negative_scope=NegativeScope.CURRENT_TU,
        ),
    )
    assert_violates(
        "INV13",
        resolved=Resolved.NOT_FOUND,
        coverage=Coverage(
            index_scope=IndexScope.CURRENT_TU,
            is_exhaustive_within_scope=True,
            negative_scope=NegativeScope.NONE,
        ),
    )
    check_invariants(mk(resolved=Resolved.NOT_FOUND, coverage=NF_CURRENT_TU))


def test_inv14_indexed_project_negative_scope_is_clamped_by_health_and_backend():
    indexed_negative = Coverage(
        index_scope=IndexScope.INDEXED_PROJECT,
        is_exhaustive_within_scope=True,
        negative_scope=NegativeScope.INDEXED_PROJECT,
    )
    assert_violates(
        "INV14B",
        resolved=Resolved.NOT_FOUND,
        coverage=indexed_negative,
        index_health=IndexHealth.UNKNOWN,
        index_backend=IndexBackend.CLANGD_INDEXER,
    )
    assert_violates(
        "INV14C",
        resolved=Resolved.NOT_FOUND,
        coverage=indexed_negative,
        index_health=IndexHealth.COMPLETE,
        index_backend=IndexBackend.BACKGROUND_INDEX,
    )
    check_invariants(mk(
        resolved=Resolved.NOT_FOUND,
        coverage=indexed_negative,
        index_health=IndexHealth.COMPLETE,
        index_backend=IndexBackend.CLANGD_INDEXER,
    ))


def test_negative_scope_index_scope_matrix():
    assert_violates(
        "INV14_MATRIX",
        coverage=Coverage(
            index_scope=IndexScope.EXTERNAL_KNOWN,
            is_exhaustive_within_scope=False,
            negative_scope=NegativeScope.CURRENT_TU,
        ),
    )
    check_invariants(mk(
        resolved=Resolved.NOT_FOUND,
        coverage=Coverage(
            index_scope=IndexScope.INDEXED_PROJECT,
            is_exhaustive_within_scope=True,
            negative_scope=NegativeScope.CURRENT_TU,
        ),
    ))


def test_inv15_not_found_only_for_exhaustive_symbol_kinds():
    assert_violates(
        "INV15",
        resolved=Resolved.NOT_FOUND,
        coverage=NF_CURRENT_TU,
        symbol_kind=SymbolKind.MACRO,
    )
    for kind in (
            SymbolKind.ORDINARY_FUNCTION,
            SymbolKind.ORDINARY_VARIABLE,
            SymbolKind.TYPE):
        check_invariants(mk(
            resolved=Resolved.NOT_FOUND,
            coverage=NF_CURRENT_TU,
            symbol_kind=kind,
        ))


def test_inv16_treesitter_active_config_is_unknown():
    assert_violates(
        "INV16",
        source=Source.TREE_SITTER,
        certainty=Certainty.SYNTACTIC,
        dependency=DependencyScope.not_applicable(),
        active_config=ActiveConfig.HOST,
    )
    check_invariants(mk(
        source=Source.TREE_SITTER,
        certainty=Certainty.SYNTACTIC,
        dependency=DependencyScope.not_applicable(),
        active_config=ActiveConfig.UNKNOWN,
    ))


def test_inv18_dependency_missing_consistency_and_na_not_found_guard():
    assert_violates(
        "INV18",
        dependency=DependencyScope(
            level=DepScopeLevel.QUERY_LOCAL,
            status=DepStatus.INCOMPLETE,
            missing=(),
        ),
    )
    assert_violates(
        "INV18",
        dependency=DependencyScope(
            level=DepScopeLevel.QUERY_LOCAL,
            status=DepStatus.COMPLETE,
            missing=("missing.h",),
        ),
    )
    assert_violates(
        "INV18",
        resolved=Resolved.NOT_FOUND,
        coverage=NF_CURRENT_TU,
        dependency=DependencyScope.not_applicable(),
    )


def test_inv19_reserved_exact_syntactic_rules():
    assert_violates(
        "INV1",
        source=Source.TREE_SITTER,
        certainty=Certainty.EXACT_SYNTACTIC,
        dependency=DependencyScope.not_applicable(),
    )
    assert_violates(
        "INV19",
        source=Source.CLANGD,
        certainty=Certainty.EXACT_SYNTACTIC,
    )
    check_invariants(mk(
        source=Source.LOG_SEARCH,
        certainty=Certainty.EXACT_SYNTACTIC,
    ))


def test_inv2_now_rejects_semantic_from_reserved_log_search():
    assert_violates(
        "INV2",
        source=Source.LOG_SEARCH,
        certainty=Certainty.SEMANTIC,
    )


def test_factory_make_error_credibility_matches_contract():
    c = F.make_error_credibility(QueryKind.RELATION)
    assert c.source == Source.CLANGD
    assert c.certainty == Certainty.SYNTACTIC
    assert c.relation == Relation.NA
    assert c.resolved == Resolved.UNRESOLVED
    assert c.query_kind == QueryKind.RELATION
    assert c.symbol_kind == SymbolKind.UNKNOWN
    assert c.dependency.level == DepScopeLevel.NOT_APPLICABLE
    assert c.dependency.status == DepStatus.UNKNOWN
    assert c.coverage.index_scope == IndexScope.EXTERNAL_UNKNOWN
    assert c.coverage.negative_scope == NegativeScope.NONE


def test_query_meta_is_frozen_dataclass_with_optional_file_pos():
    assert is_dataclass(QueryMeta)
    q = QueryMeta(kind="entity", symbol="gst_element_set_state", build_config_id="arm")
    assert q.file is None
    assert q.pos is None
    with pytest.raises(FrozenInstanceError):
        q.symbol = "other"


def test_query_result_and_candidate_defaults():
    pos = Pos(line=1, character=2)
    symbol = SymbolId(usr=None, name="fn", file="/tmp/a.c", pos=pos)
    location = LocationResult(symbol_id=symbol, range=Range(pos, pos), kind="ordinary_function")
    candidate = Candidate(
        data=location,
        credibility=F.treesitter_entity_resolved(),
        relevance_score=15,
    )
    result = QueryResult(
        query=QueryMeta(kind="entity", symbol="fn", build_config_id="arm"),
        status=QueryStatus.UNRESOLVED,
        status_credibility=F.make_error_credibility(QueryKind.ENTITY),
        syntactic_candidates=[candidate],
    )
    assert candidate.consumer_warning == "not_evidence"
    assert result.semantic_results == []
    assert result.index_health == "unknown"


def test_engine_protocol_module_exports_phase1_shapes():
    assert EngineObservation is not None
    assert SyntacticProvider is not None
    observation = EngineObservationResult(diagnostics=EngineDiagnostics())
    assert observation.locations == ()
    assert observation.references == ()
    assert observation.call_edges == ()
