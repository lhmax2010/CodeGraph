from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

import pytest

from codegraph.api import (
    BuildConfig,
    CodeGraph,
    _ensure_background_index_call_hierarchy_is_non_exhaustive,
    _ensure_background_index_references_are_non_exhaustive,
    _index_ready_probe_matches,
    _prewarm_index_ready_timeout,
    _reference_warmup_file,
    _warm_background_index,
    clear_build_configs,
    find_callees as api_find_callees,
    find_callers as api_find_callers,
    find_references as api_find_references,
    get_definition as api_get_definition,
    prewarm_build_config,
    register_build_config,
    search_symbol as api_search_symbol,
)
from codegraph.credibility import (
    Certainty,
    Coverage,
    Credibility,
    DependencyScope,
    IndexBackend,
    IndexScope,
    QueryKind,
    Relation,
    Resolved,
    Source,
)
from codegraph.engines.protocol import EngineObservationResult
from codegraph.indexing import (
    BackgroundIndexConfig,
    run_background_index,
    write_index_engine_version,
)
from codegraph.types import (
    Candidate,
    CallEdgeResult,
    IssueCode,
    LocationResult,
    Pos,
    QueryMeta,
    QueryResult,
    QueryStatus,
    Range,
    ReferenceResult,
    SymbolId,
)


def write_project(tmp_path: Path) -> tuple[Path, Path]:
    header = tmp_path / "lib.h"
    lib = tmp_path / "lib.c"
    main = tmp_path / "main.c"
    header.write_text("int add(int x);\n", encoding="utf-8")
    lib.write_text(
        '#include "lib.h"\nint add(int x) { return x + 1; }\n',
        encoding="utf-8",
    )
    main.write_text(
        '#include "lib.h"\nint main(void) { return add(1); }\n',
        encoding="utf-8",
    )
    (tmp_path / "compile_commands.json").write_text(
        json.dumps(
            [
                {
                    "directory": str(tmp_path),
                    "command": f"/usr/bin/cc -I{tmp_path} -c {lib}",
                    "file": str(lib),
                },
                {
                    "directory": str(tmp_path),
                    "command": f"/usr/bin/cc -I{tmp_path} -c {main}",
                    "file": str(main),
                },
            ]
        ),
        encoding="utf-8",
    )
    return lib, main


def touch_complete_index(tmp_path: Path) -> None:
    index_dir = tmp_path / ".cache" / "clangd" / "index"
    index_dir.mkdir(parents=True)
    (index_dir / "lib.idx").write_text("idx", encoding="utf-8")
    (index_dir / "main.idx").write_text("idx", encoding="utf-8")
    write_index_engine_version(index_dir, "clangd 18.1.3")


def touch_unstamped_complete_index(tmp_path: Path) -> None:
    index_dir = tmp_path / ".cache" / "clangd" / "index"
    index_dir.mkdir(parents=True)
    (index_dir / "lib.idx").write_text("idx", encoding="utf-8")
    (index_dir / "main.idx").write_text("idx", encoding="utf-8")


def fake_engine_version_probe(_clangd_path: str) -> str:
    return "clangd 18.1.3"


def loc(name: str, file: Path, line: int = 1) -> LocationResult:
    pos = Pos(line, 4)
    return LocationResult(
        SymbolId(None, name, str(file), pos),
        Range(pos, Pos(line, 7)),
        "ordinary_function",
    )


def ref(file: Path, line: int = 1) -> ReferenceResult:
    pos = Pos(line, 9)
    return ReferenceResult(Range(pos, Pos(line, 12)), str(file), "reference")


def call_edge(
    caller_file: Path,
    callee_file: Path,
    *,
    caller_name: str = "caller",
    callee_name: str = "add",
    line: int = 1,
) -> CallEdgeResult:
    call_pos = Pos(line, 9)
    return CallEdgeResult(
        SymbolId(None, caller_name, str(caller_file), Pos(line, 4)),
        SymbolId(None, callee_name, str(callee_file), Pos(line, 0)),
        Range(call_pos, Pos(line, 12)),
    )


def exhaustive_background_index_credibility() -> Credibility:
    return Credibility(
        source=Source.CLANGD,
        certainty=Certainty.SEMANTIC,
        relation=Relation.NA,
        resolved=Resolved.RESOLVED,
        query_kind=QueryKind.ENTITY,
        dependency=DependencyScope.complete(),
        coverage=Coverage(
            index_scope=IndexScope.INDEXED_PROJECT,
            is_exhaustive_within_scope=True,
        ),
        index_backend=IndexBackend.BACKGROUND_INDEX,
        build_config_id="test",
    )


@pytest.mark.skipif(shutil.which("clangd") is None, reason="clangd unavailable")
def test_search_symbol_and_get_definition_e2e_with_background_index(tmp_path: Path):
    lib, main = write_project(tmp_path)
    build = run_background_index(
        BackgroundIndexConfig(
            compile_commands_dir=str(tmp_path),
            jobs=2,
            max_wait_seconds=10,
            poll_interval_seconds=0.1,
            stable_rounds=2,
        )
    )
    assert build.health_report.health.value == "complete"
    client = CodeGraph(
        BuildConfig(
            "test",
            str(tmp_path),
            source_roots=(str(tmp_path),),
            background_index=True,
            diagnostics_wait=0,
            index_ready_timeout=5,
            index_ready_poll_interval=0.1,
            index_ready_probe_symbol="add",
            index_ready_probe_path_suffix="lib.c",
            warmup_file=str(main),
        )
    )
    call_line = main.read_text(encoding="utf-8").splitlines()[1]

    definition = client.get_definition("add", str(main), Pos(1, call_line.index("add")))
    search = client.search_symbol("add")
    references = client.find_references(
        "add", str(main), Pos(1, call_line.index("add")), limit=10
    )

    assert definition.status == QueryStatus.OK
    assert definition.index_health == "complete"
    assert definition.engine_version is None
    assert [r.data.symbol_id.file for r in definition.semantic_results] == [str(lib)]
    assert search.status == QueryStatus.OK
    assert search.index_health == "complete"
    assert search.engine_version is None
    assert [r.data.symbol_id.name for r in search.semantic_results] == ["add"]
    assert [r.data.symbol_id.file for r in search.semantic_results] == [str(lib)]
    assert references.status == QueryStatus.OK
    assert references.index_health == "complete"
    assert references.engine_version is None
    assert references.total_hits is not None
    assert references.total_hits >= 2
    assert all(
        not item.credibility.coverage.is_exhaustive_within_scope
        for item in references.semantic_results
    )


class NeverReadyEngine:
    engine_version = "clangd 18.1.3"

    def __enter__(self) -> "NeverReadyEngine":
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def warm_file(self, file: str) -> None:
        self.warmed_file = file

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


class ReadyEngine(NeverReadyEngine):
    def __init__(self, locations: tuple[LocationResult, ...]):
        self.locations = locations

    def search_symbol(
        self,
        symbol: str,
        *,
        kind_filter: str | None = None,
        limit: int = 100,
        offset: int = 0,
        request_timeout: float | None = None,
    ) -> EngineObservationResult:
        return EngineObservationResult(
            locations=self.locations[offset : offset + limit]
        )

    def get_definition(
        self,
        symbol: str,
        file: str,
        pos: Pos,
    ) -> EngineObservationResult:
        return EngineObservationResult(locations=self.locations[:1])


class FailingEngine(NeverReadyEngine):
    def search_symbol(
        self,
        symbol: str,
        *,
        kind_filter: str | None = None,
        limit: int = 100,
        offset: int = 0,
        request_timeout: float | None = None,
    ) -> EngineObservationResult:
        raise TimeoutError("boom")


class DefinitionFailingEngine(NeverReadyEngine):
    def get_definition(
        self,
        symbol: str,
        file: str,
        pos: Pos,
    ) -> EngineObservationResult:
        raise TimeoutError("definition boom")


class ReferencesFailingEngine(NeverReadyEngine):
    def find_references(
        self,
        symbol: str,
        file: str,
        pos: Pos,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> EngineObservationResult:
        raise TimeoutError("references boom")


class ReadyNoDefinitionEngine(NeverReadyEngine):
    def __init__(self, probe_location: LocationResult):
        self.probe_location = probe_location

    def search_symbol(
        self,
        symbol: str,
        *,
        kind_filter: str | None = None,
        limit: int = 100,
        offset: int = 0,
        request_timeout: float | None = None,
    ) -> EngineObservationResult:
        if symbol == "sentinel":
            return EngineObservationResult(locations=(self.probe_location,))
        return EngineObservationResult()


class ReadyReferencesEngine(NeverReadyEngine):
    def __init__(
        self,
        probe_location: LocationResult,
        references: tuple[ReferenceResult, ...],
    ):
        self.probe_location = probe_location
        self.references = references
        self.find_references_calls = 0

    def search_symbol(
        self,
        symbol: str,
        *,
        kind_filter: str | None = None,
        limit: int = 100,
        offset: int = 0,
        request_timeout: float | None = None,
    ) -> EngineObservationResult:
        if symbol == "sentinel":
            return EngineObservationResult(locations=(self.probe_location,))
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
        self.find_references_calls += 1
        return EngineObservationResult(
            references=self.references[offset : offset + limit],
            total_results=len(self.references),
        )


class ProgressiveReferencesEngine(NeverReadyEngine):
    def __init__(self, observations: tuple[tuple[ReferenceResult, ...], ...]):
        self.observations = observations
        self.find_references_calls = 0

    def find_references(
        self,
        symbol: str,
        file: str,
        pos: Pos,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> EngineObservationResult:
        index = min(self.find_references_calls, len(self.observations) - 1)
        self.find_references_calls += 1
        references = self.observations[index]
        return EngineObservationResult(
            references=references[offset : offset + limit],
            total_results=len(references),
        )


class ReadyCallEdgesEngine(NeverReadyEngine):
    def __init__(
        self,
        *,
        callers: tuple[CallEdgeResult, ...] = (),
        callees: tuple[CallEdgeResult, ...] = (),
    ):
        self.callers = callers
        self.callees = callees
        self.find_callers_calls = 0
        self.find_callees_calls = 0

    def find_callers(
        self,
        symbol: str,
        file: str,
        pos: Pos,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> EngineObservationResult:
        self.find_callers_calls += 1
        return EngineObservationResult(
            call_edges=self.callers[offset : offset + limit],
            total_results=len(self.callers),
        )

    def find_callees(
        self,
        symbol: str,
        file: str,
        pos: Pos,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> EngineObservationResult:
        self.find_callees_calls += 1
        return EngineObservationResult(
            call_edges=self.callees[offset : offset + limit],
            total_results=len(self.callees),
        )


class ProgressiveCallEdgesEngine(NeverReadyEngine):
    def __init__(self, observations: tuple[tuple[CallEdgeResult, ...], ...]):
        self.observations = observations
        self.find_callers_calls = 0

    def find_callers(
        self,
        symbol: str,
        file: str,
        pos: Pos,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> EngineObservationResult:
        index = min(self.find_callers_calls, len(self.observations) - 1)
        self.find_callers_calls += 1
        call_edges = self.observations[index]
        return EngineObservationResult(
            call_edges=call_edges[offset : offset + limit],
            total_results=len(call_edges),
        )


class UnsupportedCalleesEngine(NeverReadyEngine):
    def find_callees(
        self,
        symbol: str,
        file: str,
        pos: Pos,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> EngineObservationResult:
        raise NotImplementedError("clangd callHierarchy outgoingCalls unsupported")


class TruncatedSearchEngine(NeverReadyEngine):
    def __init__(
        self,
        probe_location: LocationResult,
        fuzzy_locations: tuple[LocationResult, ...],
        exact_location: LocationResult,
    ):
        self.probe_location = probe_location
        self.fuzzy_locations = fuzzy_locations
        self.exact_location = exact_location
        self.search_limits: list[int] = []

    def search_symbol(
        self,
        symbol: str,
        *,
        kind_filter: str | None = None,
        limit: int = 100,
        offset: int = 0,
        request_timeout: float | None = None,
    ) -> EngineObservationResult:
        if symbol == "sentinel":
            return EngineObservationResult(locations=(self.probe_location,))
        self.search_limits.append(limit)
        locations = (*self.fuzzy_locations, self.exact_location)
        return EngineObservationResult(locations=locations[offset : offset + limit])


def test_search_symbol_filters_exact_name_and_supports_background_index_off(
    tmp_path: Path,
):
    lib, _main = write_project(tmp_path)
    touch_complete_index(tmp_path)
    client = CodeGraph(
        BuildConfig("test", str(tmp_path), background_index=False),
        engine_version_probe=fake_engine_version_probe,
        engine_factory=lambda _cfg: ReadyEngine(
            (loc("add", lib), loc("address_like_noise", lib))
        ),
    )

    result = client.search_symbol("add")

    assert result.status == QueryStatus.OK
    assert result.index_health == "unknown"
    assert [r.data.symbol_id.name for r in result.semantic_results] == ["add"]


def test_search_symbol_offset_keeps_exact_total_hits(tmp_path: Path):
    lib, main = write_project(tmp_path)
    client = CodeGraph(
        BuildConfig("test", str(tmp_path), background_index=False),
        engine_version_probe=fake_engine_version_probe,
        engine_factory=lambda _cfg: ReadyEngine(
            (
                loc("needle", lib),
                loc("other", lib),
                loc("needle", main),
                loc("needle", lib, line=0),
            )
        ),
    )

    result = client.search_symbol("needle", limit=1, offset=1)

    assert result.status == QueryStatus.OK
    assert result.total_hits == 3
    assert [item.data.symbol_id.file for item in result.semantic_results] == [str(main)]


def test_search_symbol_empty_page_with_matches_is_not_not_found(tmp_path: Path):
    lib, main = write_project(tmp_path)
    touch_complete_index(tmp_path)
    client = CodeGraph(
        BuildConfig(
            "test",
            str(tmp_path),
            background_index=True,
            index_ready_probe_symbol="sentinel",
            index_ready_probe_path_suffix="lib.c",
        ),
        engine_version_probe=fake_engine_version_probe,
        engine_factory=lambda _cfg: ReadyEngine(
            (
                loc("sentinel", lib),
                loc("needle", lib),
                loc("needle", main),
            )
        ),
    )

    result = client.search_symbol("needle", limit=1, offset=3)

    assert result.status == QueryStatus.UNRESOLVED
    assert result.total_hits == 2
    assert result.index_health == "unknown"


def test_search_symbol_truncated_fuzzy_window_cannot_assert_not_found(
    tmp_path: Path,
):
    lib, _main = write_project(tmp_path)
    touch_complete_index(tmp_path)
    fuzzy = tuple(loc(f"other_{idx}", lib) for idx in range(100))
    engine = TruncatedSearchEngine(loc("sentinel", lib), fuzzy, loc("needle", lib))
    client = CodeGraph(
        BuildConfig(
            "test",
            str(tmp_path),
            background_index=True,
            index_ready_probe_symbol="sentinel",
            index_ready_probe_path_suffix="lib.c",
        ),
        engine_version_probe=fake_engine_version_probe,
        engine_factory=lambda _cfg: engine,
    )

    result = client.search_symbol("needle", limit=1)

    assert result.status == QueryStatus.UNRESOLVED
    assert result.index_health == "unknown"
    assert result.total_hits == 0
    assert engine.search_limits == [100]


def test_search_symbol_without_kind_filter_cannot_assert_not_found(tmp_path: Path):
    lib, _main = write_project(tmp_path)
    touch_complete_index(tmp_path)
    client = CodeGraph(
        BuildConfig(
            "test",
            str(tmp_path),
            background_index=True,
            index_ready_probe_symbol="sentinel",
            index_ready_probe_path_suffix="lib.c",
        ),
        engine_version_probe=fake_engine_version_probe,
        engine_factory=lambda _cfg: ReadyNoDefinitionEngine(loc("sentinel", lib)),
    )

    result = client.search_symbol("missing")

    assert result.status == QueryStatus.UNRESOLVED
    assert result.index_health == "unknown"
    assert result.status_credibility.symbol_kind.value == "unknown"


def test_search_symbol_function_filter_keeps_kind_but_cannot_assert_not_found(
    tmp_path: Path,
):
    lib, _main = write_project(tmp_path)
    touch_complete_index(tmp_path)
    client = CodeGraph(
        BuildConfig(
            "test",
            str(tmp_path),
            background_index=True,
            index_ready_probe_symbol="sentinel",
            index_ready_probe_path_suffix="lib.c",
        ),
        engine_version_probe=fake_engine_version_probe,
        engine_factory=lambda _cfg: ReadyNoDefinitionEngine(loc("sentinel", lib)),
    )

    result = client.search_symbol("missing", kind_filter="function")

    assert result.status == QueryStatus.UNRESOLVED
    assert result.index_health == "unknown"
    assert result.status_credibility.symbol_kind.value == "ordinary_function"


def test_background_index_off_cannot_use_complete_health_for_not_found(tmp_path: Path):
    _lib, main = write_project(tmp_path)
    touch_complete_index(tmp_path)
    line = main.read_text(encoding="utf-8").splitlines()[1]
    client = CodeGraph(
        BuildConfig("test", str(tmp_path), background_index=False),
        engine_version_probe=fake_engine_version_probe,
        engine_factory=lambda _cfg: NeverReadyEngine(),
    )

    result = client.get_definition("missing", str(main), Pos(1, line.index("add")))

    assert result.status == QueryStatus.UNRESOLVED
    assert result.index_health == "unknown"


def test_get_definition_without_kind_filter_cannot_assert_not_found(tmp_path: Path):
    lib, main = write_project(tmp_path)
    touch_complete_index(tmp_path)
    line = main.read_text(encoding="utf-8").splitlines()[1]
    client = CodeGraph(
        BuildConfig(
            "test",
            str(tmp_path),
            background_index=True,
            index_ready_probe_symbol="sentinel",
            index_ready_probe_path_suffix="lib.c",
        ),
        engine_version_probe=fake_engine_version_probe,
        engine_factory=lambda _cfg: ReadyNoDefinitionEngine(loc("sentinel", lib)),
    )

    result = client.get_definition("missing", str(main), Pos(1, line.index("add")))

    assert result.status == QueryStatus.UNRESOLVED
    assert result.index_health == "unknown"
    assert result.total_hits == 0
    assert result.status_credibility.symbol_kind.value == "unknown"


def test_find_references_returns_positive_non_exhaustive_background_index_results(
    tmp_path: Path,
):
    lib, main = write_project(tmp_path)
    touch_complete_index(tmp_path)
    references = (ref(lib), ref(main), ref(lib, line=0))
    engine = ReadyReferencesEngine(loc("sentinel", lib), references)
    line = main.read_text(encoding="utf-8").splitlines()[1]
    client = CodeGraph(
        BuildConfig(
            "test",
            str(tmp_path),
            source_roots=(str(tmp_path),),
            background_index=True,
            index_ready_probe_symbol="sentinel",
            index_ready_probe_path_suffix="lib.c",
            index_ready_poll_interval=0,
            warmup_file=str(main),
        ),
        engine_version_probe=fake_engine_version_probe,
        engine_factory=lambda _cfg: engine,
    )

    result = client.find_references(
        "add", str(main), Pos(1, line.index("add")), limit=3
    )

    assert result.status == QueryStatus.OK
    assert result.index_health == "complete"
    assert result.total_hits == 3
    assert len(result.semantic_results) == 2
    assert len(result.syntactic_candidates) == 1
    credibility = result.semantic_results[0].credibility
    assert credibility.coverage.index_scope.value == "indexed_project"
    assert credibility.coverage.is_exhaustive_within_scope is False
    assert credibility.coverage.negative_scope.value == "none"
    assert result.status_credibility.coverage.is_exhaustive_within_scope is False
    assert all(
        candidate.credibility.coverage.index_scope is IndexScope.INDEXED_PROJECT
        for candidate in result.syntactic_candidates
    )
    assert all(
        not candidate.credibility.coverage.is_exhaustive_within_scope
        for candidate in result.syntactic_candidates
    )
    assert {item.data.file for item in result.semantic_results} == {str(lib), str(main)}
    assert engine.warmed_file == str(main)


def test_find_references_default_warmup_avoids_query_and_probe_target(
    tmp_path: Path,
):
    lib, main = write_project(tmp_path)
    touch_complete_index(tmp_path)
    references = (ref(lib), ref(main))
    engine = ReadyReferencesEngine(loc("sentinel", lib), references)
    line = lib.read_text(encoding="utf-8").splitlines()[1]
    client = CodeGraph(
        BuildConfig(
            "test",
            str(tmp_path),
            source_roots=(str(tmp_path),),
            background_index=True,
            index_ready_probe_symbol="sentinel",
            index_ready_probe_path_suffix="lib.c",
            index_ready_poll_interval=0,
        ),
        engine_version_probe=fake_engine_version_probe,
        engine_factory=lambda _cfg: engine,
    )

    result = client.find_references("add", str(lib), Pos(1, line.index("add")))

    assert result.status == QueryStatus.OK
    assert result.index_health == "complete"
    assert result.total_hits == 2
    assert result.status_credibility.coverage.index_scope is IndexScope.INDEXED_PROJECT
    assert all(
        item.credibility.coverage.index_scope is IndexScope.INDEXED_PROJECT
        for item in result.semantic_results
    )
    assert engine.warmed_file == str(main)


def test_find_references_waits_for_query_references_to_stabilize(
    tmp_path: Path,
):
    lib, main = write_project(tmp_path)
    touch_complete_index(tmp_path)
    project_references = (ref(main), ref(lib), ref(lib, line=0))
    engine = ProgressiveReferencesEngine(
        (
            (ref(main),),
            project_references,
            project_references,
        )
    )
    line = main.read_text(encoding="utf-8").splitlines()[1]
    client = CodeGraph(
        BuildConfig(
            "test",
            str(tmp_path),
            source_roots=(str(tmp_path),),
            background_index=True,
            index_ready_timeout=1,
            index_ready_poll_interval=0,
            index_ready_probe_symbol="sentinel",
            index_ready_probe_path_suffix="lib.c",
            warmup_file=str(main),
        ),
        engine_version_probe=fake_engine_version_probe,
        engine_factory=lambda _cfg: engine,
    )

    result = client.find_references(
        "add", str(main), Pos(1, line.index("add")), limit=3
    )

    assert result.status == QueryStatus.OK
    assert result.index_health == "complete"
    assert result.total_hits == 3
    assert {
        item.credibility.coverage.index_scope for item in result.semantic_results
    } == {IndexScope.INDEXED_PROJECT}
    assert engine.find_references_calls == 5


def test_find_references_does_not_treat_short_reference_plateau_as_ready(
    tmp_path: Path,
):
    lib, main = write_project(tmp_path)
    touch_complete_index(tmp_path)
    local = (ref(main),)
    partial = (ref(main), ref(lib))
    project_references = (ref(main), ref(lib), ref(lib, line=0))
    engine = ProgressiveReferencesEngine(
        (
            local,
            partial,
            partial,
            partial,
            project_references,
            project_references,
            project_references,
            project_references,
        )
    )
    line = main.read_text(encoding="utf-8").splitlines()[1]
    client = CodeGraph(
        BuildConfig(
            "test",
            str(tmp_path),
            source_roots=(str(tmp_path),),
            background_index=True,
            index_ready_timeout=1,
            index_ready_poll_interval=0,
            index_ready_probe_symbol="sentinel",
            index_ready_probe_path_suffix="lib.c",
            warmup_file=str(main),
        ),
        engine_version_probe=fake_engine_version_probe,
        engine_factory=lambda _cfg: engine,
    )

    result = client.find_references(
        "add", str(main), Pos(1, line.index("add")), limit=3
    )

    assert result.status == QueryStatus.OK
    assert result.index_health == "complete"
    assert result.total_hits == 3
    assert {
        item.credibility.coverage.index_scope for item in result.semantic_results
    } == {IndexScope.INDEXED_PROJECT}
    assert engine.find_references_calls == 8


def test_find_references_empty_background_index_result_is_unresolved(
    tmp_path: Path,
):
    lib, main = write_project(tmp_path)
    touch_complete_index(tmp_path)
    engine = ReadyReferencesEngine(loc("sentinel", lib), ())
    line = main.read_text(encoding="utf-8").splitlines()[1]
    client = CodeGraph(
        BuildConfig(
            "test",
            str(tmp_path),
            background_index=True,
            index_ready_timeout=0,
            index_ready_probe_symbol="sentinel",
            index_ready_probe_path_suffix="lib.c",
        ),
        engine_version_probe=fake_engine_version_probe,
        engine_factory=lambda _cfg: engine,
    )

    result = client.find_references("missing", str(main), Pos(1, line.index("add")))

    assert result.status == QueryStatus.UNRESOLVED
    assert result.index_health == "unknown"
    assert result.total_hits == 0
    assert result.semantic_results == []


def test_find_references_not_ready_marks_partial_references_current_tu(
    tmp_path: Path,
):
    _lib, main = write_project(tmp_path)
    touch_complete_index(tmp_path)
    engine = ReadyReferencesEngine(
        loc("sentinel", main), (ref(main), ref(main, line=0))
    )
    line = main.read_text(encoding="utf-8").splitlines()[1]
    client = CodeGraph(
        BuildConfig(
            "test",
            str(tmp_path),
            background_index=True,
            index_ready_timeout=0,
            index_ready_poll_interval=0,
            index_ready_probe_symbol="sentinel",
            index_ready_probe_path_suffix="lib.c",
        ),
        engine_version_probe=fake_engine_version_probe,
        engine_factory=lambda _cfg: engine,
    )

    result = client.find_references("add", str(main), Pos(1, line.index("add")))

    assert result.status == QueryStatus.OK
    assert result.index_health == "unknown"
    assert result.total_hits == 2
    assert result.semantic_results
    assert all(
        item.credibility.coverage.index_scope is IndexScope.CURRENT_TU
        for item in result.semantic_results
    )
    assert engine.find_references_calls == 1


def test_find_references_background_index_off_marks_local_references_current_tu(
    tmp_path: Path,
):
    _lib, main = write_project(tmp_path)
    touch_complete_index(tmp_path)
    engine = ReadyReferencesEngine(
        loc("sentinel", main), (ref(main), ref(main, line=0))
    )
    line = main.read_text(encoding="utf-8").splitlines()[1]
    client = CodeGraph(
        BuildConfig("test", str(tmp_path), background_index=False),
        engine_version_probe=fake_engine_version_probe,
        engine_factory=lambda _cfg: engine,
    )

    result = client.find_references("add", str(main), Pos(1, line.index("add")))

    assert result.status == QueryStatus.OK
    assert result.index_health == "unknown"
    assert result.total_hits == 2
    assert all(
        item.credibility.coverage.index_scope is IndexScope.CURRENT_TU
        for item in result.semantic_results
    )
    assert engine.find_references_calls == 1


def test_find_callers_returns_positive_non_exhaustive_background_index_edges(
    tmp_path: Path,
):
    lib, main = write_project(tmp_path)
    touch_complete_index(tmp_path)
    edges = (
        call_edge(lib, main, caller_name="helper", callee_name="add"),
        call_edge(main, main, caller_name="main", callee_name="add"),
    )
    engine = ReadyCallEdgesEngine(callers=edges)
    line = main.read_text(encoding="utf-8").splitlines()[1]
    client = CodeGraph(
        BuildConfig(
            "test",
            str(tmp_path),
            source_roots=(str(tmp_path),),
            background_index=True,
            index_ready_poll_interval=0,
            warmup_file=str(main),
        ),
        engine_version_probe=fake_engine_version_probe,
        engine_factory=lambda _cfg: engine,
    )

    result = client.find_callers("add", str(main), Pos(1, line.index("add")))

    assert result.status == QueryStatus.OK
    assert result.query.kind == "relation"
    assert result.engine_version == "clangd 18.1.3"
    assert result.index_health == "complete"
    assert result.total_hits == 2
    assert len(result.semantic_results) == 2
    first = result.semantic_results[0]
    assert isinstance(first.data, CallEdgeResult)
    assert first.data.from_symbol.name == "helper"
    assert first.data.to_symbol.name == "add"
    assert first.credibility.relation is Relation.MUST
    assert first.credibility.coverage.index_scope is IndexScope.INDEXED_PROJECT
    assert first.credibility.coverage.is_exhaustive_within_scope is False
    assert result.status_credibility.coverage.is_exhaustive_within_scope is False
    assert engine.find_callers_calls == 4


def test_find_callers_waits_for_call_edges_to_stabilize(tmp_path: Path):
    lib, main = write_project(tmp_path)
    touch_complete_index(tmp_path)
    local = (call_edge(main, main, caller_name="main", callee_name="add"),)
    project = (
        call_edge(lib, main, caller_name="helper", callee_name="add"),
        call_edge(main, main, caller_name="main", callee_name="add"),
    )
    engine = ProgressiveCallEdgesEngine((local, project, project))
    line = main.read_text(encoding="utf-8").splitlines()[1]
    client = CodeGraph(
        BuildConfig(
            "test",
            str(tmp_path),
            source_roots=(str(tmp_path),),
            background_index=True,
            index_ready_timeout=1,
            index_ready_poll_interval=0,
            warmup_file=str(main),
        ),
        engine_version_probe=fake_engine_version_probe,
        engine_factory=lambda _cfg: engine,
    )

    result = client.find_callers("add", str(main), Pos(1, line.index("add")))

    assert result.status == QueryStatus.OK
    assert result.index_health == "complete"
    assert result.total_hits == 2
    assert {
        item.credibility.coverage.index_scope for item in result.semantic_results
    } == {IndexScope.INDEXED_PROJECT}
    assert engine.find_callers_calls == 5


def test_find_callers_does_not_treat_short_call_edge_plateau_as_ready(
    tmp_path: Path,
):
    lib, main = write_project(tmp_path)
    touch_complete_index(tmp_path)
    local = (call_edge(main, main, caller_name="main", callee_name="add"),)
    partial = (
        call_edge(lib, main, caller_name="helper", callee_name="add"),
        call_edge(main, main, caller_name="main", callee_name="add"),
    )
    project = (
        call_edge(lib, main, caller_name="helper", callee_name="add"),
        call_edge(lib, main, caller_name="other_helper", callee_name="add", line=0),
        call_edge(main, main, caller_name="main", callee_name="add"),
    )
    engine = ProgressiveCallEdgesEngine(
        (local, partial, partial, partial, project, project, project, project)
    )
    line = main.read_text(encoding="utf-8").splitlines()[1]
    client = CodeGraph(
        BuildConfig(
            "test",
            str(tmp_path),
            source_roots=(str(tmp_path),),
            background_index=True,
            index_ready_timeout=1,
            index_ready_poll_interval=0,
            warmup_file=str(main),
        ),
        engine_version_probe=fake_engine_version_probe,
        engine_factory=lambda _cfg: engine,
    )

    result = client.find_callers("add", str(main), Pos(1, line.index("add")))

    assert result.status == QueryStatus.OK
    assert result.index_health == "complete"
    assert result.total_hits == 3
    assert len(result.semantic_results) == 2
    assert len(result.syntactic_candidates) == 1
    assert engine.find_callers_calls == 8


def test_find_callers_not_ready_marks_local_edges_current_tu(tmp_path: Path):
    _lib, main = write_project(tmp_path)
    touch_complete_index(tmp_path)
    engine = ReadyCallEdgesEngine(
        callers=(
            call_edge(main, main, caller_name="main", callee_name="add"),
            call_edge(main, main, caller_name="other", callee_name="add", line=0),
        )
    )
    line = main.read_text(encoding="utf-8").splitlines()[1]
    client = CodeGraph(
        BuildConfig(
            "test",
            str(tmp_path),
            background_index=True,
            index_ready_timeout=0,
        ),
        engine_version_probe=fake_engine_version_probe,
        engine_factory=lambda _cfg: engine,
    )

    result = client.find_callers("add", str(main), Pos(1, line.index("add")))

    assert result.status == QueryStatus.OK
    assert result.index_health == "unknown"
    assert result.total_hits == 2
    assert result.semantic_results
    assert all(
        item.credibility.coverage.index_scope is IndexScope.CURRENT_TU
        for item in result.semantic_results
    )
    assert engine.find_callers_calls == 1


def test_find_callers_empty_background_index_result_is_unresolved(tmp_path: Path):
    _lib, main = write_project(tmp_path)
    touch_complete_index(tmp_path)
    engine = ReadyCallEdgesEngine(callers=())
    line = main.read_text(encoding="utf-8").splitlines()[1]
    client = CodeGraph(
        BuildConfig(
            "test",
            str(tmp_path),
            background_index=True,
            index_ready_timeout=0,
        ),
        engine_version_probe=fake_engine_version_probe,
        engine_factory=lambda _cfg: engine,
    )

    result = client.find_callers("add", str(main), Pos(1, line.index("add")))

    assert result.status == QueryStatus.UNRESOLVED
    assert result.index_health == "unknown"
    assert result.total_hits == 0
    assert result.semantic_results == []
    assert result.status_credibility.coverage.negative_scope.value == "none"


def test_find_callees_unsupported_returns_failed_without_fallback(tmp_path: Path):
    _lib, main = write_project(tmp_path)
    line = main.read_text(encoding="utf-8").splitlines()[1]
    client = CodeGraph(
        BuildConfig("test", str(tmp_path), background_index=True),
        engine_version_probe=fake_engine_version_probe,
        engine_factory=lambda _cfg: UnsupportedCalleesEngine(),
    )

    result = client.find_callees("add", str(main), Pos(1, line.index("add")))

    assert result.status == QueryStatus.FAILED
    assert result.engine_version == "clangd 18.1.3"
    assert result.semantic_results == []
    assert result.syntactic_candidates == []
    assert IssueCode.CALLHIERARCHY_UNSUPPORTED in [note.code for note in result.notes]


def test_find_callees_routes_outgoing_edges_when_engine_supports_them(
    tmp_path: Path,
):
    lib, main = write_project(tmp_path)
    touch_complete_index(tmp_path)
    edges = (call_edge(main, lib, caller_name="main", callee_name="add"),)
    engine = ReadyCallEdgesEngine(callees=edges)
    line = main.read_text(encoding="utf-8").splitlines()[1]
    client = CodeGraph(
        BuildConfig(
            "test",
            str(tmp_path),
            source_roots=(str(tmp_path),),
            background_index=True,
            index_ready_poll_interval=0,
            warmup_file=str(main),
        ),
        engine_version_probe=fake_engine_version_probe,
        engine_factory=lambda _cfg: engine,
    )

    result = client.find_callees("main", str(main), Pos(1, line.index("main")))

    assert result.status == QueryStatus.OK
    assert result.engine_version == "clangd 18.1.3"
    assert result.index_health == "complete"
    assert result.total_hits == 1
    edge = result.semantic_results[0].data
    assert isinstance(edge, CallEdgeResult)
    assert edge.from_symbol.name == "main"
    assert edge.to_symbol.name == "add"
    assert result.semantic_results[0].credibility.relation is Relation.MUST
    assert (
        result.semantic_results[0].credibility.coverage.is_exhaustive_within_scope
        is False
    )


def test_unstamped_index_is_unknown_and_cannot_claim_project_scope(tmp_path: Path):
    lib, main = write_project(tmp_path)
    touch_unstamped_complete_index(tmp_path)
    engine = ReadyCallEdgesEngine(
        callers=(call_edge(lib, main, caller_name="helper", callee_name="add"),)
    )
    line = main.read_text(encoding="utf-8").splitlines()[1]
    client = CodeGraph(
        BuildConfig(
            "test",
            str(tmp_path),
            background_index=True,
            index_ready_poll_interval=0,
        ),
        engine_version_probe=fake_engine_version_probe,
        engine_factory=lambda _cfg: engine,
    )

    result = client.find_callers("add", str(main), Pos(1, line.index("add")))

    assert result.status == QueryStatus.OK
    assert result.index_health == "unknown"
    assert all(
        item.credibility.coverage.index_scope is IndexScope.CURRENT_TU
        for item in result.semantic_results
    )
    unknown = next(
        note for note in result.notes if note.code == IssueCode.INDEX_UNKNOWN
    )
    assert "stamp missing" in unknown.detail
    assert IssueCode.INDEX_ENGINE_MISMATCH not in {note.code for note in result.notes}


def test_probe_claim_is_rechecked_against_started_engine(tmp_path: Path):
    lib, main = write_project(tmp_path)
    touch_complete_index(tmp_path)
    engine = ReadyCallEdgesEngine(
        callers=(call_edge(lib, main, caller_name="helper", callee_name="add"),)
    )
    engine.engine_version = "clangd 21.1.1"
    line = main.read_text(encoding="utf-8").splitlines()[1]
    client = CodeGraph(
        BuildConfig(
            "test",
            str(tmp_path),
            background_index=True,
            index_ready_poll_interval=0,
        ),
        engine_version_probe=fake_engine_version_probe,
        engine_factory=lambda _cfg: engine,
    )

    result = client.find_callers("add", str(main), Pos(1, line.index("add")))

    assert result.status == QueryStatus.UNRESOLVED
    assert result.engine_version == "clangd 21.1.1"
    assert result.index_health == "unknown"
    assert result.semantic_results == []
    assert engine.find_callers_calls == 0
    mismatch = next(
        note for note in result.notes if note.code == IssueCode.INDEX_ENGINE_MISMATCH
    )
    assert "clangd 18.1.3" in mismatch.detail
    assert "clangd 21.1.1" in mismatch.detail
    assert (
        result.status_credibility.coverage.index_scope is not IndexScope.INDEXED_PROJECT
    )


def test_known_engine_mismatch_is_rejected_before_clangd_starts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    write_project(tmp_path)
    touch_complete_index(tmp_path)
    started = False

    def fail_if_started(_config: object) -> NeverReadyEngine:
        nonlocal started
        started = True
        raise AssertionError("clangd must not start for a known mismatched cache")

    monkeypatch.setattr("codegraph.api.ClangdAdapter", fail_if_started)
    monkeypatch.setattr(
        "codegraph.api.detect_clangd_version", lambda _path: "clangd 21.1.1"
    )
    client = CodeGraph(
        BuildConfig(
            "test",
            str(tmp_path),
            clangd_path="clangd-21",
            background_index=True,
        )
    )

    result = client.search_symbol("add", kind_filter="function")

    assert started is False
    assert result.status == QueryStatus.UNRESOLVED
    assert result.index_health == "unknown"
    assert result.status_credibility.symbol_kind.value == "ordinary_function"
    assert IssueCode.INDEX_ENGINE_MISMATCH in {note.code for note in result.notes}


def test_stamped_cache_with_unknown_current_version_fails_closed(tmp_path: Path):
    write_project(tmp_path)
    touch_complete_index(tmp_path)
    factory_calls = 0

    def count_factory_calls(_config: object) -> NeverReadyEngine:
        nonlocal factory_calls
        factory_calls += 1
        return NeverReadyEngine()

    client = CodeGraph(
        BuildConfig(
            "test",
            str(tmp_path),
            clangd_path="missing-clangd",
            background_index=True,
        ),
        engine_version_probe=lambda _path: None,
        engine_factory=count_factory_calls,
    )

    result = client.search_symbol("add", kind_filter="function")

    assert factory_calls == 0
    assert result.status == QueryStatus.UNRESOLVED
    assert result.index_health == "unknown"
    assert result.status_credibility.symbol_kind.value == "ordinary_function"
    unavailable = next(
        note for note in result.notes if note.code == IssueCode.INDEX_UNKNOWN
    )
    assert "version unavailable" in unavailable.detail


def test_background_index_call_hierarchy_guard_rejects_exhaustive_results(
    tmp_path: Path,
):
    lib, main = write_project(tmp_path)
    exhaustive = exhaustive_background_index_credibility()
    query = QueryMeta("relation", "add", "test", str(main), Pos(1, 4))
    data = call_edge(lib, main)

    with pytest.raises(RuntimeError, match="call hierarchy must not assert exhaustive"):
        _ensure_background_index_call_hierarchy_is_non_exhaustive(
            QueryResult(
                query=query,
                status=QueryStatus.OK,
                status_credibility=exhaustive,
            )
        )

    with pytest.raises(RuntimeError, match="call hierarchy must not assert exhaustive"):
        _ensure_background_index_call_hierarchy_is_non_exhaustive(
            QueryResult(
                query=query,
                status=QueryStatus.OK,
                status_credibility=Credibility(
                    source=Source.CLANGD,
                    certainty=Certainty.SEMANTIC,
                    relation=Relation.NA,
                    resolved=Resolved.RESOLVED,
                    query_kind=QueryKind.RELATION,
                    dependency=DependencyScope.complete(),
                    coverage=Coverage(index_scope=IndexScope.INDEXED_PROJECT),
                    index_backend=IndexBackend.BACKGROUND_INDEX,
                    build_config_id="test",
                ),
                semantic_results=[],
                syntactic_candidates=[
                    Candidate(data=data, credibility=exhaustive, relevance_score=None)
                ],
            )
        )


class SentinelEngine(NeverReadyEngine):
    def __init__(
        self,
        header: LocationResult,
        probe_location: LocationResult,
        implementation: LocationResult,
    ):
        self.header = header
        self.probe_location = probe_location
        self.implementation = implementation
        self.probe_calls = 0
        self.ready = False

    def search_symbol(
        self,
        symbol: str,
        *,
        kind_filter: str | None = None,
        limit: int = 100,
        offset: int = 0,
        request_timeout: float | None = None,
    ) -> EngineObservationResult:
        if symbol == "target":
            return EngineObservationResult(locations=(self.header,))
        if symbol == "sentinel":
            self.probe_calls += 1
            if self.probe_calls >= 2:
                self.ready = True
                return EngineObservationResult(locations=(self.probe_location,))
        return EngineObservationResult()

    def get_definition(
        self,
        symbol: str,
        file: str,
        pos: Pos,
    ) -> EngineObservationResult:
        return EngineObservationResult(
            locations=(self.implementation if self.ready else self.header,)
        )


def test_ready_probe_is_not_satisfied_by_target_header_hit(tmp_path: Path):
    lib, main = write_project(tmp_path)
    touch_complete_index(tmp_path)
    engine = SentinelEngine(
        loc("target", main), loc("sentinel", lib), loc("target", lib)
    )
    line = main.read_text(encoding="utf-8").splitlines()[1]
    client = CodeGraph(
        BuildConfig(
            "test",
            str(tmp_path),
            background_index=True,
            index_ready_timeout=1,
            index_ready_poll_interval=0,
            index_ready_probe_symbol="sentinel",
            index_ready_probe_path_suffix="lib.c",
        ),
        engine_version_probe=fake_engine_version_probe,
        engine_factory=lambda _cfg: engine,
    )

    result = client.get_definition("target", str(main), Pos(1, line.index("add")))

    assert result.status == QueryStatus.OK
    assert result.index_health == "complete"
    assert result.semantic_results[0].data.symbol_id.file == str(lib)
    assert engine.probe_calls == 2


def test_ready_probe_requires_configured_path_suffix(tmp_path: Path):
    lib, main = write_project(tmp_path)
    touch_complete_index(tmp_path)
    engine = SentinelEngine(
        loc("target", main), loc("sentinel", lib), loc("target", lib)
    )
    line = main.read_text(encoding="utf-8").splitlines()[1]
    client = CodeGraph(
        BuildConfig(
            "test",
            str(tmp_path),
            background_index=True,
            index_ready_timeout=0,
            index_ready_probe_symbol="sentinel",
            index_ready_probe_path_suffix="other.c",
        ),
        engine_version_probe=fake_engine_version_probe,
        engine_factory=lambda _cfg: engine,
    )

    result = client.get_definition("target", str(main), Pos(1, line.index("add")))

    assert result.status == QueryStatus.OK
    assert result.index_health == "unknown"
    assert result.semantic_results[0].data.symbol_id.file == str(main)


def test_ready_probe_without_path_suffix_is_not_ready(tmp_path: Path):
    lib, _main = write_project(tmp_path)
    touch_complete_index(tmp_path)
    engine = SentinelEngine(
        loc("target", lib), loc("sentinel", lib), loc("target", lib)
    )
    client = CodeGraph(
        BuildConfig(
            "test",
            str(tmp_path),
            background_index=True,
            index_ready_probe_symbol="sentinel",
        ),
        engine_version_probe=fake_engine_version_probe,
        engine_factory=lambda _cfg: engine,
    )

    result = client.search_symbol("missing")

    assert result.status == QueryStatus.UNRESOLVED
    assert result.index_health == "unknown"
    assert engine.probe_calls == 0


def test_index_ready_probe_match_requires_path_suffix(tmp_path: Path):
    lib, _main = write_project(tmp_path)
    observation = EngineObservationResult(locations=(loc("sentinel", lib),))
    config = BuildConfig(
        "test",
        str(tmp_path),
        background_index=True,
        index_ready_probe_symbol="sentinel",
    )

    assert _index_ready_probe_matches(observation, "sentinel", config) is False


def test_reference_warmup_file_avoids_query_and_probe_suffix(tmp_path: Path):
    lib, main = write_project(tmp_path)
    config = BuildConfig(
        "test",
        str(tmp_path),
        background_index=True,
        index_ready_probe_symbol="sentinel",
        index_ready_probe_path_suffix="lib.c",
    )
    explicit = BuildConfig(
        "test",
        str(tmp_path),
        background_index=True,
        warmup_file=str(lib),
    )

    assert _reference_warmup_file(config, str(lib)) == str(main)
    assert _reference_warmup_file(config, str(main)) is None
    assert _reference_warmup_file(explicit, str(main)) == str(lib)


def test_background_index_reference_guard_rejects_exhaustive_status_and_candidates(
    tmp_path: Path,
):
    lib, _main = write_project(tmp_path)
    exhaustive = exhaustive_background_index_credibility()
    non_exhaustive = Credibility(
        source=Source.CLANGD,
        certainty=Certainty.SEMANTIC,
        relation=Relation.NA,
        resolved=Resolved.RESOLVED,
        query_kind=QueryKind.ENTITY,
        dependency=DependencyScope.complete(),
        coverage=Coverage(index_scope=IndexScope.INDEXED_PROJECT),
        index_backend=IndexBackend.BACKGROUND_INDEX,
        build_config_id="test",
    )
    query = QueryMeta("entity", "add", "test", str(lib), Pos(1, 4))

    with pytest.raises(RuntimeError, match="must not assert exhaustive"):
        _ensure_background_index_references_are_non_exhaustive(
            QueryResult(
                query=query,
                status=QueryStatus.OK,
                status_credibility=exhaustive,
            )
        )

    with pytest.raises(RuntimeError, match="must not assert exhaustive"):
        _ensure_background_index_references_are_non_exhaustive(
            QueryResult(
                query=query,
                status=QueryStatus.OK,
                status_credibility=non_exhaustive,
                syntactic_candidates=[
                    Candidate(
                        data=loc("add", lib),
                        credibility=exhaustive,
                        relevance_score=20,
                    )
                ],
            )
        )


def test_prewarm_warms_cache_but_query_still_proves_readiness(tmp_path: Path):
    lib, main = write_project(tmp_path)
    touch_complete_index(tmp_path)
    engine = SentinelEngine(
        loc("target", main), loc("sentinel", lib), loc("target", lib)
    )
    line = main.read_text(encoding="utf-8").splitlines()[1]
    client = CodeGraph(
        BuildConfig(
            "test",
            str(tmp_path),
            background_index=True,
            index_ready_timeout=1,
            index_ready_poll_interval=0,
            index_ready_probe_symbol="sentinel",
            index_ready_probe_path_suffix="lib.c",
            warmup_file=str(main),
        ),
        engine_version_probe=fake_engine_version_probe,
        engine_factory=lambda _cfg: engine,
    )

    assert client.prewarm() is True
    prewarm_probe_calls = engine.probe_calls
    result = client.get_definition("target", str(main), Pos(1, line.index("add")))

    assert result.status == QueryStatus.OK
    assert result.index_health == "complete"
    assert result.semantic_results[0].data.symbol_id.file == str(lib)
    assert engine.probe_calls > prewarm_probe_calls


def test_prewarm_failure_does_not_disable_later_query_warm(tmp_path: Path):
    lib, main = write_project(tmp_path)
    touch_complete_index(tmp_path)
    ready_engine = SentinelEngine(
        loc("target", main), loc("sentinel", lib), loc("target", lib)
    )
    engines = iter((NeverReadyEngine(), ready_engine))
    line = main.read_text(encoding="utf-8").splitlines()[1]
    client = CodeGraph(
        BuildConfig(
            "test",
            str(tmp_path),
            background_index=True,
            index_ready_timeout=1,
            prewarm_index_ready_timeout=0,
            index_ready_poll_interval=0,
            index_ready_probe_symbol="sentinel",
            index_ready_probe_path_suffix="lib.c",
        ),
        engine_version_probe=fake_engine_version_probe,
        engine_factory=lambda _cfg: next(engines),
    )

    assert client.prewarm() is False
    result = client.get_definition("target", str(main), Pos(1, line.index("add")))

    assert result.status == QueryStatus.OK
    assert result.index_health == "complete"
    assert result.semantic_results[0].data.symbol_id.file == str(lib)
    assert ready_engine.probe_calls == 2


class TimeoutProbeEngine(NeverReadyEngine):
    def __init__(self):
        self.request_timeouts: list[float | None] = []

    def search_symbol(
        self,
        symbol: str,
        *,
        kind_filter: str | None = None,
        limit: int = 100,
        offset: int = 0,
        request_timeout: float | None = None,
    ) -> EngineObservationResult:
        self.request_timeouts.append(request_timeout)
        time.sleep(min(request_timeout or 0.0, 0.02))
        raise TimeoutError("probe timed out")


def test_warm_background_index_passes_remaining_deadline_to_probe(tmp_path: Path):
    _lib, main = write_project(tmp_path)
    engine = TimeoutProbeEngine()
    config = BuildConfig(
        "test",
        str(tmp_path),
        background_index=True,
        index_ready_timeout=0.03,
        index_ready_poll_interval=0,
        index_ready_probe_symbol="sentinel",
        index_ready_probe_path_suffix="lib.c",
        request_timeout=5,
        warmup_file=str(main),
    )

    start = time.monotonic()
    ready = _warm_background_index(engine, config)
    elapsed = time.monotonic() - start

    assert ready is False
    assert elapsed < 0.1
    assert engine.request_timeouts
    assert 0 < engine.request_timeouts[0] <= config.index_ready_timeout


def test_prewarm_uses_independent_longer_timeout(tmp_path: Path):
    _lib, main = write_project(tmp_path)
    engine = TimeoutProbeEngine()
    config = BuildConfig(
        "test",
        str(tmp_path),
        background_index=True,
        index_ready_timeout=0.03,
        prewarm_index_ready_timeout=0.2,
        index_ready_poll_interval=0,
        index_ready_probe_symbol="sentinel",
        index_ready_probe_path_suffix="lib.c",
        request_timeout=5,
        warmup_file=str(main),
    )
    client = CodeGraph(
        config,
        engine_version_probe=fake_engine_version_probe,
        engine_factory=lambda _cfg: engine,
    )

    assert client.prewarm() is False

    assert engine.request_timeouts
    assert engine.request_timeouts[0] is not None
    assert config.index_ready_timeout < engine.request_timeouts[0] <= 0.2


def test_prewarm_default_timeout_is_at_least_thirty_seconds(tmp_path: Path):
    short = BuildConfig("short", str(tmp_path), index_ready_timeout=8)
    long = BuildConfig("long", str(tmp_path), index_ready_timeout=45)
    explicit = BuildConfig(
        "explicit",
        str(tmp_path),
        index_ready_timeout=8,
        prewarm_index_ready_timeout=12,
    )

    assert _prewarm_index_ready_timeout(short) == 30.0
    assert _prewarm_index_ready_timeout(long) == 45
    assert _prewarm_index_ready_timeout(explicit) == 12


def test_query_warm_still_uses_query_timeout_not_prewarm_timeout(tmp_path: Path):
    _lib, main = write_project(tmp_path)
    touch_complete_index(tmp_path)
    engine = TimeoutProbeEngine()
    line = main.read_text(encoding="utf-8").splitlines()[1]
    client = CodeGraph(
        BuildConfig(
            "test",
            str(tmp_path),
            background_index=True,
            index_ready_timeout=0.03,
            prewarm_index_ready_timeout=0.2,
            index_ready_poll_interval=0,
            index_ready_probe_symbol="sentinel",
            index_ready_probe_path_suffix="lib.c",
            request_timeout=5,
        ),
        engine_version_probe=fake_engine_version_probe,
        engine_factory=lambda _cfg: engine,
    )

    result = client.get_definition("missing", str(main), Pos(1, line.index("add")))

    assert result.status == QueryStatus.UNRESOLVED
    assert result.index_health == "unknown"
    assert engine.request_timeouts
    assert engine.request_timeouts[0] is not None
    assert 0 < engine.request_timeouts[0] <= 0.03


def test_invalid_inputs_and_engine_failures_return_structured_results(tmp_path: Path):
    _lib, main = write_project(tmp_path)
    client = CodeGraph(
        BuildConfig("test", str(tmp_path), background_index=False),
        engine_version_probe=fake_engine_version_probe,
        engine_factory=lambda _cfg: FailingEngine(),
    )

    assert client.search_symbol("add", kind_filter="bad").status == (
        QueryStatus.INVALID_REQUEST
    )
    assert client.get_definition("add", str(main), Pos(99, 0)).status == (
        QueryStatus.INVALID_REQUEST
    )
    failed = client.search_symbol("add")
    assert failed.status == QueryStatus.FAILED

    definition_failed = CodeGraph(
        BuildConfig("test", str(tmp_path), background_index=False),
        engine_version_probe=fake_engine_version_probe,
        engine_factory=lambda _cfg: DefinitionFailingEngine(),
    ).get_definition("add", str(main), Pos(1, 0))
    assert definition_failed.status == QueryStatus.FAILED


def test_get_definition_rejects_invalid_paths_and_positions(tmp_path: Path):
    _lib, main = write_project(tmp_path)
    client = CodeGraph(BuildConfig("test", str(tmp_path), background_index=False))

    assert client.get_definition(
        "add", str(tmp_path / "missing.c"), Pos(0, 0)
    ).status == (QueryStatus.INVALID_REQUEST)
    assert client.get_definition("add", str(main), Pos(-1, 0)).status == (
        QueryStatus.INVALID_REQUEST
    )
    assert client.get_definition("add", str(main), Pos(99, 0)).status == (
        QueryStatus.INVALID_REQUEST
    )
    assert client.get_definition("add", str(main), Pos(0, 999)).status == (
        QueryStatus.INVALID_REQUEST
    )


def test_background_index_not_ready_downgrades_health_to_avoid_false_not_found(
    tmp_path: Path,
):
    _lib, main = write_project(tmp_path)
    touch_complete_index(tmp_path)
    line = main.read_text(encoding="utf-8").splitlines()[1]
    client = CodeGraph(
        BuildConfig(
            "test",
            str(tmp_path),
            background_index=True,
            index_ready_timeout=0,
        ),
        engine_version_probe=fake_engine_version_probe,
        engine_factory=lambda _cfg: NeverReadyEngine(),
    )

    result = client.get_definition("missing", str(main), Pos(1, line.index("add")))

    assert result.status == QueryStatus.UNRESOLVED
    assert result.index_health == "unknown"


def test_module_level_registry_reports_unknown_config():
    clear_build_configs()

    assert prewarm_build_config("missing") is False
    assert api_search_symbol("add", build_config_id="missing").status == (
        QueryStatus.INVALID_REQUEST
    )
    assert (
        api_get_definition(
            "add", "/tmp/missing.c", Pos(0, 0), build_config_id="missing"
        ).status
        == QueryStatus.INVALID_REQUEST
    )
    assert (
        api_find_references(
            "add", "/tmp/missing.c", Pos(0, 0), build_config_id="missing"
        ).status
        == QueryStatus.INVALID_REQUEST
    )
    assert (
        api_find_callers(
            "add", "/tmp/missing.c", Pos(0, 0), build_config_id="missing"
        ).status
        == QueryStatus.INVALID_REQUEST
    )
    assert (
        api_find_callees(
            "add", "/tmp/missing.c", Pos(0, 0), build_config_id="missing"
        ).status
        == QueryStatus.INVALID_REQUEST
    )


def test_module_level_registry_validates_and_delegates(monkeypatch, tmp_path: Path):
    _lib, main = write_project(tmp_path)
    clear_build_configs()
    register_build_config(BuildConfig("test", str(tmp_path)))
    search_marker = object()
    definition_marker = object()
    references_marker = object()
    callers_marker = object()
    callees_marker = object()
    calls: list[tuple[str, object]] = []

    class DummyCodeGraph:
        def __init__(self, config: BuildConfig):
            calls.append(("init", config.build_config_id))

        def search_symbol(
            self,
            symbol: str,
            *,
            kind_filter: str | None = None,
            limit: int = 100,
            offset: int = 0,
        ):
            calls.append(("search", (symbol, kind_filter, limit, offset)))
            return search_marker

        def get_definition(
            self,
            symbol: str,
            file: str,
            pos: Pos,
            *,
            allow_syntactic_fallback: bool = False,
        ):
            calls.append(("definition", (symbol, file, pos, allow_syntactic_fallback)))
            return definition_marker

        def find_references(
            self,
            symbol: str,
            file: str,
            pos: Pos,
            *,
            limit: int = 100,
            offset: int = 0,
            allow_syntactic_fallback: bool = False,
        ):
            calls.append(
                (
                    "references",
                    (symbol, file, pos, limit, offset, allow_syntactic_fallback),
                )
            )
            return references_marker

        def find_callers(
            self,
            symbol: str,
            file: str,
            pos: Pos,
            *,
            limit: int = 100,
            offset: int = 0,
            allow_syntactic_fallback: bool = False,
        ):
            calls.append(
                (
                    "callers",
                    (symbol, file, pos, limit, offset, allow_syntactic_fallback),
                )
            )
            return callers_marker

        def find_callees(
            self,
            symbol: str,
            file: str,
            pos: Pos,
            *,
            limit: int = 100,
            offset: int = 0,
            allow_syntactic_fallback: bool = False,
        ):
            calls.append(
                (
                    "callees",
                    (symbol, file, pos, limit, offset, allow_syntactic_fallback),
                )
            )
            return callees_marker

    monkeypatch.setattr("codegraph.api.CodeGraph", DummyCodeGraph)

    assert api_search_symbol(
        "add", build_config_id="test", kind_filter="bad"
    ).status == (QueryStatus.INVALID_REQUEST)
    assert api_search_symbol("add", build_config_id="test", limit=3) is search_marker
    assert (
        api_get_definition("add", str(main), Pos(1, 0), build_config_id="test")
        is definition_marker
    )
    assert (
        api_find_references(
            "add", str(main), Pos(1, 0), build_config_id="test", limit=7, offset=2
        )
        is references_marker
    )
    assert (
        api_find_callers(
            "add", str(main), Pos(1, 0), build_config_id="test", limit=5, offset=1
        )
        is callers_marker
    )
    assert (
        api_find_callees(
            "add", str(main), Pos(1, 0), build_config_id="test", limit=4, offset=3
        )
        is callees_marker
    )
    assert calls == [
        ("init", "test"),
        ("search", ("add", None, 3, 0)),
        ("init", "test"),
        ("definition", ("add", str(main), Pos(1, 0), False)),
        ("init", "test"),
        ("references", ("add", str(main), Pos(1, 0), 7, 2, False)),
        ("init", "test"),
        ("callers", ("add", str(main), Pos(1, 0), 5, 1, False)),
        ("init", "test"),
        ("callees", ("add", str(main), Pos(1, 0), 4, 3, False)),
    ]


def test_register_build_config_can_explicitly_prewarm(monkeypatch, tmp_path: Path):
    clear_build_configs()
    calls: list[tuple[str, object]] = []

    class DummyCodeGraph:
        def __init__(self, config: BuildConfig):
            calls.append(("init", config.build_config_id))

        def prewarm(self):
            calls.append(("prewarm", None))
            return True

    monkeypatch.setattr("codegraph.api.CodeGraph", DummyCodeGraph)

    assert (
        register_build_config(BuildConfig("test", str(tmp_path)), prewarm=True) is None
    )
    assert prewarm_build_config("test")
    assert calls == [
        ("init", "test"),
        ("prewarm", None),
        ("init", "test"),
        ("prewarm", None),
    ]
