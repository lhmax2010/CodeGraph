from __future__ import annotations

import asyncio
import json
import os
import sys
from dataclasses import fields, is_dataclass, replace
from enum import Enum
from pathlib import Path
from typing import Any

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.server.fastmcp.exceptions import ToolError

import codegraph.api as codegraph_api
import codegraph.mcp_server as mcp_module
from codegraph.api import BuildConfig
from codegraph.credibility import (
    ActiveConfig,
    Coverage,
    DependencyScope,
    IndexHealth,
    IndexScope,
    NegativeScope,
    QueryKind,
    SymbolKind,
)
from codegraph.factories import (
    clangd_entity_resolved,
    clangd_relation_must,
    make_error_credibility,
    treesitter_entity_resolved,
    treesitter_relation_may,
)
from codegraph.mcp_server import (
    _NOT_EVIDENCE_WARNING,
    _ToolHandlers,
    create_mcp_server,
    load_startup_config,
    main,
    query_result_to_json,
)
from codegraph.types import (
    CallEdgeResult,
    Candidate,
    IssueCode,
    LocationResult,
    Note,
    Pos,
    QueryMeta,
    QueryResult,
    QueryStatus,
    Range,
    ReferenceResult,
    Result,
    SymbolId,
)


def _range(line: int = 4, character: int = 2) -> Range:
    return Range(Pos(line, character), Pos(line, character + 3))


def _symbol(name: str, file: str) -> SymbolId:
    return SymbolId(f"usr:{name}", name, file, Pos(4, 2))


def _entity_credibility() -> Any:
    return replace(
        clangd_entity_resolved(
            DependencyScope.complete(),
            build_config_id="arm",
            coverage=Coverage(
                index_scope=IndexScope.INDEXED_PROJECT,
                is_exhaustive_within_scope=False,
                negative_scope=NegativeScope.NONE,
            ),
            active_config=ActiveConfig.TARGET,
            symbol_kind=SymbolKind.ORDINARY_FUNCTION,
            index_health=IndexHealth.COMPLETE,
        ),
        consumer_hint={"labels": ["reviewed"], "score": 0.75},
    )


def _relation_credibility() -> Any:
    return replace(
        clangd_relation_must(
            DependencyScope.complete(),
            build_config_id="arm",
            coverage=Coverage(index_scope=IndexScope.INDEXED_PROJECT),
            active_config=ActiveConfig.TARGET,
            symbol_kind=SymbolKind.ORDINARY_FUNCTION,
            index_health=IndexHealth.COMPLETE,
        ),
        consumer_hint={"origin": "test"},
    )


def _location(file: str = "/usr/include/example.h") -> LocationResult:
    return LocationResult(_symbol("needle", file), _range(), "function")


def _reference(file: str = "/project/needle.c") -> ReferenceResult:
    return ReferenceResult(_range(), file, "reference")


def _call_edge(file: str = "/project/caller.c") -> CallEdgeResult:
    return CallEdgeResult(
        _symbol("caller", file),
        _symbol("needle", "/project/needle.c"),
        _range(),
    )


def _ok_result(data: object) -> QueryResult:
    relation = isinstance(data, CallEdgeResult)
    credibility = _relation_credibility() if relation else _entity_credibility()
    candidate_credibility = replace(
        treesitter_relation_may() if relation else treesitter_entity_resolved(),
        build_config_id="arm",
        consumer_hint={"candidate": True},
    )
    return QueryResult(
        query=QueryMeta(
            "relation" if relation else "entity",
            "needle",
            "arm",
            "/project/needle.c",
            Pos(4, 2),
        ),
        status=QueryStatus.OK,
        status_credibility=credibility,
        semantic_results=[Result(data, credibility)],  # type: ignore[arg-type]
        syntactic_candidates=[
            Candidate(data, candidate_credibility, 20, "not_evidence")  # type: ignore[arg-type]
        ],
        index_health="complete",
        total_hits=389,
        notes=[Note(IssueCode.SOFT_WARNING, "kept verbatim")],
        engine_version="clangd 21.1.1",
    )


def _status_result(status: QueryStatus) -> QueryResult:
    if status is QueryStatus.OK:
        return _ok_result(_location())
    credibility = replace(
        make_error_credibility(QueryKind.ENTITY), build_config_id="arm"
    )
    candidates = []
    if status is QueryStatus.UNRESOLVED:
        candidate_credibility = replace(
            treesitter_entity_resolved(), build_config_id="arm"
        )
        candidates = [Candidate(_location(), candidate_credibility, 15)]
    return QueryResult(
        query=QueryMeta("entity", "needle", "arm"),
        status=status,
        status_credibility=credibility,
        syntactic_candidates=candidates,
        index_health="unknown",
        total_hits=None,
        notes=[Note(IssueCode.ENGINE_UNAVAILABLE, status.value)],
        engine_version="clangd 18.1.3" if status is QueryStatus.FAILED else None,
    )


def _assert_preserved(original: object, decoded: object) -> None:
    if isinstance(original, Enum):
        assert decoded == original.value
        return
    if is_dataclass(original) and not isinstance(original, type):
        assert isinstance(decoded, dict)
        assert set(decoded) == {field.name for field in fields(original)}
        for field in fields(original):
            _assert_preserved(getattr(original, field.name), decoded[field.name])
        return
    if isinstance(original, (list, tuple)):
        assert isinstance(decoded, list)
        assert len(original) == len(decoded)
        for source_item, decoded_item in zip(original, decoded, strict=True):
            _assert_preserved(source_item, decoded_item)
        return
    if isinstance(original, dict):
        assert isinstance(decoded, dict)
        assert set(original) == set(decoded)
        for key, item in original.items():
            _assert_preserved(item, decoded[key])
        return
    assert decoded == original


@pytest.mark.parametrize(
    "status",
    [
        QueryStatus.OK,
        QueryStatus.NOT_FOUND,
        QueryStatus.UNRESOLVED,
        QueryStatus.FAILED,
        QueryStatus.INVALID_REQUEST,
    ],
)
def test_query_result_serialization_preserves_every_status_field(
    status: QueryStatus,
) -> None:
    result = _status_result(status)
    encoded = query_result_to_json(result)
    decoded = json.loads(json.dumps(encoded, ensure_ascii=False))

    _assert_preserved(result, decoded)


@pytest.mark.parametrize("data", [_location(), _reference(), _call_edge()])
def test_query_result_serialization_preserves_every_result_shape(data: object) -> None:
    result = _ok_result(data)
    decoded = json.loads(json.dumps(query_result_to_json(result), ensure_ascii=False))

    _assert_preserved(result, decoded)
    assert decoded["syntactic_candidates"][0]["consumer_warning"] == "not_evidence"
    assert decoded["engine_version"] == "clangd 21.1.1"
    assert decoded["total_hits"] == 389


def test_query_result_serialization_fails_loud_on_unknown_type() -> None:
    result = _ok_result(_location())
    result.status_credibility = replace(
        result.status_credibility, consumer_hint={"bad": object()}
    )

    with pytest.raises(TypeError, match="object"):
        query_result_to_json(result)


def test_query_result_serialization_supports_declared_pathlike_values() -> None:
    result = _ok_result(_reference())
    result.semantic_results[0].data.file = Path("/project/pathlike.c")  # type: ignore[union-attr,assignment]

    encoded = query_result_to_json(result)

    assert encoded["semantic_results"][0]["data"]["file"] == ("/project/pathlike.c")


@pytest.mark.parametrize("bad", [{1: "value"}, {"value": float("nan")}])
def test_query_result_serialization_rejects_non_json_consumer_hint(
    bad: dict[object, object],
) -> None:
    result = _ok_result(_location())
    result.status_credibility = replace(result.status_credibility, consumer_hint=bad)

    with pytest.raises(TypeError):
        query_result_to_json(result)


def test_tool_mapping_is_exact_and_hides_build_config_id(tmp_path: Path) -> None:
    server = create_mcp_server(
        BuildConfig("arm", str(tmp_path)), allowed_read_roots=[str(tmp_path)]
    )
    tools = asyncio.run(server.list_tools())

    assert {tool.name for tool in tools} == {
        "search",
        "definition",
        "references",
        "callers",
        "callees",
    }
    for tool in tools:
        assert _NOT_EVIDENCE_WARNING in (tool.description or "")
        assert "build_config_id" not in tool.inputSchema.get("properties", {})
        assert tool.inputSchema["additionalProperties"] is False
        assert tool.inputSchema["properties"]["symbol"]["type"] == "string"
        assert tool.inputSchema["properties"]["symbol"]["maxLength"] == 512
    search_schema = next(tool for tool in tools if tool.name == "search").inputSchema
    assert search_schema["properties"]["limit"] == {
        "default": 100,
        "maximum": 1000,
        "minimum": 1,
        "title": "Limit",
        "type": "integer",
    }
    definition_schema = next(
        tool for tool in tools if tool.name == "definition"
    ).inputSchema
    assert definition_schema["properties"]["pos"]["additionalProperties"] is False
    assert definition_schema["properties"]["allow_syntactic_fallback"]["type"] == (
        "boolean"
    )


def test_handlers_inject_config_and_do_not_filter_output_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "query.c"
    source.write_text("int needle(void);\n", encoding="utf-8")
    calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []
    result = _ok_result(_location("/usr/include/external.h"))

    def fake(name: str):
        def call(*args: object, **kwargs: object) -> QueryResult:
            calls.append((name, args, kwargs))
            return result

        return call

    monkeypatch.setattr(codegraph_api, "search_symbol", fake("search"))
    monkeypatch.setattr(codegraph_api, "get_definition", fake("definition"))
    monkeypatch.setattr(codegraph_api, "find_references", fake("references"))
    monkeypatch.setattr(codegraph_api, "find_callers", fake("callers"))
    monkeypatch.setattr(codegraph_api, "find_callees", fake("callees"))
    handlers = _ToolHandlers("arm", (tmp_path.resolve(),))

    handlers.search("needle", "FUNCTION", 3, 1)
    handlers.definition("needle", str(source), {"line": 0, "character": 1}, False)
    handlers.references("needle", str(source), {"line": 0, "character": 1})
    handlers.callers("needle", str(source), {"line": 0, "character": 1})
    output = handlers.callees("needle", str(source), {"line": 0, "character": 1})

    assert [name for name, _, _ in calls] == [
        "search",
        "definition",
        "references",
        "callers",
        "callees",
    ]
    assert all(kwargs["build_config_id"] == "arm" for _, _, kwargs in calls)
    assert calls[0][2]["kind_filter"] == "function"
    assert output["semantic_results"][0]["data"]["symbol_id"]["file"] == (
        "/usr/include/external.h"
    )


def test_fastmcp_success_exposes_complete_structured_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    expected = _ok_result(_location("/usr/include/external.h"))
    monkeypatch.setattr(
        codegraph_api, "search_symbol", lambda *_args, **_kwargs: expected
    )
    server = create_mcp_server(
        BuildConfig("arm", str(tmp_path)), allowed_read_roots=[str(tmp_path)]
    )

    returned = asyncio.run(server.call_tool("search", {"symbol": "needle"}))

    assert returned.isError is False
    assert returned.structuredContent == query_result_to_json(expected)
    assert json.loads(returned.content[0].text) == returned.structuredContent


def test_fastmcp_all_five_tools_reach_only_their_mapped_api(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "query.c"
    source.write_text("int needle(void);\n", encoding="utf-8")
    expected = _ok_result(_location())
    called: list[str] = []

    def fake(name: str):
        def call(*_args: object, **_kwargs: object) -> QueryResult:
            called.append(name)
            return expected

        return call

    for api_name in (
        "search_symbol",
        "get_definition",
        "find_references",
        "find_callers",
        "find_callees",
    ):
        monkeypatch.setattr(codegraph_api, api_name, fake(api_name))
    server = create_mcp_server(
        BuildConfig("arm", str(tmp_path)), allowed_read_roots=[str(tmp_path)]
    )
    position_args = {
        "symbol": "needle",
        "file": str(source),
        "pos": {"line": 0, "character": 1},
    }

    async def exercise() -> None:
        await server.call_tool("search", {"symbol": "needle"})
        await server.call_tool("definition", position_args)
        for name in ("references", "callers", "callees"):
            await server.call_tool(name, position_args)

    asyncio.run(exercise())

    assert called == [
        "search_symbol",
        "get_definition",
        "find_references",
        "find_callers",
        "find_callees",
    ]


@pytest.mark.parametrize(
    ("method", "arguments", "field"),
    [
        ("search", {"symbol": ""}, "symbol"),
        ("search", {"symbol": "x" * 513}, "symbol"),
        ("search", {"symbol": 1}, "symbol"),
        ("search", {"symbol": "bad\nname"}, "symbol"),
        ("search", {"symbol": "x", "kind_filter": "class"}, "kind_filter"),
        ("search", {"symbol": "x", "kind_filter": 1}, "kind_filter"),
        ("search", {"symbol": "x", "limit": True}, "limit"),
        ("search", {"symbol": "x", "limit": 0}, "limit"),
        ("search", {"symbol": "x", "limit": 1001}, "limit"),
        ("search", {"symbol": "x", "offset": -1}, "offset"),
        ("search", {"symbol": "x", "offset": False}, "offset"),
        ("search", {"symbol": "x", "offset": 1_000_001}, "offset"),
        (
            "definition",
            {"symbol": "x", "file": 1, "pos": {"line": 0, "character": 0}},
            "file",
        ),
        (
            "definition",
            {"symbol": "x", "file": "x" * 4097, "pos": {"line": 0, "character": 0}},
            "file",
        ),
        (
            "definition",
            {"symbol": "x", "file": "bad\npath", "pos": {"line": 0, "character": 0}},
            "file",
        ),
        (
            "definition",
            {"symbol": "x", "file": "/outside/x.c", "pos": {"line": 0, "character": 0}},
            "file",
        ),
        (
            "definition",
            {"symbol": "x", "file": "inside.c", "pos": {"line": -1, "character": 0}},
            "pos.line",
        ),
        (
            "definition",
            {"symbol": "x", "file": "inside.c", "pos": {"line": 0}},
            "pos",
        ),
        (
            "definition",
            {
                "symbol": "x",
                "file": "inside.c",
                "pos": {"line": 0, "character": 1 << 31},
            },
            "pos.character",
        ),
        (
            "definition",
            {"symbol": "x", "file": "inside.c", "pos": {"line": False, "character": 0}},
            "pos.line",
        ),
        (
            "definition",
            {
                "symbol": "x",
                "file": "inside.c",
                "pos": {"line": 0, "character": 0},
                "allow_syntactic_fallback": 1,
            },
            "allow_syntactic_fallback",
        ),
    ],
)
def test_invalid_parameters_return_stable_tool_error_without_calling_api(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    arguments: dict[str, object],
    field: str,
) -> None:
    (tmp_path / "inside.c").write_text("int x;\n", encoding="utf-8")
    called = False

    def should_not_run(*_args: object, **_kwargs: object) -> QueryResult:
        nonlocal called
        called = True
        raise AssertionError("library API must not run")

    monkeypatch.setattr(codegraph_api, "search_symbol", should_not_run)
    monkeypatch.setattr(codegraph_api, "get_definition", should_not_run)
    handlers = _ToolHandlers("arm", (tmp_path.resolve(),))
    if "file" in arguments and arguments["file"] == "inside.c":
        arguments["file"] = str(tmp_path / "inside.c")

    with pytest.raises(ToolError) as error:
        getattr(handlers, method)(**arguments)

    payload = json.loads(str(error.value))
    assert payload == {
        "error": {
            "code": "invalid_params",
            "detail": payload["error"]["detail"],
            "field": field,
        }
    }
    assert called is False


@pytest.mark.parametrize(
    ("method", "arguments", "field"),
    [
        ("search", {"symbol": "x", "limit": "1"}, "limit"),
        ("search", {"symbol": "x", "limit": True}, "limit"),
        ("search", {"symbol": "x", "kind_filter": 1}, "kind_filter"),
        (
            "definition",
            {
                "symbol": "x",
                "file": "SOURCE",
                "pos": {"line": True, "character": 0},
            },
            "pos.line",
        ),
        (
            "definition",
            {
                "symbol": "x",
                "file": "SOURCE",
                "pos": {"line": 0, "character": 0},
                "allow_syntactic_fallback": 0,
            },
            "allow_syntactic_fallback",
        ),
    ],
)
def test_fastmcp_boundary_does_not_coerce_invalid_parameter_types(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    arguments: dict[str, object],
    field: str,
) -> None:
    source = tmp_path / "query.c"
    source.write_text("int x;\n", encoding="utf-8")
    called = False

    def should_not_run(*_args: object, **_kwargs: object) -> QueryResult:
        nonlocal called
        called = True
        raise AssertionError("library API must not run")

    monkeypatch.setattr(codegraph_api, "search_symbol", should_not_run)
    monkeypatch.setattr(codegraph_api, "get_definition", should_not_run)
    server = create_mcp_server(
        BuildConfig("arm", str(tmp_path)), allowed_read_roots=[str(tmp_path)]
    )
    call_arguments = dict(arguments)
    if call_arguments.get("file") == "SOURCE":
        call_arguments["file"] = str(source)

    returned = asyncio.run(server.call_tool(method, call_arguments))

    assert returned.isError is True
    assert returned.structuredContent["error"]["field"] == field
    assert json.loads(returned.content[0].text) == returned.structuredContent
    assert called is False


def test_input_file_symlink_cannot_escape_allowed_root(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    target = outside / "external.c"
    target.write_text("int external;\n", encoding="utf-8")
    link = allowed / "query.c"
    link.symlink_to(target)
    handlers = _ToolHandlers("arm", (allowed.resolve(),))

    with pytest.raises(ToolError) as error:
        handlers.definition("external", str(link), {"line": 0, "character": 0})

    assert json.loads(str(error.value))["error"]["field"] == "file"


@pytest.mark.parametrize(
    ("tool_name", "arguments"),
    [
        ("search", {"symbol": "needle"}),
        (
            "definition",
            {
                "symbol": "needle",
                "file": "SOURCE",
                "pos": {"line": 0, "character": 0},
            },
        ),
        (
            "references",
            {
                "symbol": "needle",
                "file": "SOURCE",
                "pos": {"line": 0, "character": 0},
            },
        ),
        (
            "callers",
            {
                "symbol": "needle",
                "file": "SOURCE",
                "pos": {"line": 0, "character": 0},
            },
        ),
        (
            "callees",
            {
                "symbol": "needle",
                "file": "SOURCE",
                "pos": {"line": 0, "character": 0},
            },
        ),
    ],
)
@pytest.mark.parametrize("unknown_field", ["unexpected_field", "build_config_id"])
def test_raw_argument_gate_rejects_unknown_fields_for_every_tool(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tool_name: str,
    arguments: dict[str, object],
    unknown_field: str,
) -> None:
    source = tmp_path / "query.c"
    source.write_text("int needle(void);\n", encoding="utf-8")
    called = False

    def should_not_run(*_args: object, **_kwargs: object) -> QueryResult:
        nonlocal called
        called = True
        raise AssertionError("library API must not run")

    for api_name in (
        "search_symbol",
        "get_definition",
        "find_references",
        "find_callers",
        "find_callees",
    ):
        monkeypatch.setattr(codegraph_api, api_name, should_not_run)
    server = create_mcp_server(
        BuildConfig("arm", str(tmp_path)), allowed_read_roots=[str(tmp_path)]
    )
    call_arguments = dict(arguments)
    if call_arguments.get("file") == "SOURCE":
        call_arguments["file"] = str(source)
    call_arguments[unknown_field] = (
        "forged" if unknown_field == "build_config_id" else True
    )

    returned = asyncio.run(server.call_tool(tool_name, call_arguments))

    assert returned.isError is True
    assert returned.structuredContent == {
        "error": {
            "code": "invalid_params",
            "field": unknown_field,
            "detail": "unknown parameter",
        }
    }
    assert json.loads(returned.content[0].text) == returned.structuredContent
    assert called is False


@pytest.mark.parametrize(
    ("tool_name", "arguments", "missing_field"),
    [
        ("search", {}, "symbol"),
        (
            "definition",
            {"symbol": "needle", "pos": {"line": 0, "character": 0}},
            "file",
        ),
        (
            "references",
            {"symbol": "needle", "file": "SOURCE"},
            "pos",
        ),
        (
            "callers",
            {"file": "SOURCE", "pos": {"line": 0, "character": 0}},
            "symbol",
        ),
        (
            "callees",
            {"symbol": "needle", "file": "SOURCE"},
            "pos",
        ),
    ],
)
def test_raw_argument_gate_structures_missing_required_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tool_name: str,
    arguments: dict[str, object],
    missing_field: str,
) -> None:
    source = tmp_path / "query.c"
    source.write_text("int needle(void);\n", encoding="utf-8")
    called = False

    def should_not_run(*_args: object, **_kwargs: object) -> QueryResult:
        nonlocal called
        called = True
        raise AssertionError("library API must not run")

    for api_name in (
        "search_symbol",
        "get_definition",
        "find_references",
        "find_callers",
        "find_callees",
    ):
        monkeypatch.setattr(codegraph_api, api_name, should_not_run)
    server = create_mcp_server(
        BuildConfig("arm", str(tmp_path)), allowed_read_roots=[str(tmp_path)]
    )
    call_arguments = dict(arguments)
    if call_arguments.get("file") == "SOURCE":
        call_arguments["file"] = str(source)

    returned = asyncio.run(server.call_tool(tool_name, call_arguments))

    assert returned.isError is True
    assert returned.structuredContent == {
        "error": {
            "code": "invalid_params",
            "field": missing_field,
            "detail": "required parameter is missing",
        }
    }
    assert called is False


def test_raw_argument_gate_runs_before_fastmcp_tool_manager(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server = create_mcp_server(
        BuildConfig("arm", str(tmp_path)), allowed_read_roots=[str(tmp_path)]
    )
    dispatched = False

    async def should_not_dispatch(*_args: object, **_kwargs: object) -> object:
        nonlocal dispatched
        dispatched = True
        raise AssertionError("FastMCP ToolManager must not run")

    monkeypatch.setattr(server._tool_manager, "call_tool", should_not_dispatch)

    returned = asyncio.run(
        server.call_tool("search", {"symbol": "needle", "unexpected_field": True})
    )

    assert returned.isError is True
    assert returned.structuredContent["error"]["field"] == "unexpected_field"
    assert dispatched is False


def test_raw_argument_gate_rejects_non_object_and_ignores_unknown_tool() -> None:
    with pytest.raises(ToolError, match='"field":"arguments"'):
        mcp_module._validate_raw_arguments("search", [])

    assert mcp_module._validate_raw_arguments("future_tool", {}) is None


def test_load_startup_config_converts_enums_and_rejects_unknown_fields(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "mcp.json"
    config_path.write_text(
        json.dumps(
            {
                "build_config": {
                    "build_config_id": "arm",
                    "compile_commands_dir": str(tmp_path),
                    "source_roots": [str(tmp_path)],
                    "active_config": "target",
                    "index_scope": "indexed_project",
                },
                "allowed_read_roots": [str(tmp_path)],
            }
        ),
        encoding="utf-8",
    )

    config, roots = load_startup_config(config_path)

    assert config.source_roots == (str(tmp_path),)
    assert config.active_config is ActiveConfig.TARGET
    assert config.index_scope is IndexScope.INDEXED_PROJECT
    assert roots == (str(tmp_path),)

    raw = json.loads(config_path.read_text(encoding="utf-8"))
    raw["build_config"]["unexpected"] = True
    config_path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="unknown BuildConfig fields"):
        load_startup_config(config_path)

    del raw["build_config"]["unexpected"]
    raw["unexpected"] = True
    config_path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="unknown startup config fields"):
        load_startup_config(config_path)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("background_index", "false", "must be a boolean"),
        ("request_timeout", "30", "must be a finite number"),
        ("request_timeout", True, "must be a finite number"),
        ("diagnostics_wait", None, "must be a finite number"),
        ("index_ready_timeout", float("nan"), "must be a finite number"),
        ("prewarm_index_ready_timeout", "30", "must be a finite number"),
        ("clangd_path", 18, "must be a string"),
        ("warmup_file", False, "must be a string or null"),
        ("index_ready_probe_symbol", 1, "must be a string or null"),
        ("active_config", 1, "must be a string"),
        ("index_scope", False, "must be a string"),
    ],
)
def test_load_startup_config_strictly_validates_every_field_family(
    tmp_path: Path, field: str, value: object, message: str
) -> None:
    config_path = tmp_path / "mcp.json"
    config_path.write_text(
        json.dumps(
            {
                "build_config": {
                    "build_config_id": "arm",
                    "compile_commands_dir": str(tmp_path),
                    field: value,
                },
                "allowed_read_roots": [str(tmp_path)],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=message):
        load_startup_config(config_path)


def test_load_startup_config_accepts_json_numbers_for_float_fields(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "mcp.json"
    config_path.write_text(
        json.dumps(
            {
                "build_config": {
                    "build_config_id": "arm",
                    "compile_commands_dir": str(tmp_path),
                    "request_timeout": 30,
                    "diagnostics_wait": 0,
                    "index_ready_timeout": 0,
                    "prewarm_index_ready_timeout": None,
                    "warmup_file": str(tmp_path / "warm.c"),
                    "background_index": True,
                },
                "allowed_read_roots": [str(tmp_path)],
            }
        ),
        encoding="utf-8",
    )

    config, _ = load_startup_config(config_path)

    assert config.request_timeout == 30.0
    assert type(config.request_timeout) is float
    assert config.diagnostics_wait == 0.0
    assert config.index_ready_timeout == 0.0
    assert config.prewarm_index_ready_timeout is None
    assert config.warmup_file == str(tmp_path / "warm.c")
    assert config.background_index is True


@pytest.mark.parametrize("missing", ["build_config_id", "compile_commands_dir"])
def test_load_startup_config_requires_build_config_fields(
    tmp_path: Path, missing: str
) -> None:
    build_config = {
        "build_config_id": "arm",
        "compile_commands_dir": str(tmp_path),
    }
    del build_config[missing]
    config_path = tmp_path / "mcp.json"
    config_path.write_text(
        json.dumps(
            {
                "build_config": build_config,
                "allowed_read_roots": [str(tmp_path)],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=rf"BuildConfig\.{missing} is required"):
        load_startup_config(config_path)


def test_load_startup_config_rejects_number_that_overflows_float(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "mcp.json"
    config_path.write_text(
        json.dumps(
            {
                "build_config": {
                    "build_config_id": "arm",
                    "compile_commands_dir": str(tmp_path),
                    "request_timeout": 10**400,
                },
                "allowed_read_roots": [str(tmp_path)],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="must be a finite number"):
        load_startup_config(config_path)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("request_timeout", 0, "must be greater than zero"),
        ("request_timeout", -1, "must be greater than zero"),
        ("diagnostics_wait", -0.1, "must be non-negative"),
        ("index_ready_timeout", -0.1, "must be non-negative"),
        ("prewarm_index_ready_timeout", -0.1, "must be non-negative"),
        ("index_ready_poll_interval", 0, "must be greater than zero"),
        ("index_ready_poll_interval", -0.1, "must be greater than zero"),
    ],
)
def test_load_startup_config_rejects_out_of_range_numbers(
    tmp_path: Path, field: str, value: int | float, message: str
) -> None:
    config_path = tmp_path / "mcp.json"
    config_path.write_text(
        json.dumps(
            {
                "build_config": {
                    "build_config_id": "arm",
                    "compile_commands_dir": str(tmp_path),
                    field: value,
                },
                "allowed_read_roots": [str(tmp_path)],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=message):
        load_startup_config(config_path)


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ([], "startup config must be a JSON object"),
        ({"allowed_read_roots": ["ROOT"]}, "build_config must be a JSON object"),
        ({"build_config": {}}, "allowed_read_roots must be a non-empty JSON array"),
        (
            {
                "build_config": {
                    "build_config_id": "arm",
                    "compile_commands_dir": "ROOT",
                    "source_roots": "ROOT",
                },
                "allowed_read_roots": ["ROOT"],
            },
            "BuildConfig.source_roots must be an array of strings",
        ),
        (
            {
                "build_config": {
                    "build_config_id": "",
                    "compile_commands_dir": "ROOT",
                },
                "allowed_read_roots": ["ROOT"],
            },
            "BuildConfig.build_config_id must be a non-empty string",
        ),
        (
            {
                "build_config": {
                    "build_config_id": "arm",
                    "compile_commands_dir": 1,
                },
                "allowed_read_roots": ["ROOT"],
            },
            "BuildConfig.compile_commands_dir must be a string",
        ),
        (
            {
                "build_config": {
                    "build_config_id": "arm",
                    "compile_commands_dir": "ROOT",
                },
                "allowed_read_roots": [1],
            },
            "allowed_read_roots must contain only strings",
        ),
    ],
)
def test_load_startup_config_rejects_invalid_shapes(
    tmp_path: Path, payload: object, message: str
) -> None:
    config_path = tmp_path / "mcp.json"
    replaced = json.loads(json.dumps(payload).replace("ROOT", str(tmp_path)))
    config_path.write_text(json.dumps(replaced), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        load_startup_config(config_path)


def test_allowed_roots_are_required_real_directories_and_deduplicated(
    tmp_path: Path,
) -> None:
    assert mcp_module._normalize_allowed_roots([str(tmp_path), str(tmp_path)]) == (
        tmp_path.resolve(),
    )
    with pytest.raises(ValueError, match="must not be empty"):
        mcp_module._normalize_allowed_roots([])
    with pytest.raises(ValueError, match="non-empty paths"):
        mcp_module._normalize_allowed_roots([""])
    with pytest.raises(ValueError, match="not a directory"):
        mcp_module._normalize_allowed_roots([str(tmp_path / "missing")])


def test_invalid_startup_config_writes_only_stderr(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "bad.json"
    config.write_text("not json", encoding="utf-8")

    assert main(["--config", str(config)]) == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err)["error"]["code"] == "invalid_server_config"


def test_main_runs_only_stdio_with_valid_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "mcp.json"
    config_path.write_text(
        json.dumps(
            {
                "build_config": {
                    "build_config_id": "arm",
                    "compile_commands_dir": str(tmp_path),
                },
                "allowed_read_roots": [str(tmp_path)],
            }
        ),
        encoding="utf-8",
    )
    transports: list[str] = []

    class FakeServer:
        def run(self, *, transport: str) -> None:
            transports.append(transport)

    monkeypatch.setattr(
        mcp_module, "create_mcp_server", lambda *_args, **_kwargs: FakeServer()
    )

    assert main(["--config", str(config_path)]) == 0
    assert transports == ["stdio"]


def test_real_sdk_stdio_client_sees_only_protocol_frames(tmp_path: Path) -> None:
    config = tmp_path / "mcp.json"
    config.write_text(
        json.dumps(
            {
                "build_config": {
                    "build_config_id": "arm",
                    "compile_commands_dir": str(tmp_path),
                    "source_roots": [str(tmp_path)],
                },
                "allowed_read_roots": [str(tmp_path)],
            }
        ),
        encoding="utf-8",
    )
    stderr_path = tmp_path / "server.stderr"

    async def exercise() -> tuple[set[str], object, object]:
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "codegraph.mcp_server", "--config", str(config)],
            cwd=Path(__file__).resolve().parents[1],
            env=dict(os.environ),
        )
        with stderr_path.open("w", encoding="utf-8") as stderr:
            async with stdio_client(params, errlog=stderr) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    invalid = await session.call_tool("search", {"symbol": ""})
                    unexpected = await session.call_tool(
                        "search", {"symbol": "needle", "unexpected_field": True}
                    )
                    return {tool.name for tool in tools.tools}, invalid, unexpected

    names, invalid, unexpected = asyncio.run(exercise())

    assert names == {"search", "definition", "references", "callers", "callees"}
    assert invalid.isError is True
    assert json.loads(invalid.content[0].text)["error"]["code"] == "invalid_params"
    assert invalid.structuredContent == json.loads(invalid.content[0].text)
    assert unexpected.isError is True
    assert unexpected.structuredContent == {
        "error": {
            "code": "invalid_params",
            "field": "unexpected_field",
            "detail": "unknown parameter",
        }
    }
    assert "Traceback" not in stderr_path.read_text(encoding="utf-8")
