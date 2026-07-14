"""Public CodeGraph library API for semantic code queries."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, replace
from pathlib import Path
from types import TracebackType
from typing import Callable, Iterable, Literal, Protocol

from .credibility import (
    ActiveConfig,
    IndexBackend,
    IndexHealth,
    IndexScope,
    QueryKind,
    SymbolKind,
)
from .engines.clangd_adapter import ClangdAdapter, ClangdAdapterConfig
from .engines.protocol import EngineObservation, EngineObservationResult
from .engines.treesitter_adapter import create_treesitter_provider
from .engine_version import detect_clangd_version
from .factories import make_error_credibility
from .indexing import (
    IndexHealthReport,
    evaluate_index_health,
    index_dir_for_compile_commands_dir,
    scan_index_shards,
    summarize_compile_commands,
)
from .routing import route_engine_call, route_observation, validate_query_result
from .types import (
    CallEdgeResult,
    IssueCode,
    Note,
    Pos,
    QueryMeta,
    QueryResult,
    QueryStatus,
)

_KIND_FILTERS = {
    "function": SymbolKind.ORDINARY_FUNCTION,
    "variable": SymbolKind.ORDINARY_VARIABLE,
    "type": SymbolKind.TYPE,
    "macro": SymbolKind.MACRO,
}
_DEFAULT_PREWARM_INDEX_READY_TIMEOUT = 30.0
_STABLE_MATCHES = 3
_INDEX_ENGINE_BLOCKING_REASONS = {
    "index_engine_build_in_progress",
    "index_engine_mismatch",
    "index_engine_stamp_invalid",
    "index_engine_stamp_write_failed",
    "index_engine_unavailable",
    "index_health_error",
}
EngineVersionProbe = Callable[[str], str | None]


@dataclass(frozen=True)
class BuildConfig:
    """One build config whose CDB/cache is owned by one exact clangd version."""

    build_config_id: str
    compile_commands_dir: str
    source_roots: tuple[str, ...] = ()
    clangd_path: str = "clangd"
    background_index: bool = True
    request_timeout: float = 30.0
    diagnostics_wait: float = 0.5
    index_ready_timeout: float = 5.0
    prewarm_index_ready_timeout: float | None = None
    index_ready_poll_interval: float = 0.25
    index_ready_probe_symbol: str | None = None
    index_ready_probe_path_suffix: str | None = None
    warmup_file: str | None = None
    active_config: ActiveConfig = ActiveConfig.UNKNOWN
    index_scope: IndexScope = IndexScope.INDEXED_PROJECT


_BUILD_CONFIGS: dict[str, BuildConfig] = {}


class ManagedEngine(EngineObservation, Protocol):
    def __enter__(self) -> "ManagedEngine": ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...


def register_build_config(config: BuildConfig, *, prewarm: bool = False) -> None:
    """Register a build config for the module-level API functions."""

    _BUILD_CONFIGS[config.build_config_id] = config
    if prewarm:
        prewarm_build_config(config.build_config_id)


def prewarm_build_config(build_config_id: str) -> bool:
    """Warm a registered build config without granting future queries readiness."""

    config = _BUILD_CONFIGS.get(build_config_id)
    if config is None:
        return False
    return CodeGraph(config).prewarm()


def clear_build_configs() -> None:
    """Clear module-level build configs, mainly for tests."""

    _BUILD_CONFIGS.clear()


def search_symbol(
    symbol: str,
    *,
    build_config_id: str,
    kind_filter: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> QueryResult:
    """Search for a symbol in a registered build configuration."""

    query = QueryMeta("entity", symbol, build_config_id)
    config = _BUILD_CONFIGS.get(build_config_id)
    if config is None:
        return _invalid_result(query, f"unknown build_config_id: {build_config_id}")
    normalized_kind = _normalize_kind_filter(kind_filter)
    if normalized_kind is None and kind_filter is not None:
        return _invalid_result(query, f"invalid kind_filter: {kind_filter}")
    client = CodeGraph(config)
    return client.search_symbol(
        symbol, kind_filter=kind_filter, limit=limit, offset=offset
    )


def get_definition(
    symbol: str,
    file: str,
    pos: Pos,
    *,
    build_config_id: str,
    allow_syntactic_fallback: bool = False,
) -> QueryResult:
    """Return the definition location for a symbol in a registered build config."""

    query = QueryMeta("entity", symbol, build_config_id, str(file), pos)
    config = _BUILD_CONFIGS.get(build_config_id)
    if config is None:
        return _invalid_result(query, f"unknown build_config_id: {build_config_id}")
    client = CodeGraph(config)
    return client.get_definition(
        symbol,
        file,
        pos,
        allow_syntactic_fallback=allow_syntactic_fallback,
    )


def find_references(
    symbol: str,
    file: str,
    pos: Pos,
    *,
    build_config_id: str,
    limit: int = 100,
    offset: int = 0,
    allow_syntactic_fallback: bool = False,
) -> QueryResult:
    """Return references for a symbol in a registered build config."""

    query = QueryMeta("entity", symbol, build_config_id, str(file), pos)
    config = _BUILD_CONFIGS.get(build_config_id)
    if config is None:
        return _invalid_result(query, f"unknown build_config_id: {build_config_id}")
    client = CodeGraph(config)
    return client.find_references(
        symbol,
        file,
        pos,
        limit=limit,
        offset=offset,
        allow_syntactic_fallback=allow_syntactic_fallback,
    )


def find_callers(
    symbol: str,
    file: str,
    pos: Pos,
    *,
    build_config_id: str,
    limit: int = 100,
    offset: int = 0,
    allow_syntactic_fallback: bool = False,
) -> QueryResult:
    """Return callers for a symbol in a registered build config."""

    query = QueryMeta("relation", symbol, build_config_id, str(file), pos)
    config = _BUILD_CONFIGS.get(build_config_id)
    if config is None:
        return _invalid_result(query, f"unknown build_config_id: {build_config_id}")
    client = CodeGraph(config)
    return client.find_callers(
        symbol,
        file,
        pos,
        limit=limit,
        offset=offset,
        allow_syntactic_fallback=allow_syntactic_fallback,
    )


def find_callees(
    symbol: str,
    file: str,
    pos: Pos,
    *,
    build_config_id: str,
    limit: int = 100,
    offset: int = 0,
    allow_syntactic_fallback: bool = False,
) -> QueryResult:
    """Return callees for a symbol in a registered build config."""

    query = QueryMeta("relation", symbol, build_config_id, str(file), pos)
    config = _BUILD_CONFIGS.get(build_config_id)
    if config is None:
        return _invalid_result(query, f"unknown build_config_id: {build_config_id}")
    client = CodeGraph(config)
    return client.find_callees(
        symbol,
        file,
        pos,
        limit=limit,
        offset=offset,
        allow_syntactic_fallback=allow_syntactic_fallback,
    )


class CodeGraph:
    """API facade that wires P3/P4/P5 into the P2 router."""

    def __init__(
        self,
        config: BuildConfig,
        *,
        engine_factory: Callable[[ClangdAdapterConfig], ManagedEngine] | None = None,
        engine_version_probe: EngineVersionProbe | None = None,
    ):
        self.config = config
        self._engine_factory = engine_factory or (lambda cfg: ClangdAdapter(cfg))
        self._engine_version_probe = (
            engine_version_probe
            if engine_version_probe is not None
            else detect_clangd_version
        )

    def prewarm(self, file: str | None = None) -> bool:
        """Warm clangd/index caches; each user query still proves readiness itself."""

        health = _initial_index_health(self.config, self._engine_version_probe)
        if _index_engine_blocks_use(health, self.config.background_index):
            return False
        try:
            with self._engine_factory(self._clangd_config()) as engine:
                engine_version = _managed_engine_version(engine)
                health = _index_health(self.config, engine_version)
                if _index_engine_blocks_use(health, self.config.background_index):
                    return False
                ready = _warm_background_index(
                    engine,
                    self.config,
                    file,
                    timeout=_prewarm_index_ready_timeout(self.config),
                )
                if ready:
                    health = _index_health(self.config, engine_version)
                return ready and health.reason not in {
                    "index_engine_unverified",
                    "index_engine_mismatch",
                    "index_engine_stamp_invalid",
                    "index_engine_unavailable",
                }
        except Exception:
            return False

    def search_symbol(
        self,
        symbol: str,
        *,
        kind_filter: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> QueryResult:
        query = QueryMeta("entity", symbol, self.config.build_config_id)
        kind = _normalize_kind_filter(kind_filter)
        if kind is None and kind_filter is not None:
            return _invalid_result(query, f"invalid kind_filter: {kind_filter}")
        provider = create_treesitter_provider(self.config.source_roots)
        health = _initial_index_health(self.config, self._engine_version_probe)
        if _index_engine_blocks_use(health, self.config.background_index):
            return _index_guard_unresolved(
                query,
                health,
                active_config=self.config.active_config,
                symbol_kind=_search_symbol_kind(kind),
            )
        engine_version: str | None = None
        try:
            with self._engine_factory(self._clangd_config()) as engine:
                engine_version = _managed_engine_version(engine)
                health = _index_health(self.config, engine_version)
                if _index_engine_blocks_use(health, self.config.background_index):
                    return _index_guard_unresolved(
                        query,
                        health,
                        active_config=self.config.active_config,
                        symbol_kind=_search_symbol_kind(kind),
                    )
                ready = _warm_background_index(engine, self.config)
                engine_limit = _semantic_search_limit(limit, offset)
                observation = engine.search_symbol(
                    symbol,
                    kind_filter=kind.value if kind is not None else None,
                    limit=engine_limit,
                    offset=0,
                )
                search_window_may_be_truncated = _search_window_may_be_truncated(
                    observation, engine_limit
                )
        except Exception as exc:  # noqa: BLE001 - API reports engine failures.
            return _with_index_engine_health_note(_engine_failure(query, exc), health)
        health = _health_after_warm(
            health, self.config, ready, engine_version=engine_version
        )
        observation, total_hits = _exact_symbol_observation(
            observation, symbol, limit=limit, offset=offset
        )
        ready_for_negative_proof = (
            ready
            and health.health == IndexHealth.COMPLETE
            and not (search_window_may_be_truncated and total_hits == 0)
        )
        if self.config.background_index and not observation.locations:
            ready_for_negative_proof = False
        result = route_observation(
            query,
            observation,
            syntactic_provider=provider,
            kind_filter=kind.value if kind is not None else None,
            limit=limit,
            offset=offset,
            index_scope=_effective_index_scope(self.config, ready_for_negative_proof),
            index_health=_effective_health(
                health.health, self.config, ready_for_negative_proof
            ),
            index_backend=IndexBackend.BACKGROUND_INDEX,
            active_config=self.config.active_config,
            symbol_kind=_search_symbol_kind(kind),
            total_hits=total_hits,
        )
        return _with_index_engine_health_note(result, health)

    def get_definition(
        self,
        symbol: str,
        file: str,
        pos: Pos,
        *,
        allow_syntactic_fallback: bool = False,
    ) -> QueryResult:
        real_file = str(Path(file).resolve())
        query = QueryMeta("entity", symbol, self.config.build_config_id, real_file, pos)
        invalid = _validate_file_pos(real_file, pos)
        if invalid is not None:
            return _invalid_result(query, invalid)
        provider = create_treesitter_provider(self.config.source_roots)
        health = _initial_index_health(self.config, self._engine_version_probe)
        if _index_engine_blocks_use(health, self.config.background_index):
            return _index_guard_unresolved(
                query,
                health,
                active_config=self.config.active_config,
                symbol_kind=SymbolKind.UNKNOWN,
            )
        engine_version: str | None = None
        try:
            with self._engine_factory(self._clangd_config()) as engine:
                engine_version = _managed_engine_version(engine)
                health = _index_health(self.config, engine_version)
                if _index_engine_blocks_use(health, self.config.background_index):
                    return _index_guard_unresolved(
                        query,
                        health,
                        active_config=self.config.active_config,
                        symbol_kind=SymbolKind.UNKNOWN,
                    )
                ready = _warm_background_index(engine, self.config, real_file)
                observation = engine.get_definition(symbol, real_file, pos)
        except Exception as exc:  # noqa: BLE001 - API reports engine failures.
            return _with_index_engine_health_note(_engine_failure(query, exc), health)
        health = _health_after_warm(
            health, self.config, ready, engine_version=engine_version
        )
        ready_for_negative_proof = ready and health.health == IndexHealth.COMPLETE
        if self.config.background_index and not observation.locations:
            ready_for_negative_proof = False
        result = route_observation(
            query,
            observation,
            syntactic_provider=provider,
            allow_syntactic_fallback=allow_syntactic_fallback,
            index_scope=_effective_index_scope(self.config, ready_for_negative_proof),
            index_health=_effective_health(
                health.health, self.config, ready_for_negative_proof
            ),
            index_backend=IndexBackend.BACKGROUND_INDEX,
            active_config=self.config.active_config,
            symbol_kind=SymbolKind.UNKNOWN,
            total_hits=len(observation.locations),
        )
        return _with_index_engine_health_note(result, health)

    def find_references(
        self,
        symbol: str,
        file: str,
        pos: Pos,
        *,
        limit: int = 100,
        offset: int = 0,
        allow_syntactic_fallback: bool = False,
    ) -> QueryResult:
        real_file = str(Path(file).resolve())
        query = QueryMeta("entity", symbol, self.config.build_config_id, real_file, pos)
        invalid = _validate_file_pos(real_file, pos)
        if invalid is not None:
            return _invalid_result(query, invalid)
        provider = create_treesitter_provider(self.config.source_roots)
        health = _initial_index_health(self.config, self._engine_version_probe)
        if _index_engine_blocks_use(health, self.config.background_index):
            return _index_guard_unresolved(
                query,
                health,
                active_config=self.config.active_config,
                symbol_kind=SymbolKind.UNKNOWN,
            )
        observation = EngineObservationResult()
        ready = False
        engine_version: str | None = None
        try:
            with self._engine_factory(self._clangd_config()) as engine:
                engine_version = _managed_engine_version(engine)
                health = _index_health(self.config, engine_version)
                if _index_engine_blocks_use(health, self.config.background_index):
                    return _index_guard_unresolved(
                        query,
                        health,
                        active_config=self.config.active_config,
                        symbol_kind=SymbolKind.UNKNOWN,
                    )
                warmup_file = _reference_warmup_file(self.config, real_file)
                _warm_references_file(engine, self.config, warmup_file)
                observation, ready = _find_references_with_stable_cross_tu(
                    engine,
                    self.config,
                    symbol,
                    real_file,
                    pos,
                    limit,
                    offset,
                )
        except Exception as exc:  # noqa: BLE001 - API reports engine failures.
            return _with_index_engine_health_note(_engine_failure(query, exc), health)
        health = _health_after_warm(
            health, self.config, ready, engine_version=engine_version
        )
        total_hits = (
            observation.total_results
            if observation.total_results is not None
            else len(observation.references)
        )
        ready_for_references = (
            ready
            and health.health == IndexHealth.COMPLETE
            and _references_have_cross_tu_evidence(observation, real_file)
        )
        if self.config.background_index and total_hits == 0:
            ready_for_references = False
        result = route_observation(
            query,
            observation,
            syntactic_provider=provider,
            allow_syntactic_fallback=allow_syntactic_fallback,
            limit=limit,
            offset=offset,
            index_scope=_effective_index_scope(self.config, ready_for_references),
            index_health=_effective_health(
                health.health, self.config, ready_for_references
            ),
            index_backend=IndexBackend.BACKGROUND_INDEX,
            active_config=self.config.active_config,
            symbol_kind=SymbolKind.UNKNOWN,
            total_hits=total_hits,
        )
        result = _with_index_engine_health_note(result, health)
        return _ensure_background_index_references_are_non_exhaustive(result)

    def find_callers(
        self,
        symbol: str,
        file: str,
        pos: Pos,
        *,
        limit: int = 100,
        offset: int = 0,
        allow_syntactic_fallback: bool = False,
    ) -> QueryResult:
        return self._find_call_edges(
            "callers",
            symbol,
            file,
            pos,
            limit=limit,
            offset=offset,
            allow_syntactic_fallback=allow_syntactic_fallback,
        )

    def find_callees(
        self,
        symbol: str,
        file: str,
        pos: Pos,
        *,
        limit: int = 100,
        offset: int = 0,
        allow_syntactic_fallback: bool = False,
    ) -> QueryResult:
        return self._find_call_edges(
            "callees",
            symbol,
            file,
            pos,
            limit=limit,
            offset=offset,
            allow_syntactic_fallback=allow_syntactic_fallback,
        )

    def _find_call_edges(
        self,
        direction: Literal["callers", "callees"],
        symbol: str,
        file: str,
        pos: Pos,
        *,
        limit: int,
        offset: int,
        allow_syntactic_fallback: bool,
    ) -> QueryResult:
        real_file = str(Path(file).resolve())
        query = QueryMeta(
            "relation", symbol, self.config.build_config_id, real_file, pos
        )
        invalid = _validate_file_pos(real_file, pos)
        if invalid is not None:
            return _invalid_result(query, invalid)
        provider = create_treesitter_provider(self.config.source_roots)
        health = _initial_index_health(self.config, self._engine_version_probe)
        if _index_engine_blocks_use(health, self.config.background_index):
            return _index_guard_unresolved(
                query,
                health,
                active_config=self.config.active_config,
                symbol_kind=SymbolKind.ORDINARY_FUNCTION,
            )
        observation = EngineObservationResult()
        ready = False
        engine_version: str | None = None
        try:
            with self._engine_factory(self._clangd_config()) as engine:
                engine_version = _managed_engine_version(engine)
                health = _index_health(self.config, engine_version)
                if _index_engine_blocks_use(health, self.config.background_index):
                    return _index_guard_unresolved(
                        query,
                        health,
                        active_config=self.config.active_config,
                        symbol_kind=SymbolKind.ORDINARY_FUNCTION,
                        engine_version=engine_version,
                    )
                warmup_file = _reference_warmup_file(self.config, real_file)
                _warm_references_file(engine, self.config, warmup_file)
                observation, ready = _find_call_edges_with_stable_cross_tu(
                    engine,
                    self.config,
                    direction,
                    symbol,
                    real_file,
                    pos,
                    limit,
                    offset,
                )
        except Exception as exc:  # noqa: BLE001 - API reports engine failures.
            result = _engine_failure(query, exc, engine_version=engine_version)
            return _with_index_engine_health_note(result, health)
        health = _health_after_warm(
            health, self.config, ready, engine_version=engine_version
        )
        total_hits = (
            observation.total_results
            if observation.total_results is not None
            else len(observation.call_edges)
        )
        ready_for_call_edges = (
            ready
            and health.health == IndexHealth.COMPLETE
            and _call_edges_have_cross_tu_evidence(observation, real_file, direction)
        )
        if self.config.background_index and total_hits == 0:
            ready_for_call_edges = False
        result = route_observation(
            query,
            observation,
            syntactic_provider=provider,
            allow_syntactic_fallback=allow_syntactic_fallback,
            limit=limit,
            offset=offset,
            index_scope=_effective_index_scope(self.config, ready_for_call_edges),
            index_health=_effective_health(
                health.health, self.config, ready_for_call_edges
            ),
            index_backend=IndexBackend.BACKGROUND_INDEX,
            active_config=self.config.active_config,
            symbol_kind=SymbolKind.ORDINARY_FUNCTION,
            total_hits=total_hits,
        )
        result = validate_query_result(replace(result, engine_version=engine_version))
        result = _with_index_engine_health_note(result, health)
        return _ensure_background_index_call_hierarchy_is_non_exhaustive(result)

    def _clangd_config(self) -> ClangdAdapterConfig:
        return ClangdAdapterConfig(
            self.config.compile_commands_dir,
            clangd_path=self.config.clangd_path,
            background_index=self.config.background_index,
            request_timeout=self.config.request_timeout,
            diagnostics_wait=self.config.diagnostics_wait,
        )


def _warm_background_index(
    engine: EngineObservation,
    config: BuildConfig,
    file: str | None = None,
    *,
    timeout: float | None = None,
) -> bool:
    if not config.background_index:
        return False
    warm_file = file or config.warmup_file or _first_existing_tu(config)
    if warm_file is not None and hasattr(engine, "warm_file"):
        getattr(engine, "warm_file")(warm_file)
    probe_symbol = config.index_ready_probe_symbol
    if probe_symbol is None or config.index_ready_probe_path_suffix is None:
        return False
    ready_timeout = config.index_ready_timeout if timeout is None else timeout
    deadline = time.monotonic() + ready_timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        try:
            observation = engine.search_symbol(
                probe_symbol,
                limit=20,
                request_timeout=min(remaining, config.request_timeout),
            )
        except TimeoutError:
            return False
        if _index_ready_probe_matches(observation, probe_symbol, config):
            return True
        sleep_for = min(
            config.index_ready_poll_interval, max(0.0, deadline - time.monotonic())
        )
        if sleep_for > 0:
            time.sleep(sleep_for)


def _warm_references_file(
    engine: EngineObservation,
    config: BuildConfig,
    warmup_file: str | None,
) -> None:
    if not config.background_index:
        return
    if warmup_file is not None and hasattr(engine, "warm_file"):
        getattr(engine, "warm_file")(warmup_file)


def _find_references_with_stable_cross_tu(
    engine: EngineObservation,
    config: BuildConfig,
    symbol: str,
    file: str,
    pos: Pos,
    limit: int,
    offset: int,
) -> tuple[EngineObservationResult, bool]:
    def observe() -> EngineObservationResult:
        return engine.find_references(
            symbol,
            file,
            pos,
            limit=limit,
            offset=offset,
        )

    return _wait_for_stable_cross_tu_observation(
        config,
        observe,
        _references_stability_signature,
        lambda observation: _references_have_cross_tu_evidence(observation, file),
    )


def _find_call_edges_with_stable_cross_tu(
    engine: EngineObservation,
    config: BuildConfig,
    direction: Literal["callers", "callees"],
    symbol: str,
    file: str,
    pos: Pos,
    limit: int,
    offset: int,
) -> tuple[EngineObservationResult, bool]:
    engine_limit = _semantic_search_limit(limit, offset)

    def observe() -> EngineObservationResult:
        return _call_edges_observation(
            engine, direction, symbol, file, pos, limit=engine_limit, offset=0
        )

    observation, ready = _wait_for_stable_cross_tu_observation(
        config,
        observe,
        _call_edges_stability_signature,
        lambda observation: _call_edges_have_cross_tu_evidence(
            observation, file, direction
        ),
    )
    return _slice_call_edges_observation(observation, limit, offset), ready


def _wait_for_stable_cross_tu_observation(
    config: BuildConfig,
    observe: Callable[[], EngineObservationResult],
    signature: Callable[[EngineObservationResult], object],
    has_cross_tu: Callable[[EngineObservationResult], bool],
) -> tuple[EngineObservationResult, bool]:
    observation = observe()
    if not config.background_index:
        return observation, False

    current_signature = signature(observation)
    current_cross_tu = has_cross_tu(observation)
    stable_matches = 0
    deadline = time.monotonic() + config.index_ready_timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return observation, False
        sleep_for = min(config.index_ready_poll_interval, remaining)
        if sleep_for > 0:
            time.sleep(sleep_for)
        next_observation = observe()
        next_signature = signature(next_observation)
        next_cross_tu = has_cross_tu(next_observation)
        if current_cross_tu and next_cross_tu and current_signature == next_signature:
            stable_matches += 1
            if stable_matches >= _STABLE_MATCHES:
                return next_observation, True
        else:
            stable_matches = 0
        observation = next_observation
        current_signature = next_signature
        current_cross_tu = next_cross_tu


def _call_edges_observation(
    engine: EngineObservation,
    direction: Literal["callers", "callees"],
    symbol: str,
    file: str,
    pos: Pos,
    *,
    limit: int,
    offset: int,
) -> EngineObservationResult:
    if direction == "callers":
        return engine.find_callers(symbol, file, pos, limit=limit, offset=offset)
    return engine.find_callees(symbol, file, pos, limit=limit, offset=offset)


def _prewarm_index_ready_timeout(config: BuildConfig) -> float:
    if config.prewarm_index_ready_timeout is not None:
        return config.prewarm_index_ready_timeout
    return max(config.index_ready_timeout, _DEFAULT_PREWARM_INDEX_READY_TIMEOUT)


def _effective_health(
    health: IndexHealth, config: BuildConfig, index_ready: bool
) -> IndexHealth:
    if not config.background_index or not index_ready:
        return IndexHealth.UNKNOWN
    return health


def _effective_index_scope(config: BuildConfig, index_ready: bool) -> IndexScope:
    if not config.background_index or not index_ready:
        return IndexScope.CURRENT_TU
    return config.index_scope


def _health_after_warm(
    health: IndexHealthReport,
    config: BuildConfig,
    index_ready: bool,
    *,
    engine_version: str | None,
) -> IndexHealthReport:
    if config.background_index and index_ready:
        return _index_health(config, engine_version)
    return health


def _exact_symbol_observation(
    observation: EngineObservationResult,
    symbol: str,
    *,
    limit: int,
    offset: int,
) -> tuple[EngineObservationResult, int]:
    exact = tuple(loc for loc in observation.locations if loc.symbol_id.name == symbol)
    return (
        replace(
            observation,
            locations=exact[offset : offset + limit],
        ),
        len(exact),
    )


def _index_ready_probe_matches(
    observation: EngineObservationResult, probe_symbol: str, config: BuildConfig
) -> bool:
    suffix = config.index_ready_probe_path_suffix
    if suffix is None:
        return False
    for location in observation.locations:
        if location.symbol_id.name != probe_symbol:
            continue
        if not location.symbol_id.file.endswith(suffix):
            continue
        return True
    return False


def _reference_warmup_file(config: BuildConfig, query_file: str) -> str | None:
    if config.warmup_file is not None:
        return config.warmup_file
    query_real = str(Path(query_file).resolve())
    suffix = config.index_ready_probe_path_suffix
    for file in _compile_command_files(config.compile_commands_dir):
        file_real = str(Path(file).resolve())
        if file_real == query_real:
            continue
        if suffix is not None and file_real.endswith(suffix):
            continue
        return file_real
    return None


def _references_have_cross_tu_evidence(
    observation: EngineObservationResult, query_file: str
) -> bool:
    query_real = str(Path(query_file).resolve())
    return any(
        str(Path(reference.file).resolve()) != query_real
        for reference in observation.references
    )


def _references_stability_signature(
    observation: EngineObservationResult,
) -> tuple[int | None, tuple[tuple[str, int, int, str], ...]]:
    return (
        observation.total_results,
        tuple(
            (
                str(Path(reference.file).resolve()),
                reference.range.start.line,
                reference.range.start.character,
                reference.kind,
            )
            for reference in observation.references
        ),
    )


def _call_edges_have_cross_tu_evidence(
    observation: EngineObservationResult,
    query_file: str,
    direction: Literal["callers", "callees"],
) -> bool:
    query_real = str(Path(query_file).resolve())
    if direction == "callers":
        return any(
            str(Path(edge.from_symbol.file).resolve()) != query_real
            for edge in observation.call_edges
        )
    return any(
        str(Path(edge.to_symbol.file).resolve()) != query_real
        for edge in observation.call_edges
    )


def _call_edges_stability_signature(
    observation: EngineObservationResult,
) -> tuple[int | None, tuple[tuple[str, int, int, str, str, int, int], ...]]:
    return (
        observation.total_results,
        tuple(_call_edge_signature(edge) for edge in observation.call_edges),
    )


def _call_edge_signature(
    edge: CallEdgeResult,
) -> tuple[str, int, int, str, str, int, int]:
    return (
        str(Path(edge.from_symbol.file).resolve()),
        edge.from_symbol.pos.line,
        edge.from_symbol.pos.character,
        edge.from_symbol.name,
        str(Path(edge.to_symbol.file).resolve()),
        edge.call_site.start.line,
        edge.call_site.start.character,
    )


def _slice_call_edges_observation(
    observation: EngineObservationResult, limit: int, offset: int
) -> EngineObservationResult:
    return replace(
        observation,
        call_edges=observation.call_edges[offset : offset + limit],
    )


def _semantic_search_limit(limit: int, offset: int) -> int:
    return max(100, limit + offset)


def _search_symbol_kind(kind_filter: SymbolKind | None) -> SymbolKind:
    return kind_filter if kind_filter is not None else SymbolKind.UNKNOWN


def _search_window_may_be_truncated(
    observation: EngineObservationResult, engine_limit: int
) -> bool:
    return len(observation.locations) >= engine_limit


def _ensure_background_index_references_are_non_exhaustive(
    result: QueryResult,
) -> QueryResult:
    return _ensure_background_index_results_are_non_exhaustive(result, "references")


def _ensure_background_index_call_hierarchy_is_non_exhaustive(
    result: QueryResult,
) -> QueryResult:
    return _ensure_background_index_results_are_non_exhaustive(result, "call hierarchy")


def _ensure_background_index_results_are_non_exhaustive(
    result: QueryResult, label: str
) -> QueryResult:
    credibilities = (
        [result.status_credibility]
        + [item.credibility for item in result.semantic_results]
        + [candidate.credibility for candidate in result.syntactic_candidates]
    )
    for credibility in credibilities:
        if (
            credibility.index_backend == IndexBackend.BACKGROUND_INDEX
            and credibility.coverage.is_exhaustive_within_scope
        ):
            raise RuntimeError(f"background-index {label} must not assert exhaustive")
    return result


def _index_health(
    config: BuildConfig, engine_version: str | None = None
) -> IndexHealthReport:
    index_dir = index_dir_for_compile_commands_dir(config.compile_commands_dir)
    try:
        cdb = summarize_compile_commands(config.compile_commands_dir)
        shards = scan_index_shards(index_dir)
        return evaluate_index_health(
            cdb,
            shards,
            expected_engine_version=(
                engine_version if config.background_index else None
            ),
            check_engine_ownership=config.background_index,
        )
    except (OSError, ValueError):
        return IndexHealthReport(
            health=IndexHealth.UNKNOWN,
            reason="index_health_error",
            unique_tu_count=0,
            idx_shards=0,
            index_dir=str(index_dir.resolve()),
        )


def _initial_index_health(
    config: BuildConfig, engine_version_probe: EngineVersionProbe
) -> IndexHealthReport:
    engine_version: str | None = None
    if config.background_index:
        try:
            engine_version = engine_version_probe(config.clangd_path)
        except Exception:
            engine_version = None
    return _index_health(config, engine_version)


def _index_engine_blocks_use(health: IndexHealthReport, background_index: bool) -> bool:
    return background_index and health.reason in _INDEX_ENGINE_BLOCKING_REASONS


def _index_guard_unresolved(
    query: QueryMeta,
    health: IndexHealthReport,
    *,
    active_config: ActiveConfig,
    symbol_kind: SymbolKind,
    engine_version: str | None = None,
) -> QueryResult:
    result = route_observation(
        query,
        EngineObservationResult(),
        index_scope=IndexScope.CURRENT_TU,
        index_health=IndexHealth.UNKNOWN,
        index_backend=IndexBackend.BACKGROUND_INDEX,
        active_config=active_config,
        symbol_kind=symbol_kind,
        total_hits=0,
    )
    if engine_version is not None:
        result = validate_query_result(replace(result, engine_version=engine_version))
    return _with_index_engine_health_note(result, health)


def _managed_engine_version(engine: EngineObservation) -> str | None:
    value = getattr(engine, "engine_version", None)
    return value if isinstance(value, str) else None


def _with_index_engine_health_note(
    result: QueryResult, health: IndexHealthReport
) -> QueryResult:
    notes = [Note(note.code, note.detail) for note in result.notes]
    if health.reason == "index_engine_mismatch":
        notes.append(
            Note(
                IssueCode.INDEX_ENGINE_MISMATCH,
                "index built by "
                f"{health.index_engine_version or 'unknown'}; current engine "
                f"{health.expected_engine_version or 'unknown'}",
            )
        )
    elif health.reason in {
        "index_engine_build_in_progress",
        "index_engine_stamp_invalid",
        "index_engine_stamp_write_failed",
        "index_engine_unverified",
        "index_engine_unavailable",
        "index_health_error",
    }:
        details = {
            "index_engine_build_in_progress": (
                "index build in progress; index ownership is temporarily unavailable"
            ),
            "index_engine_stamp_invalid": (
                "index engine stamp invalid or unreadable; index ownership unverified"
            ),
            "index_engine_stamp_write_failed": (
                "index engine stamp write failed; index ownership unverified"
            ),
            "index_engine_unverified": (
                "index engine stamp missing; engine compatibility unverified"
            ),
            "index_engine_unavailable": (
                "current clangd version unavailable; index compatibility unverified"
            ),
            "index_health_error": (
                "index health evaluation failed; index ownership unverified"
            ),
        }
        detail = details[health.reason]
        replaced = False
        for note in notes:
            if note.code == IssueCode.INDEX_UNKNOWN:
                note.detail = detail
                replaced = True
                break
        if not replaced:
            notes.append(Note(IssueCode.INDEX_UNKNOWN, detail))
    return validate_query_result(replace(result, notes=notes))


def _first_existing_tu(config: BuildConfig) -> str | None:
    for file in _compile_command_files(config.compile_commands_dir):
        if Path(file).is_file():
            return file
    return None


def _compile_command_files(path_or_dir: str) -> Iterable[str]:
    cdb_path = Path(path_or_dir)
    if cdb_path.is_dir():
        cdb_path = cdb_path / "compile_commands.json"
    try:
        entries = json.loads(cdb_path.read_text(encoding="utf-8"))
    except Exception:
        return ()
    if not isinstance(entries, list):
        return ()
    files: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict) or "file" not in entry:
            continue
        raw = Path(str(entry["file"]))
        if not raw.is_absolute():
            raw = Path(str(entry.get("directory", cdb_path.parent))) / raw
        files.append(str(raw.resolve()))
    return tuple(files)


def _normalize_kind_filter(kind_filter: str | None) -> SymbolKind | None:
    if kind_filter is None:
        return None
    return _KIND_FILTERS.get(kind_filter.lower())


def _validate_file_pos(file: str, pos: Pos) -> str | None:
    path = Path(file)
    if not path.is_file():
        return "file does not exist"
    if pos.line < 0 or pos.character < 0:
        return "position must be non-negative"
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if pos.line >= len(lines):
        return "line is out of range"
    if pos.character > len(lines[pos.line]):
        return "character is out of range"
    return None


def _invalid_result(query: QueryMeta, detail: str) -> QueryResult:
    return validate_query_result(
        QueryResult(
            query=query,
            status=QueryStatus.INVALID_REQUEST,
            status_credibility=make_error_credibility(QueryKind.ENTITY),
            index_health=IndexHealth.UNKNOWN.value,
            total_hits=None,
            notes=[Note(IssueCode.INVALID_INPUT, detail)],
        )
    )


def _engine_failure(
    query: QueryMeta,
    exc: Exception,
    *,
    engine_version: str | None = None,
) -> QueryResult:
    def raise_observation() -> EngineObservationResult:
        raise exc

    result = route_engine_call(query, raise_observation)
    return validate_query_result(replace(result, engine_version=engine_version))
