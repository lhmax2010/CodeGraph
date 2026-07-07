from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

import pytest

from codegraph.api import (
    BuildConfig,
    CodeGraph,
    _index_ready_probe_matches,
    _prewarm_index_ready_timeout,
    _warm_background_index,
    clear_build_configs,
    get_definition as api_get_definition,
    prewarm_build_config,
    register_build_config,
    search_symbol as api_search_symbol,
)
from codegraph.engines.protocol import EngineObservationResult
from codegraph.types import LocationResult, Pos, QueryStatus, Range, SymbolId


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


def loc(name: str, file: Path, line: int = 1) -> LocationResult:
    pos = Pos(line, 4)
    return LocationResult(
        SymbolId(None, name, str(file), pos),
        Range(pos, Pos(line, 7)),
        "ordinary_function",
    )


@pytest.mark.skipif(shutil.which("clangd") is None, reason="clangd unavailable")
def test_search_symbol_and_get_definition_e2e_with_background_index(tmp_path: Path):
    lib, main = write_project(tmp_path)
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

    assert definition.status == QueryStatus.OK
    assert definition.index_health == "complete"
    assert [r.data.symbol_id.file for r in definition.semantic_results] == [str(lib)]
    assert search.status == QueryStatus.OK
    assert search.index_health == "complete"
    assert [r.data.symbol_id.name for r in search.semantic_results] == ["add"]
    assert [r.data.symbol_id.file for r in search.semantic_results] == [str(lib)]


class NeverReadyEngine:
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
    assert result.index_health == "complete"


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
        engine_factory=lambda _cfg: ReadyNoDefinitionEngine(loc("sentinel", lib)),
    )

    result = client.search_symbol("missing")

    assert result.status == QueryStatus.UNRESOLVED
    assert result.index_health == "complete"
    assert result.status_credibility.symbol_kind.value == "unknown"


def test_search_symbol_function_filter_can_assert_not_found(tmp_path: Path):
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
        engine_factory=lambda _cfg: ReadyNoDefinitionEngine(loc("sentinel", lib)),
    )

    result = client.search_symbol("missing", kind_filter="function")

    assert result.status == QueryStatus.NOT_FOUND
    assert result.index_health == "complete"
    assert result.status_credibility.symbol_kind.value == "ordinary_function"


def test_background_index_off_cannot_use_complete_health_for_not_found(tmp_path: Path):
    _lib, main = write_project(tmp_path)
    touch_complete_index(tmp_path)
    line = main.read_text(encoding="utf-8").splitlines()[1]
    client = CodeGraph(
        BuildConfig("test", str(tmp_path), background_index=False),
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
        engine_factory=lambda _cfg: ReadyNoDefinitionEngine(loc("sentinel", lib)),
    )

    result = client.get_definition("missing", str(main), Pos(1, line.index("add")))

    assert result.status == QueryStatus.UNRESOLVED
    assert result.index_health == "complete"
    assert result.total_hits == 0
    assert result.status_credibility.symbol_kind.value == "unknown"


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
    client = CodeGraph(config, engine_factory=lambda _cfg: engine)

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


def test_module_level_registry_validates_and_delegates(monkeypatch, tmp_path: Path):
    _lib, main = write_project(tmp_path)
    clear_build_configs()
    register_build_config(BuildConfig("test", str(tmp_path)))
    search_marker = object()
    definition_marker = object()
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

    monkeypatch.setattr("codegraph.api.CodeGraph", DummyCodeGraph)

    assert api_search_symbol(
        "add", build_config_id="test", kind_filter="bad"
    ).status == (QueryStatus.INVALID_REQUEST)
    assert api_search_symbol("add", build_config_id="test", limit=3) is search_marker
    assert (
        api_get_definition("add", str(main), Pos(1, 0), build_config_id="test")
        is definition_marker
    )
    assert calls == [
        ("init", "test"),
        ("search", ("add", None, 3, 0)),
        ("init", "test"),
        ("definition", ("add", str(main), Pos(1, 0), False)),
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
