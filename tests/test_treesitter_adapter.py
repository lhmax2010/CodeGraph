from __future__ import annotations

from pathlib import Path

from codegraph.credibility import (
    ActiveConfig,
    Certainty,
    IndexHealth,
    QueryKind,
    Relation,
    Source,
    SymbolKind,
)
from codegraph.engines import treesitter_adapter
from codegraph.engines.protocol import EngineObservationResult
from codegraph.engines.treesitter_adapter import (
    TreeSitterProvider,
    create_treesitter_provider,
)
from codegraph.routing import route_observation
from codegraph.types import (
    IssueCode,
    LocationResult,
    Pos,
    QueryMeta,
    QueryStatus,
    Range,
    SymbolId,
)

SOURCE = """\
#define MAKE_FN(name) int name(void) { return 1; }
#define LIMIT 7
struct Thing { int field; };
typedef struct Thing ThingAlias;
static int helper(int value) { return value + LIMIT; }
int global_value = LIMIT;
int caller(void) { return helper(global_value); }
"""


def write_source(tmp_path: Path) -> Path:
    source = tmp_path / "sample.c"
    source.write_text(SOURCE, encoding="utf-8")
    return source


def query(file: Path) -> QueryMeta:
    return QueryMeta(
        QueryKind.ENTITY.value, "MAKE_FN", "arm", file=str(file), pos=Pos(0, 8)
    )


def macro_location(file: Path, pos: Pos) -> LocationResult:
    return LocationResult(
        SymbolId(None, "MAKE_FN", str(file), pos),
        Range(pos, Pos(pos.line, pos.character + 7)),
        SymbolKind.MACRO.value,
    )


def codes(result):
    return {note.code for note in result.notes}


def test_factory_degrades_to_none_when_bindings_are_unavailable(monkeypatch):
    monkeypatch.setattr(treesitter_adapter, "_IMPORT_ERROR", ImportError("missing"))
    assert create_treesitter_provider(("/tmp",)) is None

    result = route_observation(
        QueryMeta(QueryKind.ENTITY.value, "missing", "arm"),
        EngineObservationResult(),
        syntactic_provider=create_treesitter_provider(("/tmp",)),
        allow_syntactic_fallback=True,
        index_health=IndexHealth.UNKNOWN,
    )
    assert result.status == QueryStatus.UNRESOLVED
    assert IssueCode.TREE_SITTER_UNAVAILABLE in codes(result)


def test_search_candidates_use_real_treesitter_and_score_without_filtering(
    tmp_path: Path,
):
    source = write_source(tmp_path)
    provider = TreeSitterProvider((tmp_path,))

    helper = provider.search_candidates(
        "helper", kind_filter=SymbolKind.ORDINARY_FUNCTION.value
    )
    assert len(helper) == 1
    assert helper[0].relevance_score == 20
    assert helper[0].consumer_warning == "not_evidence"
    assert helper[0].credibility.source == Source.TREE_SITTER
    assert helper[0].credibility.certainty == Certainty.SYNTACTIC
    assert helper[0].credibility.active_config == ActiveConfig.UNKNOWN
    assert helper[0].credibility.symbol_kind == SymbolKind.ORDINARY_FUNCTION

    low_score = provider.search_candidates("helper", kind_filter=SymbolKind.TYPE.value)
    assert low_score[0].relevance_score == 15

    macro = provider.search_candidates("LIMIT", kind_filter=SymbolKind.MACRO.value)
    assert macro[0].data.symbol_id.file == str(source)
    assert macro[0].credibility.symbol_kind == SymbolKind.MACRO


def test_candidates_near_score_name_file_and_inferred_type(tmp_path: Path):
    source = write_source(tmp_path)
    provider = TreeSitterProvider((tmp_path,))

    candidates = provider.candidates_near("helper", str(source), Pos(6, 26))

    assert len(candidates) == 1
    assert candidates[0].relevance_score == 30
    assert candidates[0].data.symbol_id.name == "helper"


def test_preprocessor_helper_uses_position_not_symbol_kind(tmp_path: Path):
    source = write_source(tmp_path)
    provider = TreeSitterProvider((tmp_path,))

    define_name = Pos(0, 8)
    macro_body = Pos(0, 27)

    assert provider.is_preprocessor_location(str(source), define_name) is False
    assert provider.is_preprocessor_location(str(source), macro_body) is True

    definition_ok = route_observation(
        query(source),
        EngineObservationResult(locations=(macro_location(source, define_name),)),
        syntactic_provider=provider,
    )
    assert definition_ok.status == QueryStatus.OK
    assert definition_ok.semantic_results[0].credibility.symbol_kind == SymbolKind.MACRO

    expansion_blind_spot = route_observation(
        query(source),
        EngineObservationResult(locations=(macro_location(source, macro_body),)),
        syntactic_provider=provider,
    )
    assert expansion_blind_spot.status == QueryStatus.UNRESOLVED
    assert expansion_blind_spot.semantic_results == []
    assert (
        expansion_blind_spot.syntactic_candidates[
            0
        ].credibility.blind_spot_affects_result
        is True
    )
    assert (
        expansion_blind_spot.syntactic_candidates[0].credibility.relation == Relation.NA
    )


def test_no_helper_still_conservatively_downgrades_macro_definition(tmp_path: Path):
    source = write_source(tmp_path)

    result = route_observation(
        query(source),
        EngineObservationResult(locations=(macro_location(source, Pos(0, 8)),)),
        syntactic_provider=None,
    )

    assert result.status == QueryStatus.UNRESOLVED
    assert result.semantic_results == []
    assert result.syntactic_candidates[0].credibility.blind_spot_affects_result is True


def test_unparsable_file_is_conservative_blind_spot(tmp_path: Path):
    missing = tmp_path / "deleted.c"
    provider = TreeSitterProvider((tmp_path,))
    pos = Pos(0, 0)

    assert provider.is_preprocessor_location(str(missing), pos) is True

    result = route_observation(
        query(missing),
        EngineObservationResult(locations=(macro_location(missing, pos),)),
        syntactic_provider=provider,
    )

    assert result.status == QueryStatus.UNRESOLVED
    assert result.semantic_results == []
    assert result.syntactic_candidates[0].credibility.blind_spot_affects_result is True
