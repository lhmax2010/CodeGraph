"""tree-sitter syntactic fallback provider and syntax helper."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

from ..credibility import (
    ActiveConfig,
    Certainty,
    Coverage,
    Credibility,
    DependencyScope,
    IndexScope,
    QueryKind,
    Relation,
    Resolved,
    Source,
    SymbolKind,
    validate,
)
from ..types import Candidate, LocationResult, Pos, Range, SymbolId

_Language: Any
_Parser: Any
_tree_sitter_c: Any
_tree_sitter_cpp: Any
_IMPORT_ERROR: Exception | None = None

try:
    from tree_sitter import Language as _Language
    from tree_sitter import Parser as _Parser
    import tree_sitter_c as _tree_sitter_c
    import tree_sitter_cpp as _tree_sitter_cpp
except ImportError as exc:  # pragma: no cover - covered via monkeypatch.
    _Language = None
    _Parser = None
    _tree_sitter_c = None
    _tree_sitter_cpp = None
    _IMPORT_ERROR = exc


_C_EXTENSIONS = {".c", ".h"}
_CPP_EXTENSIONS = {".cc", ".cpp", ".cxx", ".hpp", ".hh", ".hxx"}
_SOURCE_EXTENSIONS = _C_EXTENSIONS | _CPP_EXTENSIONS
_PREPROC_NODE_TYPES = {
    "preproc_arg",
    "preproc_call",
    "preproc_defined",
    "preproc_elif",
    "preproc_else",
    "preproc_function_def",
    "preproc_if",
    "preproc_ifdef",
    "preproc_include",
}


class TreeSitterUnavailable(RuntimeError):
    """tree-sitter bindings are not importable in this Python environment."""


@dataclass(frozen=True)
class _Symbol:
    name: str
    file: str
    range: Range
    kind: SymbolKind
    scope: str | None


@dataclass(frozen=True)
class _ParsedFile:
    path: str
    source: bytes
    tree: Any


def tree_sitter_available() -> bool:
    return _IMPORT_ERROR is None


def create_treesitter_provider(
    source_roots: Sequence[str | Path],
) -> TreeSitterProvider | None:
    """Return a provider when bindings are available, otherwise degrade to None."""

    if not tree_sitter_available():
        return None
    return TreeSitterProvider(source_roots)


class TreeSitterProvider:
    """Implementation of the P1 SyntacticProvider protocol."""

    def __init__(self, source_roots: Sequence[str | Path]):
        if not tree_sitter_available():
            raise TreeSitterUnavailable(str(_IMPORT_ERROR))
        self._source_roots = tuple(Path(root).resolve() for root in source_roots)
        self._parsers: dict[str, Any] = {}
        self._cache: dict[str, _ParsedFile] = {}

    def search_candidates(
        self,
        symbol: str,
        *,
        kind_filter: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[Candidate, ...]:
        matches = [
            self._candidate(symbol, found, kind_filter=kind_filter, query_file=None)
            for found in self._iter_symbols()
            if found.name == symbol
        ]
        return tuple(matches[offset : offset + limit])

    def candidates_near(
        self,
        symbol: str,
        file: str,
        pos: Pos,
        *,
        limit: int = 100,
    ) -> tuple[Candidate, ...]:
        query_file = str(Path(file).resolve())
        query_kind = self._infer_symbol_kind(query_file, pos)
        query_scope = self._scope_at(query_file, pos)
        matches = [
            self._candidate(
                symbol,
                found,
                kind_filter=query_kind.value if query_kind is not None else None,
                query_file=query_file,
                query_scope=query_scope,
            )
            for found in self._iter_symbols(extra_files=(query_file,))
            if found.name == symbol
        ]
        matches.sort(key=lambda candidate: candidate.relevance_score or 0, reverse=True)
        return tuple(matches[:limit])

    def is_preprocessor_location(self, file: str, pos: Pos) -> bool:
        parsed = self._parse_file(file)
        if parsed is None:
            return True
        node = self._smallest_named_node_at(parsed.tree.root_node, pos)
        while node is not None:
            if node.type in {"preproc_def", "preproc_function_def"}:
                return not self._is_preprocessor_definition_name(node, pos)
            if node.type in _PREPROC_NODE_TYPES:
                return True
            node = node.parent
        return False

    def _candidate(
        self,
        symbol: str,
        found: _Symbol,
        *,
        kind_filter: str | None,
        query_file: str | None,
        query_scope: str | None = None,
    ) -> Candidate:
        score = 0
        if found.name == symbol:
            score += 15
        if query_file is not None and found.file == query_file:
            score += 10
        if (
            query_scope is not None
            and found.scope is not None
            and query_scope == found.scope
        ):
            score += 10
        if _matches_kind_filter(found.kind, kind_filter):
            score += 5
        return Candidate(
            LocationResult(
                SymbolId(None, found.name, found.file, found.range.start),
                found.range,
                found.kind.value,
            ),
            _candidate_credibility(found.kind),
            score,
        )

    def _iter_symbols(self, extra_files: Iterable[str] = ()) -> tuple[_Symbol, ...]:
        symbols: list[_Symbol] = []
        seen_files: set[str] = set()
        for file in self._source_files():
            seen_files.add(file)
            parsed = self._parse_file(file)
            if parsed is not None:
                symbols.extend(_extract_symbols(parsed))
        for file in extra_files:
            if file in seen_files:
                continue
            parsed = self._parse_file(file)
            if parsed is not None:
                symbols.extend(_extract_symbols(parsed))
        return tuple(symbols)

    def _source_files(self) -> tuple[str, ...]:
        files: list[str] = []
        for root in self._source_roots:
            if root.is_file() and root.suffix in _SOURCE_EXTENSIONS:
                files.append(str(root))
                continue
            if not root.is_dir():
                continue
            files.extend(
                str(path.resolve())
                for path in root.rglob("*")
                if path.is_file() and path.suffix in _SOURCE_EXTENSIONS
            )
        return tuple(sorted(set(files)))

    def _parse_file(self, file: str | Path) -> _ParsedFile | None:
        path = str(Path(file).resolve())
        cached = self._cache.get(path)
        if cached is not None:
            return cached
        source_path = Path(path)
        if not source_path.is_file() or source_path.suffix not in _SOURCE_EXTENSIONS:
            return None
        source = source_path.read_bytes()
        parser = self._parser_for_suffix(source_path.suffix)
        tree = parser.parse(source)
        parsed = _ParsedFile(path, source, tree)
        self._cache[path] = parsed
        return parsed

    def _parser_for_suffix(self, suffix: str) -> Any:
        language_key = "cpp" if suffix in _CPP_EXTENSIONS else "c"
        parser = self._parsers.get(language_key)
        if parser is not None:
            return parser
        language_capsule = (
            _tree_sitter_cpp.language()
            if language_key == "cpp"
            else _tree_sitter_c.language()
        )
        parser = _Parser(_Language(language_capsule))
        self._parsers[language_key] = parser
        return parser

    def _infer_symbol_kind(self, file: str, pos: Pos) -> SymbolKind | None:
        parsed = self._parse_file(file)
        if parsed is None:
            return None
        node = self._smallest_named_node_at(parsed.tree.root_node, pos)
        if node is None:
            return None
        if node.type == "type_identifier":
            return SymbolKind.TYPE
        if _has_ancestor(node, {"call_expression", "function_declarator"}):
            return SymbolKind.ORDINARY_FUNCTION
        if _has_ancestor(node, {"preproc_def", "preproc_function_def"}):
            return SymbolKind.MACRO
        if node.type in {"identifier", "field_identifier"}:
            return SymbolKind.ORDINARY_VARIABLE
        return None

    def _scope_at(self, file: str, pos: Pos) -> str | None:
        parsed = self._parse_file(file)
        if parsed is None:
            return None
        node = self._smallest_named_node_at(parsed.tree.root_node, pos)
        while node is not None:
            if node.type == "function_definition":
                name = _function_name(node, parsed.source)
                if name is not None:
                    return f"{parsed.path}:{name}"
            node = node.parent
        return None

    def _smallest_named_node_at(self, node: Any, pos: Pos) -> Any | None:
        if not _contains_pos(node, pos):
            return None
        for child in node.named_children:
            found = self._smallest_named_node_at(child, pos)
            if found is not None:
                return found
        return node

    def _is_preprocessor_definition_name(self, preproc_node: Any, pos: Pos) -> bool:
        for child in preproc_node.named_children:
            if child.type == "identifier" and _contains_pos(child, pos):
                return True
        return False


def _extract_symbols(parsed: _ParsedFile) -> tuple[_Symbol, ...]:
    symbols: list[_Symbol] = []

    def visit(node: Any, scope: str | None) -> None:
        next_scope = scope
        if node.type == "function_definition":
            function_symbol = _symbol_from_function(node, parsed, scope)
            if function_symbol is not None:
                symbols.append(function_symbol)
                next_scope = f"{parsed.path}:{function_symbol.name}"
        elif node.type in {"preproc_def", "preproc_function_def"}:
            macro = _symbol_from_preprocessor_definition(node, parsed)
            if macro is not None:
                symbols.append(macro)
        elif node.type == "type_definition":
            typedef = _symbol_from_type_definition(node, parsed, scope)
            if typedef is not None:
                symbols.append(typedef)
        elif node.type == "struct_specifier":
            struct_symbol = _symbol_from_struct(node, parsed, scope)
            if struct_symbol is not None:
                symbols.append(struct_symbol)
        elif node.type == "declaration":
            symbols.extend(_symbols_from_declaration(node, parsed, scope))

        for child in node.named_children:
            visit(child, next_scope)

    visit(parsed.tree.root_node, None)
    return tuple(_dedupe_symbols(symbols))


def _symbol_from_function(
    node: Any, parsed: _ParsedFile, scope: str | None
) -> _Symbol | None:
    name = _function_name(node, parsed.source)
    if name is None:
        return None
    name_node = _first_descendant(node, "identifier")
    if name_node is None:
        return None
    return _symbol_from_node(name_node, parsed, SymbolKind.ORDINARY_FUNCTION, scope)


def _symbol_from_preprocessor_definition(
    node: Any, parsed: _ParsedFile
) -> _Symbol | None:
    for child in node.named_children:
        if child.type == "identifier":
            return _symbol_from_node(child, parsed, SymbolKind.MACRO, None)
    return None


def _symbol_from_type_definition(
    node: Any, parsed: _ParsedFile, scope: str | None
) -> _Symbol | None:
    type_nodes = [
        child for child in node.named_children if child.type == "type_identifier"
    ]
    if not type_nodes:
        return None
    return _symbol_from_node(type_nodes[-1], parsed, SymbolKind.TYPE, scope)


def _symbol_from_struct(
    node: Any, parsed: _ParsedFile, scope: str | None
) -> _Symbol | None:
    for child in node.named_children:
        if child.type == "type_identifier":
            return _symbol_from_node(child, parsed, SymbolKind.TYPE, scope)
    return None


def _symbols_from_declaration(
    node: Any, parsed: _ParsedFile, scope: str | None
) -> tuple[_Symbol, ...]:
    if _first_descendant(node, "function_declarator") is not None:
        return ()
    symbols: list[_Symbol] = []
    for descendant in _descendants(node):
        if descendant.type != "identifier":
            continue
        if _has_ancestor(descendant, {"call_expression"}):
            continue
        symbols.append(
            _symbol_from_node(descendant, parsed, SymbolKind.ORDINARY_VARIABLE, scope)
        )
    return tuple(symbol for symbol in symbols if symbol is not None)


def _symbol_from_node(
    node: Any, parsed: _ParsedFile, kind: SymbolKind, scope: str | None
) -> _Symbol:
    name = _node_text(node, parsed.source)
    return _Symbol(
        name,
        parsed.path,
        _range_from_node(node),
        kind,
        scope,
    )


def _candidate_credibility(kind: SymbolKind) -> Credibility:
    return validate(
        Credibility(
            source=Source.TREE_SITTER,
            certainty=Certainty.SYNTACTIC,
            relation=Relation.NA,
            resolved=Resolved.RESOLVED,
            query_kind=QueryKind.ENTITY,
            dependency=DependencyScope.not_applicable(),
            coverage=Coverage(index_scope=IndexScope.EXTERNAL_UNKNOWN),
            active_config=ActiveConfig.UNKNOWN,
            symbol_kind=kind,
        )
    )


def _range_from_node(node: Any) -> Range:
    return Range(
        Pos(node.start_point.row, node.start_point.column),
        Pos(node.end_point.row, node.end_point.column),
    )


def _node_text(node: Any, source: bytes) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _function_name(node: Any, source: bytes) -> str | None:
    declarator = _first_descendant(node, "function_declarator")
    if declarator is None:
        return None
    identifier = _first_descendant(declarator, "identifier")
    return None if identifier is None else _node_text(identifier, source)


def _first_descendant(node: Any, node_type: str) -> Any | None:
    if node.type == node_type:
        return node
    for child in node.named_children:
        found = _first_descendant(child, node_type)
        if found is not None:
            return found
    return None


def _descendants(node: Any) -> tuple[Any, ...]:
    found: list[Any] = []

    def visit(current: Any) -> None:
        found.append(current)
        for child in current.named_children:
            visit(child)

    visit(node)
    return tuple(found)


def _dedupe_symbols(symbols: Iterable[_Symbol]) -> tuple[_Symbol, ...]:
    seen: set[tuple[str, str, int, int, SymbolKind]] = set()
    deduped: list[_Symbol] = []
    for symbol in symbols:
        key = (
            symbol.name,
            symbol.file,
            symbol.range.start.line,
            symbol.range.start.character,
            symbol.kind,
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(symbol)
    return tuple(deduped)


def _contains_pos(node: Any, pos: Pos) -> bool:
    start = (node.start_point.row, node.start_point.column)
    end = (node.end_point.row, node.end_point.column)
    point = (pos.line, pos.character)
    return start <= point < end


def _has_ancestor(node: Any, node_types: set[str]) -> bool:
    current = node.parent
    while current is not None:
        if current.type in node_types:
            return True
        current = current.parent
    return False


def _matches_kind_filter(kind: SymbolKind, kind_filter: str | None) -> bool:
    if kind_filter is None:
        return False
    return kind.value == kind_filter
