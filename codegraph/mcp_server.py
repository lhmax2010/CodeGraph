"""stdio-only MCP adapter for the public CodeGraph library API."""

from __future__ import annotations

import argparse
import json
import logging
import math
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
    server = FastMCP(
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
    build_raw = raw.get("build_config")
    roots_raw = raw.get("allowed_read_roots")
    if not isinstance(build_raw, dict):
        raise ValueError("build_config must be a JSON object")
    if not isinstance(roots_raw, list) or not roots_raw:
        raise ValueError("allowed_read_roots must be a non-empty JSON array")

    allowed_fields = {field.name for field in fields(BuildConfig)}
    unknown = sorted(set(build_raw) - allowed_fields)
    if unknown:
        raise ValueError(f"unknown BuildConfig fields: {', '.join(unknown)}")
    values = dict(build_raw)
    if "source_roots" in values:
        if not isinstance(values["source_roots"], list) or not all(
            isinstance(root, str) for root in values["source_roots"]
        ):
            raise ValueError("BuildConfig.source_roots must be an array of strings")
        values["source_roots"] = tuple(values["source_roots"])
    if "active_config" in values:
        values["active_config"] = ActiveConfig(values["active_config"])
    if "index_scope" in values:
        values["index_scope"] = IndexScope(values["index_scope"])
    config = BuildConfig(**values)
    if not config.build_config_id or not isinstance(config.build_config_id, str):
        raise ValueError("BuildConfig.build_config_id must be a non-empty string")
    if not isinstance(config.compile_commands_dir, str):
        raise ValueError("BuildConfig.compile_commands_dir must be a string")
    if not all(isinstance(root, str) for root in roots_raw):
        raise ValueError("allowed_read_roots must contain only strings")
    roots = tuple(cast(list[str], roots_raw))
    _normalize_allowed_roots(roots)
    return config, roots


def _tool_description(summary: str) -> str:
    return f"{summary} {_NOT_EVIDENCE_WARNING}"


def _mcp_call(handler: Any, *arguments: object) -> CallToolResult:
    try:
        payload = handler(*arguments)
        is_error = False
    except ToolError as exc:
        payload = json.loads(str(exc))
        is_error = True
    text = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
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
    raise ToolError(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )


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
