"""Public CodeGraph library API for search and definition queries."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, replace
from pathlib import Path
from types import TracebackType
from typing import Callable, Iterable, Protocol

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
from .factories import make_error_credibility
from .indexing import (
    evaluate_index_health,
    index_dir_for_compile_commands_dir,
    scan_index_shards,
    summarize_compile_commands,
)
from .routing import route_engine_call, route_observation, validate_query_result
from .types import IssueCode, Note, Pos, QueryMeta, QueryResult, QueryStatus

_KIND_FILTERS = {
    "function": SymbolKind.ORDINARY_FUNCTION,
    "variable": SymbolKind.ORDINARY_VARIABLE,
    "type": SymbolKind.TYPE,
    "macro": SymbolKind.MACRO,
}
_DEFAULT_PREWARM_INDEX_READY_TIMEOUT = 30.0


@dataclass(frozen=True)
class BuildConfig:
    """One CodeGraph build/index configuration."""

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


class CodeGraph:
    """Thin P6 API facade that wires P3/P4/P5 into the P2 router."""

    def __init__(
        self,
        config: BuildConfig,
        *,
        engine_factory: Callable[[ClangdAdapterConfig], ManagedEngine] | None = None,
    ):
        self.config = config
        self._engine_factory = engine_factory or (lambda cfg: ClangdAdapter(cfg))

    def prewarm(self, file: str | None = None) -> bool:
        """Warm clangd/index caches; each user query still proves readiness itself."""

        try:
            with self._engine_factory(self._clangd_config()) as engine:
                return _warm_background_index(
                    engine,
                    self.config,
                    file,
                    timeout=_prewarm_index_ready_timeout(self.config),
                )
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
        health = _index_health(self.config)
        try:
            with self._engine_factory(self._clangd_config()) as engine:
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
            return _engine_failure(query, exc)
        health = _health_after_warm(health, self.config, ready)
        observation, total_hits = _exact_symbol_observation(
            observation, symbol, limit=limit, offset=offset
        )
        ready_for_negative_proof = ready and not (
            search_window_may_be_truncated and total_hits == 0
        )
        return route_observation(
            query,
            observation,
            syntactic_provider=provider,
            kind_filter=kind.value if kind is not None else None,
            limit=limit,
            offset=offset,
            index_scope=_effective_index_scope(self.config, ready_for_negative_proof),
            index_health=_effective_health(
                health, self.config, ready_for_negative_proof
            ),
            index_backend=IndexBackend.BACKGROUND_INDEX,
            active_config=self.config.active_config,
            symbol_kind=kind or SymbolKind.ORDINARY_FUNCTION,
            total_hits=total_hits,
        )

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
        health = _index_health(self.config)
        try:
            with self._engine_factory(self._clangd_config()) as engine:
                ready = _warm_background_index(engine, self.config, real_file)
                observation = engine.get_definition(symbol, real_file, pos)
        except Exception as exc:  # noqa: BLE001 - API reports engine failures.
            return _engine_failure(query, exc)
        health = _health_after_warm(health, self.config, ready)
        return route_observation(
            query,
            observation,
            syntactic_provider=provider,
            allow_syntactic_fallback=allow_syntactic_fallback,
            index_scope=_effective_index_scope(self.config, ready),
            index_health=_effective_health(health, self.config, ready),
            index_backend=IndexBackend.BACKGROUND_INDEX,
            active_config=self.config.active_config,
            symbol_kind=SymbolKind.ORDINARY_FUNCTION,
            total_hits=len(observation.locations),
        )

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
    health: IndexHealth, config: BuildConfig, index_ready: bool
) -> IndexHealth:
    if config.background_index and index_ready:
        return _index_health(config)
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


def _semantic_search_limit(limit: int, offset: int) -> int:
    return max(100, limit + offset)


def _search_window_may_be_truncated(
    observation: EngineObservationResult, engine_limit: int
) -> bool:
    return len(observation.locations) >= engine_limit


def _index_health(config: BuildConfig) -> IndexHealth:
    try:
        cdb = summarize_compile_commands(config.compile_commands_dir)
        shards = scan_index_shards(
            index_dir_for_compile_commands_dir(config.compile_commands_dir)
        )
        return evaluate_index_health(cdb, shards).health
    except Exception:
        return IndexHealth.UNKNOWN


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


def _engine_failure(query: QueryMeta, exc: Exception) -> QueryResult:
    def raise_observation() -> EngineObservationResult:
        raise exc

    return route_engine_call(query, raise_observation)
