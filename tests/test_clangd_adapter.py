from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from codegraph.engines.clangd_adapter import (
    ClangdAdapter,
    ClangdAdapterConfig,
    _as_sequence,
    _diagnostics_from_lsp,
    _location_result_from_location,
    _location_result_from_workspace_symbol,
    _reference_result_from_location,
    _symbol_kind,
    _uri_to_path,
)
from codegraph.engines.protocol import EngineObservationResult
from codegraph.routing import route_observation
from codegraph.types import (
    IssueCode,
    LocationResult,
    Pos,
    QueryMeta,
    QueryStatus,
    ReferenceResult,
)
from tools.verify_clangd import path_to_uri


class FakeClient:
    def __init__(
        self,
        responses: dict[str, list[Any]] | None = None,
        diagnostics: dict[str, list[dict[str, Any]]] | None = None,
    ):
        self.responses = responses or {}
        self.diagnostics = diagnostics or {}
        self.requests: list[tuple[str, dict, float]] = []
        self.notifications: list[tuple[str, dict]] = []
        self.shutdown_called = False
        self.shutdown_error: Exception | None = None

    def request(self, method: str, params: dict, timeout: float = 30.0) -> Any:
        self.requests.append((method, params, timeout))
        queue = self.responses.setdefault(method, [None])
        response = queue.pop(0) if queue else None
        if isinstance(response, BaseException):
            raise response
        return response

    def notify(self, method: str, params: dict) -> None:
        self.notifications.append((method, params))

    def diagnostics_for(self, uri: str, wait: float = 3.0) -> list[dict[str, Any]]:
        return self.diagnostics.get(uri, [])

    def shutdown(self) -> None:
        self.shutdown_called = True
        if self.shutdown_error is not None:
            raise self.shutdown_error


def source_file(tmp_path: Path) -> Path:
    src = tmp_path / "sample.c"
    src.write_text(
        "\n".join(
            [
                "int add(int x) {",
                "  return x + 1;",
                "}",
                "",
                "int caller(void) {",
                "  return add(1);",
                "}",
                "",
                "int main(void) {",
                "  return caller();",
                "}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return src


def write_cdb(tmp_path: Path, src: Path) -> None:
    (tmp_path / "compile_commands.json").write_text(
        json.dumps(
            [
                {
                    "directory": str(tmp_path),
                    "command": f"/usr/bin/cc -I{tmp_path} -c {src}",
                    "file": str(src),
                }
            ]
        ),
        encoding="utf-8",
    )


def make_adapter(fake: FakeClient, tmp_path: Path) -> ClangdAdapter:
    return ClangdAdapter(
        ClangdAdapterConfig(str(tmp_path), request_timeout=2.5, diagnostics_wait=0),
        client_factory=lambda *_args: fake,
    )


def test_background_index_flag_is_opt_in(tmp_path: Path):
    calls: list[tuple[str, list[str], str, bool, bool]] = []

    def factory(
        clangd_path: str,
        extra_args: list[str],
        cwd: str,
        verbose: bool,
        background_index: bool,
    ) -> FakeClient:
        calls.append((clangd_path, extra_args, cwd, verbose, background_index))
        return FakeClient({"initialize": [{}]})

    ClangdAdapter(ClangdAdapterConfig(str(tmp_path)), client_factory=factory).close()
    ClangdAdapter(
        ClangdAdapterConfig(str(tmp_path), background_index=True),
        client_factory=factory,
    ).close()

    assert calls[0][4] is False
    assert calls[1][4] is True


def test_config_positional_extra_args_keep_background_default(tmp_path: Path):
    config = ClangdAdapterConfig(str(tmp_path), "clangd-custom", ("--flag",))

    assert config.clangd_path == "clangd-custom"
    assert config.extra_args == ("--flag",)
    assert config.background_index is False


def test_config_rejects_positional_background_index_misbind(tmp_path: Path):
    with pytest.raises(TypeError, match="extra_args"):
        ClangdAdapterConfig(str(tmp_path), "clangd-custom", True)  # type: ignore[arg-type]


def lsp_range(
    start_line: int, start_char: int, end_line: int, end_char: int
) -> dict[str, dict[str, int]]:
    return {
        "start": {"line": start_line, "character": start_char},
        "end": {"line": end_line, "character": end_char},
    }


def location(uri: str, line: int, start: int, end: int) -> dict[str, Any]:
    return {"uri": uri, "range": lsp_range(line, start, line, end)}


def call_item(name: str, uri: str, line: int, start: int, end: int) -> dict[str, Any]:
    return {
        "name": name,
        "uri": uri,
        "range": lsp_range(line, start, line, end),
        "selectionRange": lsp_range(line, start, line, end),
    }


def request_methods(fake: FakeClient) -> list[str]:
    return [method for method, _params, _timeout in fake.requests]


def test_empty_definition_is_only_an_empty_observation(tmp_path: Path):
    src = source_file(tmp_path)
    fake = FakeClient({"initialize": [{}], "textDocument/definition": [[]]})
    adapter = make_adapter(fake, tmp_path)

    result = adapter.get_definition("missing", str(src), Pos(5, 9))

    assert isinstance(result, EngineObservationResult)
    assert result.locations == ()
    assert result.references == ()
    assert result.call_edges == ()
    assert result.diagnostics.file_not_found == ()
    assert result.index_scope_known is True
    assert not hasattr(result, "status")


def test_init_failure_shuts_down_started_client(tmp_path: Path):
    fake = FakeClient({"initialize": [TimeoutError("init timeout")]})

    with pytest.raises(TimeoutError, match="init timeout"):
        make_adapter(fake, tmp_path)

    assert fake.shutdown_called is True

    noisy_shutdown = FakeClient({"initialize": [TimeoutError("init timeout")]})
    noisy_shutdown.shutdown_error = RuntimeError("shutdown failed")
    with pytest.raises(TimeoutError, match="init timeout"):
        make_adapter(noisy_shutdown, tmp_path)
    assert noisy_shutdown.shutdown_called is True

    interrupted = FakeClient({"initialize": [KeyboardInterrupt()]})
    with pytest.raises(KeyboardInterrupt):
        make_adapter(interrupted, tmp_path)
    assert interrupted.shutdown_called is True


def test_definition_conversion_and_diagnostics_match_p2_contract(tmp_path: Path):
    src = source_file(tmp_path)
    uri = path_to_uri(str(src))
    fake = FakeClient(
        {
            "initialize": [{}],
            "textDocument/definition": [[location(uri, 0, 4, 7)]],
        },
        diagnostics={
            uri: [
                {"severity": 1, "message": "'missing.h' file not found"},
                {"severity": 2, "message": "unused variable"},
            ]
        },
    )
    adapter = make_adapter(fake, tmp_path)

    result = adapter.get_definition("add", str(src), Pos(5, 9))

    assert result.diagnostics.file_not_found == ("'missing.h' file not found",)
    assert result.diagnostics.soft == ("unused variable",)
    assert result.diagnostics.fatal == ()
    assert len(result.locations) == 1
    loc = result.locations[0]
    assert isinstance(loc, LocationResult)
    assert loc.symbol_id.name == "add"
    assert loc.symbol_id.file == str(src)
    assert loc.symbol_id.pos == Pos(0, 4)


def test_adapter_observation_routes_through_p2_dependency_incomplete(tmp_path: Path):
    src = source_file(tmp_path)
    uri = path_to_uri(str(src))
    fake = FakeClient(
        {
            "initialize": [{}],
            "textDocument/definition": [[location(uri, 0, 4, 7)]],
        },
        diagnostics={uri: [{"severity": 1, "message": "'missing.h' file not found"}]},
    )
    adapter = make_adapter(fake, tmp_path)
    observation = adapter.get_definition("add", str(src), Pos(5, 9))

    routed = route_observation(QueryMeta("entity", "add", "arm"), observation)

    assert routed.status == QueryStatus.UNRESOLVED
    assert routed.semantic_results == []
    assert len(routed.syntactic_candidates) == 1
    assert IssueCode.DEPENDENCY_INCOMPLETE in {note.code for note in routed.notes}


def test_search_symbol_and_references_mapping(tmp_path: Path):
    src = source_file(tmp_path)
    uri = path_to_uri(str(src))
    fake = FakeClient(
        {
            "initialize": [{}],
            "workspace/symbol": [
                [
                    {"name": "add", "kind": 12, "location": location(uri, 0, 4, 7)},
                    {"name": "value", "kind": 13, "location": location(uri, 1, 9, 14)},
                ]
            ],
            "textDocument/references": [
                [
                    location(uri, 0, 4, 7),
                    location(uri, 5, 9, 12),
                    location(uri, 9, 9, 15),
                ]
            ],
        }
    )
    adapter = make_adapter(fake, tmp_path)

    symbols = adapter.search_symbol("add", kind_filter="ordinary_function")
    refs = adapter.find_references("add", str(src), Pos(0, 4), limit=1, offset=1)

    assert [loc.symbol_id.name for loc in symbols.locations] == ["add"]
    assert symbols.locations[0].kind == "ordinary_function"
    assert len(refs.references) == 1
    assert refs.total_results == 3
    assert isinstance(refs.references[0], ReferenceResult)
    assert refs.references[0].range.start == Pos(5, 9)


def test_call_hierarchy_uses_lsp_and_preserves_direction(tmp_path: Path):
    src = source_file(tmp_path)
    uri = path_to_uri(str(src))
    callee = call_item("add", uri, 0, 4, 7)
    caller = call_item("caller", uri, 4, 4, 10)
    fake = FakeClient(
        {
            "initialize": [{}],
            "textDocument/prepareCallHierarchy": [[callee], [caller]],
            "callHierarchy/incomingCalls": [
                [{"from": caller, "fromRanges": [lsp_range(5, 9, 5, 12)]}]
            ],
            "callHierarchy/outgoingCalls": [
                [{"to": callee, "fromRanges": [lsp_range(5, 9, 5, 12)]}]
            ],
        }
    )
    adapter = make_adapter(fake, tmp_path)

    callers = adapter.find_callers("add", str(src), Pos(0, 4))
    callees = adapter.find_callees("caller", str(src), Pos(4, 4))

    assert "textDocument/references" not in request_methods(fake)
    caller_edge = callers.call_edges[0]
    assert caller_edge.from_symbol.name == "caller"
    assert caller_edge.to_symbol.name == "add"
    assert caller_edge.call_site.start == Pos(5, 9)
    callee_edge = callees.call_edges[0]
    assert callee_edge.from_symbol.name == "caller"
    assert callee_edge.to_symbol.name == "add"
    assert callee_edge.call_site.start == Pos(5, 9)
    assert "callHierarchy/incomingCalls" in request_methods(fake)
    assert "callHierarchy/outgoingCalls" in request_methods(fake)


def test_call_hierarchy_unsupported_and_timeout_propagate(tmp_path: Path):
    src = source_file(tmp_path)
    fake_unsupported = FakeClient(
        {
            "initialize": [{}],
            "textDocument/prepareCallHierarchy": [
                RuntimeError("MethodNotFound: callHierarchy")
            ],
        }
    )
    adapter = make_adapter(fake_unsupported, tmp_path)
    with pytest.raises(NotImplementedError):
        adapter.find_callers("add", str(src), Pos(0, 4))

    fake_timeout = FakeClient(
        {
            "initialize": [{}],
            "textDocument/definition": [TimeoutError("definition timeout")],
        }
    )
    adapter = make_adapter(fake_timeout, tmp_path)
    with pytest.raises(TimeoutError):
        adapter.get_definition("add", str(src), Pos(5, 9))


def test_call_hierarchy_runtime_error_is_not_mislabeled_unsupported(tmp_path: Path):
    src = source_file(tmp_path)
    fake = FakeClient(
        {
            "initialize": [{}],
            "textDocument/prepareCallHierarchy": [RuntimeError("clangd crashed")],
        }
    )
    adapter = make_adapter(fake, tmp_path)

    with pytest.raises(RuntimeError, match="clangd crashed"):
        adapter.find_callers("add", str(src), Pos(0, 4))


def test_lsp_conversion_helpers_ignore_malformed_shapes():
    assert _as_sequence(None) == []
    assert _as_sequence({"uri": "file:///tmp/a.c"}) == [{"uri": "file:///tmp/a.c"}]
    assert _as_sequence("bad") == []
    assert _location_result_from_workspace_symbol({"name": "bad"}) is None
    assert (
        _location_result_from_location({"uri": "file:///tmp/a.c"}, fallback_name="bad")
        is None
    )
    assert _reference_result_from_location({"range": lsp_range(0, 0, 0, 1)}) is None
    assert _uri_to_path("memory://scratch") == "memory://scratch"
    assert _symbol_kind(23) == "type"
    assert _symbol_kind(999) == "unknown"

    diagnostics = _diagnostics_from_lsp(
        [
            {"severity": 1, "message": "parse failed"},
            {"severity": 2, "message": ""},
        ]
    )
    assert diagnostics.fatal == ("parse failed",)
    assert diagnostics.file_not_found == ()
    assert diagnostics.soft == ()


@pytest.mark.skipif(shutil.which("clangd") is None, reason="clangd unavailable")
def test_real_clangd_small_cdb_definition_references_call_hierarchy(tmp_path: Path):
    src = source_file(tmp_path)
    write_cdb(tmp_path, src)
    lines = src.read_text(encoding="utf-8").splitlines()
    add_def = Pos(0, lines[0].index("add"))
    add_call = Pos(5, lines[5].index("add"))

    with ClangdAdapter(
        ClangdAdapterConfig(str(tmp_path), request_timeout=15, diagnostics_wait=0.5)
    ) as adapter:
        definition = adapter.get_definition("add", str(src), add_call)
        references = adapter.find_references("add", str(src), add_def)
        callers = adapter.find_callers("add", str(src), add_def)

    assert definition.locations
    assert any(loc.symbol_id.file == str(src) for loc in definition.locations)
    assert len(references.references) >= 2
    assert any(
        edge.from_symbol.name == "caller" and edge.to_symbol.name == "add"
        for edge in callers.call_edges
    )
