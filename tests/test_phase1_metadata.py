import ast
from pathlib import Path
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
    validate,
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

REPO_ROOT = Path(__file__).resolve().parents[1]
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
    check_invariants(
        mk(
            resolved=Resolved.NOT_FOUND,
            coverage=NF_CURRENT_TU,
            index_backend=IndexBackend.CLANGD_INDEXER,
        )
    )


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
    check_invariants(
        mk(
            resolved=Resolved.NOT_FOUND,
            coverage=indexed_negative,
            index_health=IndexHealth.COMPLETE,
            index_backend=IndexBackend.CLANGD_INDEXER,
        )
    )


def test_inv14d_background_index_forbids_not_found_but_indexer_allows():
    assert_violates(
        "INV14D",
        resolved=Resolved.NOT_FOUND,
        coverage=NF_CURRENT_TU,
        index_health=IndexHealth.COMPLETE,
        index_backend=IndexBackend.BACKGROUND_INDEX,
    )
    check_invariants(
        mk(
            resolved=Resolved.NOT_FOUND,
            coverage=NF_CURRENT_TU,
            index_health=IndexHealth.COMPLETE,
            index_backend=IndexBackend.CLANGD_INDEXER,
        )
    )


def test_negative_scope_index_scope_matrix():
    assert_violates(
        "INV14_MATRIX",
        resolved=Resolved.NOT_FOUND,
        coverage=Coverage(
            index_scope=IndexScope.EXTERNAL_KNOWN,
            is_exhaustive_within_scope=True,
            negative_scope=NegativeScope.CURRENT_TU,
        ),
        index_backend=IndexBackend.CLANGD_INDEXER,
    )
    check_invariants(
        mk(
            resolved=Resolved.NOT_FOUND,
            coverage=Coverage(
                index_scope=IndexScope.INDEXED_PROJECT,
                is_exhaustive_within_scope=True,
                negative_scope=NegativeScope.CURRENT_TU,
            ),
            index_backend=IndexBackend.CLANGD_INDEXER,
        )
    )


def test_inv15_not_found_only_for_exhaustive_symbol_kinds():
    assert_violates(
        "INV15",
        resolved=Resolved.NOT_FOUND,
        coverage=NF_CURRENT_TU,
        symbol_kind=SymbolKind.MACRO,
        index_backend=IndexBackend.CLANGD_INDEXER,
    )
    for kind in (
        SymbolKind.ORDINARY_FUNCTION,
        SymbolKind.ORDINARY_VARIABLE,
        SymbolKind.TYPE,
    ):
        check_invariants(
            mk(
                resolved=Resolved.NOT_FOUND,
                coverage=NF_CURRENT_TU,
                symbol_kind=kind,
                index_backend=IndexBackend.CLANGD_INDEXER,
            )
        )


def test_inv16_treesitter_active_config_is_unknown():
    assert_violates(
        "INV16",
        source=Source.TREE_SITTER,
        certainty=Certainty.SYNTACTIC,
        dependency=DependencyScope.not_applicable(),
        active_config=ActiveConfig.HOST,
    )
    check_invariants(
        mk(
            source=Source.TREE_SITTER,
            certainty=Certainty.SYNTACTIC,
            dependency=DependencyScope.not_applicable(),
            active_config=ActiveConfig.UNKNOWN,
        )
    )


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
        index_backend=IndexBackend.CLANGD_INDEXER,
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
    check_invariants(
        mk(
            source=Source.LOG_SEARCH,
            certainty=Certainty.EXACT_SYNTACTIC,
        )
    )


def test_inv2_now_rejects_semantic_from_reserved_log_search():
    assert_violates(
        "INV2",
        source=Source.LOG_SEARCH,
        certainty=Certainty.SEMANTIC,
    )


def test_inv20_not_found_requires_clangd_semantic_without_blind_spot():
    assert_violates(
        "INV12",
        source=Source.TREE_SITTER,
        certainty=Certainty.SYNTACTIC,
        resolved=Resolved.NOT_FOUND,
        dependency=DependencyScope.not_applicable(),
        coverage=NF_CURRENT_TU,
    )
    assert_violates(
        "INV5",
        resolved=Resolved.NOT_FOUND,
        coverage=NF_CURRENT_TU,
        blind_spot_affects_result=True,
        index_backend=IndexBackend.CLANGD_INDEXER,
    )
    assert_violates(
        "INV20",
        source=Source.LOG_SEARCH,
        certainty=Certainty.SYNTACTIC,
        resolved=Resolved.NOT_FOUND,
        coverage=NF_CURRENT_TU,
        index_backend=IndexBackend.CLANGD_INDEXER,
    )
    assert_violates(
        "INV20",
        certainty=Certainty.SYNTACTIC,
        resolved=Resolved.NOT_FOUND,
        coverage=NF_CURRENT_TU,
        index_backend=IndexBackend.CLANGD_INDEXER,
    )
    check_invariants(F.clangd_not_found(QueryKind.ENTITY, DEP_OK))


def test_inv21_negative_scope_only_for_not_found_and_unresolved_not_exhaustive():
    assert_violates(
        "INV21",
        coverage=Coverage(
            index_scope=IndexScope.CURRENT_TU,
            is_exhaustive_within_scope=False,
            negative_scope=NegativeScope.CURRENT_TU,
        ),
    )
    assert_violates(
        "INV21",
        resolved=Resolved.UNRESOLVED,
        coverage=Coverage(
            index_scope=IndexScope.CURRENT_TU,
            is_exhaustive_within_scope=True,
            negative_scope=NegativeScope.NONE,
        ),
    )
    check_invariants(
        mk(
            resolved=Resolved.RESOLVED,
            coverage=Coverage(
                index_scope=IndexScope.INDEXED_PROJECT,
                is_exhaustive_within_scope=True,
                negative_scope=NegativeScope.NONE,
            ),
        )
    )
    check_invariants(mk(coverage=Coverage()))


def test_log_search_syntactic_reserved_source_is_legal():
    check_invariants(
        mk(
            source=Source.LOG_SEARCH,
            certainty=Certainty.SYNTACTIC,
        )
    )


def test_consumer_hint_is_opaque_to_hash_and_equality():
    hint = {"runtime_confirmed": True}
    c = mk(consumer_hint=hint)
    same_core = mk(consumer_hint={"runtime_confirmed": False})

    before = hash(c)
    hint["runtime_confirmed"] = False

    assert c == same_core
    assert hash(c) == before
    assert hash(c) == hash(same_core)


def test_validate_returns_original_object():
    c = mk()
    assert validate(c) is c


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


def test_public_string_fields_match_frozen_enum_values():
    pos = Pos(line=0, character=0)
    symbol = SymbolId(usr=None, name="fn", file="/tmp/a.c", pos=pos)
    location = LocationResult(
        symbol_id=symbol,
        range=Range(pos, pos),
        kind=SymbolKind.ORDINARY_FUNCTION.value,
    )
    result = QueryResult(
        query=QueryMeta(
            kind=QueryKind.ENTITY.value,
            symbol="fn",
            build_config_id="arm",
        ),
        status=QueryStatus.UNRESOLVED,
        status_credibility=F.make_error_credibility(QueryKind.ENTITY),
        index_health=IndexHealth.UNKNOWN.value,
    )

    assert location.kind == "ordinary_function"
    assert result.query.kind == "entity"
    assert result.index_health == "unknown"


def test_query_result_and_candidate_defaults():
    pos = Pos(line=1, character=2)
    symbol = SymbolId(usr=None, name="fn", file="/tmp/a.c", pos=pos)
    location = LocationResult(
        symbol_id=symbol, range=Range(pos, pos), kind="ordinary_function"
    )
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


def test_engine_protocol_shape_accepts_minimal_stubs():
    class FakeEngine:
        def search_symbol(
            self,
            symbol: str,
            *,
            kind_filter: str | None = None,
            limit: int = 100,
            offset: int = 0,
            request_timeout: float | None = None,
        ) -> EngineObservationResult:
            return EngineObservationResult()

        def get_definition(
            self,
            symbol: str,
            file: str,
            pos: Pos,
        ) -> EngineObservationResult:
            return EngineObservationResult()

        def find_references(
            self,
            symbol: str,
            file: str,
            pos: Pos,
            *,
            limit: int = 100,
            offset: int = 0,
        ) -> EngineObservationResult:
            return EngineObservationResult()

        def find_callers(
            self,
            symbol: str,
            file: str,
            pos: Pos,
            *,
            limit: int = 100,
            offset: int = 0,
        ) -> EngineObservationResult:
            return EngineObservationResult()

        def find_callees(
            self,
            symbol: str,
            file: str,
            pos: Pos,
            *,
            limit: int = 100,
            offset: int = 0,
        ) -> EngineObservationResult:
            return EngineObservationResult()

    class FakeSyntacticProvider:
        def search_candidates(
            self,
            symbol: str,
            *,
            kind_filter: str | None = None,
            limit: int = 100,
            offset: int = 0,
        ) -> tuple[Candidate, ...]:
            return ()

        def candidates_near(
            self,
            symbol: str,
            file: str,
            pos: Pos,
            *,
            limit: int = 100,
        ) -> tuple[Candidate, ...]:
            return ()

        def is_preprocessor_location(self, file: str, pos: Pos) -> bool:
            return False

    engine: EngineObservation = FakeEngine()
    syntactic: SyntacticProvider = FakeSyntacticProvider()
    pos = Pos(line=0, character=0)

    assert engine.get_definition("fn", "/tmp/a.c", pos).locations == ()
    assert syntactic.search_candidates("fn") == ()
    assert not syntactic.is_preprocessor_location("/tmp/a.c", pos)


def _contains_pep604_union(node: ast.AST) -> bool:
    return any(
        isinstance(child, ast.BinOp) and isinstance(child.op, ast.BitOr)
        for child in ast.walk(node)
    )


def _has_future_annotations(tree: ast.Module) -> bool:
    return any(
        isinstance(node, ast.ImportFrom)
        and node.module == "__future__"
        and any(alias.name == "annotations" for alias in node.names)
        for node in tree.body
    )


def _uses_pep604_annotation_syntax(tree: ast.Module) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and node.annotation is not None:
            if _contains_pep604_union(node.annotation):
                return True
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            annotations = [arg.annotation for arg in node.args.args]
            annotations.extend(arg.annotation for arg in node.args.kwonlyargs)
            annotations.extend(
                arg.annotation
                for arg in (
                    node.args.posonlyargs if hasattr(node.args, "posonlyargs") else []
                )
            )
            annotations.extend(
                [node.args.vararg.annotation if node.args.vararg else None]
            )
            annotations.extend(
                [node.args.kwarg.annotation if node.args.kwarg else None]
            )
            annotations.extend([node.returns])
            if any(
                annotation is not None and _contains_pep604_union(annotation)
                for annotation in annotations
            ):
                return True
    return False


def test_pep604_union_syntax_requires_future_annotations():
    checked_roots = (REPO_ROOT / "codegraph", REPO_ROOT / "tools")
    offenders: list[str] = []
    for root in checked_roots:
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            if _uses_pep604_annotation_syntax(tree) and not _has_future_annotations(
                tree
            ):
                offenders.append(str(path.relative_to(REPO_ROOT)))
    assert offenders == []
