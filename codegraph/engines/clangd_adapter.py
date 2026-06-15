"""clangd EngineObservation adapter built on the verified stdlib LSP client."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from importlib import import_module
from typing import Any, Protocol
from urllib.parse import unquote, urlparse

from ..credibility import SymbolKind
from ..types import (
    CallEdgeResult,
    LocationResult,
    Pos,
    Range,
    ReferenceResult,
    SymbolId,
)
from .protocol import EngineDiagnostics, EngineObservationResult

JsonObject = dict[str, Any]
_verify_clangd: Any = import_module("tools.verify_clangd")
LSPClient: Any = _verify_clangd.LSPClient
path_to_uri: Callable[[str], str] = _verify_clangd.path_to_uri


class _Client(Protocol):
    def request(self, method: str, params: dict, timeout: float = 30.0) -> Any: ...

    def notify(self, method: str, params: dict) -> None: ...

    def diagnostics_for(self, uri: str, wait: float = 3.0) -> list: ...

    def shutdown(self) -> None: ...


ClientFactory = Callable[[str, list[str], str, bool], _Client]


@dataclass(frozen=True)
class ClangdAdapterConfig:
    """Configuration for a clangd process serving one compile_commands directory."""

    compile_commands_dir: str
    clangd_path: str = "clangd"
    extra_args: tuple[str, ...] = ()
    request_timeout: float = 30.0
    diagnostics_wait: float = 0.5
    verbose: bool = False


class ClangdAdapter:
    """EngineObservation implementation backed by clangd LSP observations."""

    def __init__(
        self,
        config: ClangdAdapterConfig,
        *,
        client_factory: ClientFactory = LSPClient,
    ):
        self.config = config
        self.compile_dir = _compile_dir(config.compile_commands_dir)
        extra_args = [
            f"--compile-commands-dir={self.compile_dir}",
            *config.extra_args,
        ]
        self._client = client_factory(
            config.clangd_path, extra_args, self.compile_dir, config.verbose
        )
        self._opened: set[str] = set()
        self._initialize()

    def __enter__(self) -> "ClangdAdapter":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.shutdown()

    def search_symbol(
        self,
        symbol: str,
        *,
        kind_filter: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> EngineObservationResult:
        result = self._request("workspace/symbol", {"query": symbol})
        locations = [
            loc
            for loc in (
                _location_result_from_workspace_symbol(item)
                for item in _as_sequence(result)
            )
            if loc is not None and (kind_filter is None or loc.kind == kind_filter)
        ]
        return EngineObservationResult(
            locations=tuple(locations[offset : offset + limit])
        )

    def get_definition(
        self,
        symbol: str,
        file: str,
        pos: Pos,
    ) -> EngineObservationResult:
        uri = self._open_document(file)
        result = self._request(
            "textDocument/definition",
            {
                "textDocument": {"uri": uri},
                "position": _lsp_pos(pos),
            },
        )
        locations = tuple(_location_results(result, fallback_name=symbol))
        return EngineObservationResult(
            diagnostics=self._diagnostics(uri),
            locations=locations,
            symbol_ambiguous=len(locations) > 1,
        )

    def find_references(
        self,
        symbol: str,
        file: str,
        pos: Pos,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> EngineObservationResult:
        uri = self._open_document(file)
        result = self._request(
            "textDocument/references",
            {
                "textDocument": {"uri": uri},
                "position": _lsp_pos(pos),
                "context": {"includeDeclaration": True},
            },
        )
        refs = _reference_results(result)
        return EngineObservationResult(
            diagnostics=self._diagnostics(uri),
            references=tuple(refs[offset : offset + limit]),
        )

    def find_callers(
        self,
        symbol: str,
        file: str,
        pos: Pos,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> EngineObservationResult:
        uri = self._open_document(file)
        roots = self._prepare_call_hierarchy(uri, pos)
        edges: list[CallEdgeResult] = []
        for root in roots:
            calls = self._call_hierarchy_request(
                "callHierarchy/incomingCalls", {"item": root}
            )
            for call in _as_sequence(calls):
                caller = _symbol_from_call_item(call.get("from", {}))
                callee = _symbol_from_call_item(root, fallback_name=symbol)
                for call_range in call.get("fromRanges", ()) or ():
                    edges.append(CallEdgeResult(caller, callee, _range(call_range)))
        return EngineObservationResult(
            diagnostics=self._diagnostics(uri),
            call_edges=tuple(edges[offset : offset + limit]),
            symbol_ambiguous=len(roots) > 1,
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
        uri = self._open_document(file)
        roots = self._prepare_call_hierarchy(uri, pos)
        edges: list[CallEdgeResult] = []
        for root in roots:
            calls = self._call_hierarchy_request(
                "callHierarchy/outgoingCalls", {"item": root}
            )
            for call in _as_sequence(calls):
                caller = _symbol_from_call_item(root, fallback_name=symbol)
                callee = _symbol_from_call_item(call.get("to", {}))
                for call_range in call.get("fromRanges", ()) or ():
                    edges.append(CallEdgeResult(caller, callee, _range(call_range)))
        return EngineObservationResult(
            diagnostics=self._diagnostics(uri),
            call_edges=tuple(edges[offset : offset + limit]),
            symbol_ambiguous=len(roots) > 1,
        )

    def _initialize(self) -> None:
        self._request(
            "initialize",
            {
                "processId": os.getpid(),
                "rootUri": path_to_uri(self.compile_dir),
                "capabilities": {
                    "workspace": {"symbol": {}},
                    "textDocument": {
                        "definition": {},
                        "references": {},
                        "callHierarchy": {"dynamicRegistration": False},
                    },
                },
            },
        )
        self._client.notify("initialized", {})

    def _open_document(self, file: str) -> str:
        path = os.path.abspath(file)
        uri = path_to_uri(path)
        if uri in self._opened:
            return uri
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        self._client.notify(
            "textDocument/didOpen",
            {
                "textDocument": {
                    "uri": uri,
                    "languageId": _language_id(path),
                    "version": 1,
                    "text": text,
                }
            },
        )
        self._opened.add(uri)
        return uri

    def _request(self, method: str, params: dict) -> Any:
        return self._client.request(method, params, timeout=self.config.request_timeout)

    def _prepare_call_hierarchy(self, uri: str, pos: Pos) -> list[JsonObject]:
        result = self._call_hierarchy_request(
            "textDocument/prepareCallHierarchy",
            {
                "textDocument": {"uri": uri},
                "position": _lsp_pos(pos),
            },
        )
        return [item for item in _as_sequence(result) if isinstance(item, dict)]

    def _call_hierarchy_request(self, method: str, params: dict) -> Any:
        try:
            return self._request(method, params)
        except RuntimeError as exc:
            if _looks_unsupported(exc):
                raise NotImplementedError("clangd callHierarchy unsupported") from exc
            raise

    def _diagnostics(self, uri: str) -> EngineDiagnostics:
        return _diagnostics_from_lsp(
            self._client.diagnostics_for(uri, wait=self.config.diagnostics_wait)
        )


def _compile_dir(cdb_path: str) -> str:
    path = os.path.abspath(cdb_path)
    return path if os.path.isdir(path) else os.path.dirname(path)


def _language_id(file: str) -> str:
    return "cpp" if file.endswith((".cc", ".cpp", ".cxx", ".hpp", ".hh")) else "c"


def _lsp_pos(pos: Pos) -> dict[str, int]:
    return {"line": pos.line, "character": pos.character}


def _pos(data: JsonObject) -> Pos:
    return Pos(int(data.get("line", 0)), int(data.get("character", 0)))


def _range(data: JsonObject) -> Range:
    return Range(_pos(data["start"]), _pos(data["end"]))


def _as_sequence(result: Any) -> list[JsonObject]:
    if result is None:
        return []
    if isinstance(result, list):
        return [item for item in result if isinstance(item, dict)]
    if isinstance(result, dict):
        return [result]
    return []


def _location_results(result: Any, *, fallback_name: str) -> list[LocationResult]:
    return [
        loc
        for loc in (
            _location_result_from_location(item, fallback_name=fallback_name)
            for item in _as_sequence(result)
        )
        if loc is not None
    ]


def _reference_results(result: Any) -> list[ReferenceResult]:
    return [
        ref
        for ref in (
            _reference_result_from_location(item) for item in _as_sequence(result)
        )
        if ref is not None
    ]


def _location_result_from_workspace_symbol(
    item: JsonObject,
) -> LocationResult | None:
    location = item.get("location")
    if not isinstance(location, dict):
        return None
    return _location_result_from_location(
        location,
        fallback_name=str(item.get("name", "")),
        kind=_symbol_kind(item.get("kind")),
    )


def _location_result_from_location(
    item: JsonObject,
    *,
    fallback_name: str,
    kind: str = SymbolKind.UNKNOWN.value,
) -> LocationResult | None:
    uri = item.get("targetUri") or item.get("uri")
    raw_range = item.get("targetSelectionRange") or item.get("range")
    if not isinstance(uri, str) or not isinstance(raw_range, dict):
        return None
    location_range = _range(raw_range)
    return LocationResult(
        SymbolId(None, fallback_name, _uri_to_path(uri), location_range.start),
        location_range,
        kind,
    )


def _reference_result_from_location(item: JsonObject) -> ReferenceResult | None:
    uri = item.get("targetUri") or item.get("uri")
    raw_range = item.get("targetSelectionRange") or item.get("range")
    if not isinstance(uri, str) or not isinstance(raw_range, dict):
        return None
    return ReferenceResult(_range(raw_range), _uri_to_path(uri), "reference")


def _symbol_from_call_item(
    item: JsonObject, *, fallback_name: str | None = None
) -> SymbolId:
    uri = str(item.get("uri", ""))
    raw_range = item.get("selectionRange") or item.get("range")
    pos = _range(raw_range).start if isinstance(raw_range, dict) else Pos(0, 0)
    return SymbolId(
        None,
        str(item.get("name") or fallback_name or ""),
        _uri_to_path(uri) if uri else "",
        pos,
    )


def _uri_to_path(uri: str) -> str:
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        return uri
    return unquote(parsed.path)


def _symbol_kind(kind: Any) -> str:
    if kind in (6, 9, 12):
        return SymbolKind.ORDINARY_FUNCTION.value
    if kind in (7, 8, 13, 14, 22):
        return SymbolKind.ORDINARY_VARIABLE.value
    if kind in (5, 10, 11, 23, 26):
        return SymbolKind.TYPE.value
    return SymbolKind.UNKNOWN.value


def _diagnostics_from_lsp(diagnostics: Iterable[JsonObject]) -> EngineDiagnostics:
    file_not_found: list[str] = []
    fatal: list[str] = []
    soft: list[str] = []
    for diagnostic in diagnostics:
        message = str(diagnostic.get("message", ""))
        severity = diagnostic.get("severity")
        if severity == 1 and _is_include_not_found(message):
            file_not_found.append(message)
        elif severity == 1:
            fatal.append(message)
        elif message:
            soft.append(message)
    return EngineDiagnostics(
        file_not_found=tuple(file_not_found),
        fatal=tuple(fatal),
        soft=tuple(soft),
    )


def _is_include_not_found(message: str) -> bool:
    lower = message.lower()
    return "file not found" in lower or ("'" in message and "not found" in lower)


def _looks_unsupported(exc: RuntimeError) -> bool:
    text = str(exc).lower()
    return (
        "methodnotfound" in text or "method not found" in text or "unsupported" in text
    )
