"""stdio-only MCP adapter for the public CodeGraph library API."""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sys
from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Annotated, Any, NoReturn, cast

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import CallToolResult, TextContent
from pydantic import WithJsonSchema

from . import api as codegraph_api
from .api import BuildConfig
from .credibility import ActiveConfig, IndexScope
from .types import Pos, QueryResult

_MAX_SYMBOL_LENGTH = 512
_MAX_FILE_LENGTH = 4096
_MAX_POSITION = (1 << 31) - 1
_MAX_LIMIT = 1000
_MAX_OFFSET = 1_000_000
_KIND_FILTERS = frozenset({"function", "variable", "type", "macro"})
_NOT_EVIDENCE_WARNING = (
    "syntactic_candidates 仅作启发，带 consumer_warning=not_evidence，"
    "不得作为确定性证据使用。"
)
_SERVER_INSTRUCTIONS = (
    "CodeGraph exposes code facts with complete credibility metadata. "
    + _NOT_EVIDENCE_WARNING
)

_SymbolInput = Annotated[
    Any,
    WithJsonSchema({"type": "string", "minLength": 1, "maxLength": _MAX_SYMBOL_LENGTH}),
]
_FileInput = Annotated[
    Any,
    WithJsonSchema({"type": "string", "minLength": 1, "maxLength": _MAX_FILE_LENGTH}),
]
_PosInput = Annotated[
    Any,
    WithJsonSchema(
        {
            "type": "object",
            "properties": {
                "line": {"type": "integer", "minimum": 0, "maximum": _MAX_POSITION},
                "character": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": _MAX_POSITION,
                },
            },
            "required": ["line", "character"],
            "additionalProperties": False,
        }
    ),
]
_LimitInput = Annotated[
    Any,
    WithJsonSchema({"type": "integer", "minimum": 1, "maximum": _MAX_LIMIT}),
]
_OffsetInput = Annotated[
    Any,
    WithJsonSchema({"type": "integer", "minimum": 0, "maximum": _MAX_OFFSET}),
]
_KindFilterInput = Annotated[
    Any,
    WithJsonSchema(
        {
            "anyOf": [
                {"type": "null"},
                {"type": "string", "enum": sorted(_KIND_FILTERS)},
            ]
        }
    ),
]
_BoolInput = Annotated[Any, WithJsonSchema({"type": "boolean"})]


@dataclass(frozen=True, slots=True)
class _ArgumentContract:
    allowed: frozenset[str]
    required: frozenset[str]


_POSITION_QUERY_ARGUMENTS = frozenset(
    {
        "symbol",
        "file",
        "pos",
        "limit",
        "offset",
        "allow_syntactic_fallback",
    }
)
_TOOL_ARGUMENT_CONTRACTS = {
    "search": _ArgumentContract(
        frozenset({"symbol", "kind_filter", "limit", "offset"}),
        frozenset({"symbol"}),
    ),
    "definition": _ArgumentContract(
        frozenset({"symbol", "file", "pos", "allow_syntactic_fallback"}),
        frozenset({"symbol", "file", "pos"}),
    ),
    "references": _ArgumentContract(
        _POSITION_QUERY_ARGUMENTS, frozenset({"symbol", "file", "pos"})
    ),
    "callers": _ArgumentContract(
        _POSITION_QUERY_ARGUMENTS, frozenset({"symbol", "file", "pos"})
    ),
    "callees": _ArgumentContract(
        _POSITION_QUERY_ARGUMENTS, frozenset({"symbol", "file", "pos"})
    ),
}


class _StrictFastMCP(FastMCP):
    """FastMCP with a fail-closed raw argument gate before Pydantic."""

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        try:
            _validate_raw_arguments(name, arguments)
        except ToolError as exc:
            return _tool_error_result(exc)
        return await super().call_tool(name, arguments)

    async def list_tools(self) -> list[Any]:
        tools = await super().list_tools()
        for tool in tools:
            contract = _TOOL_ARGUMENT_CONTRACTS.get(tool.name)
            if contract is None:
                continue
            properties = set(tool.inputSchema.get("properties", {}))
            required = set(tool.inputSchema.get("required", []))
            if properties != contract.allowed or required != contract.required:
                raise RuntimeError(f"tool argument contract drift: {tool.name}")
            tool.inputSchema["additionalProperties"] = False
        return tools


def query_result_to_json(result: QueryResult) -> dict[str, Any]:
    """Convert a QueryResult to JSON data without dropping or stringifying fields."""

    converted = _to_json_value(result)
    if not isinstance(
        converted, dict
    ):  # pragma: no cover - QueryResult is a dataclass.
        raise TypeError("QueryResult serializer did not produce an object")
    json.dumps(converted, ensure_ascii=False, allow_nan=False)
    return cast(dict[str, Any], converted)


def _to_json_value(value: object) -> Any:
    if isinstance(value, Enum):
        return _to_json_value(value.value)
    if isinstance(value, os.PathLike):
        return _to_json_value(os.fspath(value))
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _to_json_value(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, (list, tuple)):
        return [_to_json_value(item) for item in value]
    if isinstance(value, dict):
        converted: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("JSON object keys must be strings")
            converted[key] = _to_json_value(item)
        return converted
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise TypeError("non-finite floats are not valid JSON values")
        return value
    raise TypeError(f"unsupported MCP serialization type: {type(value).__name__}")


@dataclass(frozen=True, slots=True)
class _ToolHandlers:
    build_config_id: str
    allowed_read_roots: tuple[Path, ...]

    def search(
        self,
        symbol: object,
        kind_filter: object = None,
        limit: object = 100,
        offset: object = 0,
    ) -> dict[str, Any]:
        checked_symbol = _validate_symbol(symbol)
        checked_kind = _validate_kind_filter(kind_filter)
        checked_limit = _validate_integer("limit", limit, minimum=1, maximum=_MAX_LIMIT)
        checked_offset = _validate_integer(
            "offset", offset, minimum=0, maximum=_MAX_OFFSET
        )
        return query_result_to_json(
            codegraph_api.search_symbol(
                checked_symbol,
                build_config_id=self.build_config_id,
                kind_filter=checked_kind,
                limit=checked_limit,
                offset=checked_offset,
            )
        )

    def definition(
        self,
        symbol: object,
        file: object,
        pos: object,
        allow_syntactic_fallback: object = False,
    ) -> dict[str, Any]:
        checked_symbol = _validate_symbol(symbol)
        checked_file = _validate_input_file(file, self.allowed_read_roots)
        checked_pos = _validate_pos(pos)
        checked_fallback = _validate_bool(
            "allow_syntactic_fallback", allow_syntactic_fallback
        )
        return query_result_to_json(
            codegraph_api.get_definition(
                checked_symbol,
                checked_file,
                checked_pos,
                build_config_id=self.build_config_id,
                allow_syntactic_fallback=checked_fallback,
            )
        )

    def references(
        self,
        symbol: object,
        file: object,
        pos: object,
        limit: object = 100,
        offset: object = 0,
        allow_syntactic_fallback: object = False,
    ) -> dict[str, Any]:
        return self._position_list_query(
            codegraph_api.find_references,
            symbol,
            file,
            pos,
            limit,
            offset,
            allow_syntactic_fallback,
        )

    def callers(
        self,
        symbol: object,
        file: object,
        pos: object,
        limit: object = 100,
        offset: object = 0,
        allow_syntactic_fallback: object = False,
    ) -> dict[str, Any]:
        return self._position_list_query(
            codegraph_api.find_callers,
            symbol,
            file,
            pos,
            limit,
            offset,
            allow_syntactic_fallback,
        )

    def callees(
        self,
        symbol: object,
        file: object,
        pos: object,
        limit: object = 100,
        offset: object = 0,
        allow_syntactic_fallback: object = False,
    ) -> dict[str, Any]:
        return self._position_list_query(
            codegraph_api.find_callees,
            symbol,
            file,
            pos,
            limit,
            offset,
            allow_syntactic_fallback,
        )

    def _position_list_query(
        self,
        query: Any,
        symbol: object,
        file: object,
        pos: object,
        limit: object,
        offset: object,
        allow_syntactic_fallback: object,
    ) -> dict[str, Any]:
        checked_symbol = _validate_symbol(symbol)
        checked_file = _validate_input_file(file, self.allowed_read_roots)
        checked_pos = _validate_pos(pos)
        checked_limit = _validate_integer("limit", limit, minimum=1, maximum=_MAX_LIMIT)
        checked_offset = _validate_integer(
            "offset", offset, minimum=0, maximum=_MAX_OFFSET
        )
        checked_fallback = _validate_bool(
            "allow_syntactic_fallback", allow_syntactic_fallback
        )
        return query_result_to_json(
            query(
                checked_symbol,
                checked_file,
                checked_pos,
                build_config_id=self.build_config_id,
                limit=checked_limit,
                offset=checked_offset,
                allow_syntactic_fallback=checked_fallback,
            )
        )


def create_mcp_server(
    config: BuildConfig,
    *,
    allowed_read_roots: tuple[str, ...] | list[str],
) -> FastMCP:
    """Create the stdio MCP server with one startup-injected build config."""

    roots = _normalize_allowed_roots(allowed_read_roots)
    codegraph_api.register_build_config(config)
    handlers = _ToolHandlers(config.build_config_id, roots)
    server = _StrictFastMCP(
        "CodeGraph",
        instructions=_SERVER_INSTRUCTIONS,
        log_level="WARNING",
    )

    @server.tool(
        name="search",
        description=_tool_description("Search for a symbol."),
        structured_output=False,
    )
    def search(
        symbol: _SymbolInput,
        kind_filter: _KindFilterInput = None,
        limit: _LimitInput = 100,
        offset: _OffsetInput = 0,
    ) -> CallToolResult:
        return _mcp_call(handlers.search, symbol, kind_filter, limit, offset)

    @server.tool(
        name="definition",
        description=_tool_description("Get the definition of a symbol."),
        structured_output=False,
    )
    def definition(
        symbol: _SymbolInput,
        file: _FileInput,
        pos: _PosInput,
        allow_syntactic_fallback: _BoolInput = False,
    ) -> CallToolResult:
        return _mcp_call(
            handlers.definition, symbol, file, pos, allow_syntactic_fallback
        )

    @server.tool(
        name="references",
        description=_tool_description("Find references to a symbol."),
        structured_output=False,
    )
    def references(
        symbol: _SymbolInput,
        file: _FileInput,
        pos: _PosInput,
        limit: _LimitInput = 100,
        offset: _OffsetInput = 0,
        allow_syntactic_fallback: _BoolInput = False,
    ) -> CallToolResult:
        return _mcp_call(
            handlers.references,
            symbol,
            file,
            pos,
            limit,
            offset,
            allow_syntactic_fallback,
        )

    @server.tool(
        name="callers",
        description=_tool_description("Find direct callers of a symbol."),
        structured_output=False,
    )
    def callers(
        symbol: _SymbolInput,
        file: _FileInput,
        pos: _PosInput,
        limit: _LimitInput = 100,
        offset: _OffsetInput = 0,
        allow_syntactic_fallback: _BoolInput = False,
    ) -> CallToolResult:
        return _mcp_call(
            handlers.callers,
            symbol,
            file,
            pos,
            limit,
            offset,
            allow_syntactic_fallback,
        )

    @server.tool(
        name="callees",
        description=_tool_description("Find direct callees of a symbol."),
        structured_output=False,
    )
    def callees(
        symbol: _SymbolInput,
        file: _FileInput,
        pos: _PosInput,
        limit: _LimitInput = 100,
        offset: _OffsetInput = 0,
        allow_syntactic_fallback: _BoolInput = False,
    ) -> CallToolResult:
        return _mcp_call(
            handlers.callees,
            symbol,
            file,
            pos,
            limit,
            offset,
            allow_syntactic_fallback,
        )

    return server


def load_startup_config(path: str | Path) -> tuple[BuildConfig, tuple[str, ...]]:
    """Load the operator-owned startup JSON used by the stdio server."""

    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("startup config must be a JSON object")
    unknown_top_level = sorted(set(raw) - {"build_config", "allowed_read_roots"})
    if unknown_top_level:
        raise ValueError(
            f"unknown startup config fields: {', '.join(unknown_top_level)}"
        )
    build_raw = raw.get("build_config")
    roots_raw = raw.get("allowed_read_roots")
    if not isinstance(build_raw, dict):
        raise ValueError("build_config must be a JSON object")
    if not isinstance(roots_raw, list) or not roots_raw:
        raise ValueError("allowed_read_roots must be a non-empty JSON array")

    values = _validate_build_config_values(build_raw)
    config = BuildConfig(**values)
    if not all(isinstance(root, str) for root in roots_raw):
        raise ValueError("allowed_read_roots must contain only strings")
    roots = tuple(cast(list[str], roots_raw))
    _normalize_allowed_roots(roots)
    return config, roots


def _tool_description(summary: str) -> str:
    return f"{summary} {_NOT_EVIDENCE_WARNING}"


def _validate_build_config_values(build_raw: dict[str, Any]) -> dict[str, Any]:
    allowed_fields = {field.name for field in fields(BuildConfig)}
    unknown = sorted(set(build_raw) - allowed_fields)
    if unknown:
        raise ValueError(f"unknown BuildConfig fields: {', '.join(unknown)}")
    for required in ("build_config_id", "compile_commands_dir"):
        if required not in build_raw:
            raise ValueError(f"BuildConfig.{required} is required")

    string_fields = {"build_config_id", "compile_commands_dir", "clangd_path"}
    optional_string_fields = {
        "index_ready_probe_symbol",
        "index_ready_probe_path_suffix",
        "warmup_file",
    }
    number_fields = {
        "request_timeout",
        "diagnostics_wait",
        "index_ready_timeout",
        "index_ready_poll_interval",
    }
    handled_fields = (
        string_fields
        | optional_string_fields
        | number_fields
        | {
            "source_roots",
            "background_index",
            "prewarm_index_ready_timeout",
            "active_config",
            "index_scope",
        }
    )
    unvalidated = allowed_fields - handled_fields
    if unvalidated:  # pragma: no cover - protects future BuildConfig fields.
        raise RuntimeError(
            f"BuildConfig fields lack MCP startup validators: {', '.join(sorted(unvalidated))}"
        )

    values: dict[str, Any] = {}
    for name, value in build_raw.items():
        if name in string_fields:
            if type(value) is not str:
                raise ValueError(f"BuildConfig.{name} must be a string")
            if name == "build_config_id" and not value:
                raise ValueError(
                    "BuildConfig.build_config_id must be a non-empty string"
                )
            values[name] = value
        elif name in optional_string_fields:
            if value is not None and type(value) is not str:
                raise ValueError(f"BuildConfig.{name} must be a string or null")
            values[name] = value
        elif name in number_fields:
            values[name] = _validate_config_number(name, value)
        elif name == "prewarm_index_ready_timeout":
            values[name] = (
                None if value is None else _validate_config_number(name, value)
            )
        elif name == "source_roots":
            if not isinstance(value, list) or not all(
                type(root) is str for root in value
            ):
                raise ValueError("BuildConfig.source_roots must be an array of strings")
            values[name] = tuple(value)
        elif name == "background_index":
            if type(value) is not bool:
                raise ValueError("BuildConfig.background_index must be a boolean")
            values[name] = value
        elif name == "active_config":
            if type(value) is not str:
                raise ValueError("BuildConfig.active_config must be a string")
            values[name] = ActiveConfig(value)
        elif name == "index_scope":
            if type(value) is not str:
                raise ValueError("BuildConfig.index_scope must be a string")
            values[name] = IndexScope(value)
    return values


def _validate_config_number(field: str, value: object) -> float:
    if type(value) not in (int, float):
        raise ValueError(f"BuildConfig.{field} must be a finite number")
    try:
        number = float(cast(int | float, value))
    except OverflowError as exc:
        raise ValueError(f"BuildConfig.{field} must be a finite number") from exc
    if not math.isfinite(number):
        raise ValueError(f"BuildConfig.{field} must be a finite number")
    return number


def _validate_raw_arguments(name: str, arguments: dict[str, Any]) -> None:
    contract = _TOOL_ARGUMENT_CONTRACTS.get(name)
    if contract is None:
        return
    unknown = sorted(set(arguments) - contract.allowed)
    if unknown:
        _invalid_parameter(unknown[0], "unknown parameter")
    missing = sorted(contract.required - set(arguments))
    if missing:
        _invalid_parameter(missing[0], "required parameter is missing")


def _mcp_call(handler: Any, *arguments: object) -> CallToolResult:
    try:
        payload = handler(*arguments)
        is_error = False
    except ToolError as exc:
        return _tool_error_result(exc)
    return _call_tool_result(payload, is_error=is_error)


def _tool_error_result(error: ToolError) -> CallToolResult:
    return _call_tool_result(json.loads(str(error)), is_error=True)


def _call_tool_result(payload: dict[str, Any], *, is_error: bool) -> CallToolResult:
    text = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )
    return CallToolResult(
        content=[TextContent(type="text", text=text)],
        structuredContent=payload,
        isError=is_error,
    )


def _normalize_allowed_roots(roots: tuple[str, ...] | list[str]) -> tuple[Path, ...]:
    if not roots:
        raise ValueError("allowed_read_roots must not be empty")
    normalized: list[Path] = []
    for root in roots:
        if not isinstance(root, str) or not root or len(root) > _MAX_FILE_LENGTH:
            raise ValueError("allowed_read_roots entries must be non-empty paths")
        path = Path(root).resolve()
        if not path.is_dir():
            raise ValueError(f"allowed_read_root is not a directory: {root}")
        if path not in normalized:
            normalized.append(path)
    return tuple(normalized)


def _validate_symbol(value: object) -> str:
    if not isinstance(value, str):
        _invalid_parameter("symbol", "must be a string")
    if not 1 <= len(value) <= _MAX_SYMBOL_LENGTH:
        _invalid_parameter("symbol", "length must be between 1 and 512")
    if any(character in value for character in ("\x00", "\r", "\n")):
        _invalid_parameter("symbol", "must not contain NUL, CR, or LF")
    return value


def _validate_input_file(value: object, allowed_roots: tuple[Path, ...]) -> str:
    if not isinstance(value, str):
        _invalid_parameter("file", "must be a string")
    if not 1 <= len(value) <= _MAX_FILE_LENGTH:
        _invalid_parameter("file", "length must be between 1 and 4096")
    if any(character in value for character in ("\x00", "\r", "\n")):
        _invalid_parameter("file", "must not contain NUL, CR, or LF")
    resolved = Path(value).resolve()
    if not any(resolved == root or root in resolved.parents for root in allowed_roots):
        _invalid_parameter("file", "realpath is outside allowed_read_roots")
    return str(resolved)


def _validate_pos(value: object) -> Pos:
    if not isinstance(value, dict) or set(value) != {"line", "character"}:
        _invalid_parameter("pos", "must contain exactly line and character")
    line = _validate_integer(
        "pos.line", value["line"], minimum=0, maximum=_MAX_POSITION
    )
    character = _validate_integer(
        "pos.character", value["character"], minimum=0, maximum=_MAX_POSITION
    )
    return Pos(line, character)


def _validate_kind_filter(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        _invalid_parameter("kind_filter", "must be null or a string")
    normalized = value.lower()
    if normalized not in _KIND_FILTERS:
        _invalid_parameter(
            "kind_filter", "must be one of function, variable, type, macro"
        )
    return normalized


def _validate_bool(field: str, value: object) -> bool:
    if type(value) is not bool:
        _invalid_parameter(field, "must be a boolean")
    return cast(bool, value)


def _validate_integer(field: str, value: object, *, minimum: int, maximum: int) -> int:
    if type(value) is not int:
        _invalid_parameter(field, "must be an integer")
    integer = cast(int, value)
    if not minimum <= integer <= maximum:
        _invalid_parameter(field, f"must be between {minimum} and {maximum}")
    return integer


def _invalid_parameter(field: str, detail: str) -> NoReturn:
    payload = {"error": {"code": "invalid_params", "field": field, "detail": detail}}
    raise ToolError(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the CodeGraph stdio MCP server")
    parser.add_argument("--config", required=True, help="startup JSON configuration")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    try:
        config, roots = load_startup_config(args.config)
        server = create_mcp_server(config, allowed_read_roots=roots)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        payload = {"error": {"code": "invalid_server_config", "detail": str(exc)}}
        sys.stderr.write(json.dumps(payload, ensure_ascii=False) + "\n")
        return 2
    server.run(transport="stdio")
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through subprocess.
    raise SystemExit(main())
