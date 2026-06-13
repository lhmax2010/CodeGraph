"""
factories.py — 构造合法 Credibility 的便利工厂。

直接 new Credibility(...) 容易拼出非法组合;这些工厂封装"引擎+查询类型"的
典型合法形态,并在返回前跑一遍 check_invariants(),把错误挡在构造期。
引擎包装器(clangd / tree-sitter adapter)应优先用这些工厂,而非裸构造。
"""

from __future__ import annotations

from .credibility import (
    ActiveConfig,
    Certainty,
    Coverage,
    Credibility,
    DepScopeLevel,
    DepStatus,
    DependencyScope,
    IndexBackend,
    IndexHealth,
    IndexScope,
    NegativeScope,
    QueryKind,
    Relation,
    Resolved,
    Source,
    SymbolKind,
    validate,
)

# ---- clangd(语义级)----


def _not_found_coverage(
    negative_scope: NegativeScope = NegativeScope.CURRENT_TU,
    index_scope: IndexScope = IndexScope.CURRENT_TU,
) -> Coverage:
    return Coverage(
        index_scope=index_scope,
        is_exhaustive_within_scope=True,
        negative_scope=negative_scope,
    )


def clangd_entity_resolved(
    dep: DependencyScope,
    *,
    build_config_id: str = "unknown",
    coverage: Coverage | None = None,
    active_config: ActiveConfig = ActiveConfig.UNKNOWN,
    symbol_kind: SymbolKind = SymbolKind.UNKNOWN,
    index_health: IndexHealth = IndexHealth.UNKNOWN,
    index_backend: IndexBackend = IndexBackend.BACKGROUND_INDEX,
) -> Credibility:
    """clangd 成功解析一个实体(定义/符号位置)。"""
    return validate(
        Credibility(
            source=Source.CLANGD,
            certainty=Certainty.SEMANTIC,
            relation=Relation.NA,
            resolved=Resolved.RESOLVED,
            query_kind=QueryKind.ENTITY,
            dependency=dep,
            coverage=coverage or Coverage(),
            active_config=active_config,
            build_config_id=build_config_id,
            symbol_kind=symbol_kind,
            index_health=index_health,
            index_backend=index_backend,
        )
    )


def clangd_relation_must(
    dep: DependencyScope,
    *,
    build_config_id: str = "unknown",
    coverage: Coverage | None = None,
    active_config: ActiveConfig = ActiveConfig.UNKNOWN,
    symbol_kind: SymbolKind = SymbolKind.UNKNOWN,
    index_health: IndexHealth = IndexHealth.UNKNOWN,
    index_backend: IndexBackend = IndexBackend.BACKGROUND_INDEX,
) -> Credibility:
    """clangd 语义确认的必然关系(精确调用边)。

    调用方应只在依赖闭包足以支撑该调用边时使用；工厂本身不额外强制
    dep.status=complete，因为冻结不变量只要求 must => semantic + resolved。
    """
    return validate(
        Credibility(
            source=Source.CLANGD,
            certainty=Certainty.SEMANTIC,
            relation=Relation.MUST,
            resolved=Resolved.RESOLVED,
            query_kind=QueryKind.RELATION,
            dependency=dep,
            coverage=coverage or Coverage(),
            active_config=active_config,
            build_config_id=build_config_id,
            symbol_kind=symbol_kind,
            index_health=index_health,
            index_backend=index_backend,
        )
    )


def clangd_relation_may(
    dep: DependencyScope,
    *,
    blind_spot_affects: bool = False,
    build_config_id: str = "unknown",
    coverage: Coverage | None = None,
    active_config: ActiveConfig = ActiveConfig.UNKNOWN,
    symbol_kind: SymbolKind = SymbolKind.UNKNOWN,
    index_health: IndexHealth = IndexHealth.UNKNOWN,
    index_backend: IndexBackend = IndexBackend.BACKGROUND_INDEX,
) -> Credibility:
    """clangd 给出"可能"关系(如经盲区,只能 may)。
    若盲区影响了本结果,certainty 必须降为 syntactic(INV5):此时关系已非纯
    语义确认。"""
    cert = Certainty.SYNTACTIC if blind_spot_affects else Certainty.SEMANTIC
    return validate(
        Credibility(
            source=Source.CLANGD,
            certainty=cert,
            relation=Relation.MAY,
            resolved=Resolved.RESOLVED,
            query_kind=QueryKind.RELATION,
            dependency=dep,
            coverage=coverage or Coverage(),
            active_config=active_config,
            build_config_id=build_config_id,
            symbol_kind=symbol_kind,
            index_health=index_health,
            index_backend=index_backend,
            blind_spot_affects_result=blind_spot_affects,
        )
    )


def clangd_not_found(
    query_kind: QueryKind,
    dep: DependencyScope,
    *,
    build_config_id: str = "unknown",
    coverage: Coverage | None = None,
    active_config: ActiveConfig = ActiveConfig.UNKNOWN,
    symbol_kind: SymbolKind = SymbolKind.ORDINARY_FUNCTION,
    index_health: IndexHealth = IndexHealth.COMPLETE,
    index_backend: IndexBackend = IndexBackend.BACKGROUND_INDEX,
) -> Credibility:
    """clangd 确认不存在(诚实的 not_found)。仅当依赖闭包 complete 才合法(INV6)。"""
    return validate(
        Credibility(
            source=Source.CLANGD,
            certainty=Certainty.SEMANTIC,
            relation=Relation.NA,
            resolved=Resolved.NOT_FOUND,
            query_kind=query_kind,
            dependency=dep,
            coverage=coverage or _not_found_coverage(),
            active_config=active_config,
            build_config_id=build_config_id,
            symbol_kind=symbol_kind,
            index_health=index_health,
            index_backend=index_backend,
        )
    )


def clangd_unresolved(
    query_kind: QueryKind,
    dep: DependencyScope,
    *,
    blind_spot_affects: bool = False,
    build_config_id: str = "unknown",
    coverage: Coverage | None = None,
    active_config: ActiveConfig = ActiveConfig.UNKNOWN,
    symbol_kind: SymbolKind = SymbolKind.UNKNOWN,
    index_health: IndexHealth = IndexHealth.UNKNOWN,
    index_backend: IndexBackend = IndexBackend.BACKGROUND_INDEX,
) -> Credibility:
    """clangd 看不到(依赖缺失/盲区)。这是"看不到",不是"没有"。"""
    cert = Certainty.SYNTACTIC if blind_spot_affects else Certainty.SEMANTIC
    return validate(
        Credibility(
            source=Source.CLANGD,
            certainty=cert,
            relation=Relation.NA,
            resolved=Resolved.UNRESOLVED,
            query_kind=query_kind,
            dependency=dep,
            coverage=coverage or Coverage(),
            active_config=active_config,
            build_config_id=build_config_id,
            symbol_kind=symbol_kind,
            index_health=index_health,
            index_backend=index_backend,
            blind_spot_affects_result=blind_spot_affects,
        )
    )


# ---- tree-sitter(语法级)----


def treesitter_entity_resolved() -> Credibility:
    """tree-sitter 语法定位到实体。永远 syntactic,依赖 n/a。"""
    return validate(
        Credibility(
            source=Source.TREE_SITTER,
            certainty=Certainty.SYNTACTIC,
            relation=Relation.NA,
            resolved=Resolved.RESOLVED,
            query_kind=QueryKind.ENTITY,
            dependency=DependencyScope.not_applicable(),
            active_config=ActiveConfig.UNKNOWN,
        )
    )


def treesitter_relation_may() -> Credibility:
    """tree-sitter 语法层面的关系猜测,只能 may,绝不能 must(INV8)。"""
    return validate(
        Credibility(
            source=Source.TREE_SITTER,
            certainty=Certainty.SYNTACTIC,
            relation=Relation.MAY,
            resolved=Resolved.RESOLVED,
            query_kind=QueryKind.RELATION,
            dependency=DependencyScope.not_applicable(),
            active_config=ActiveConfig.UNKNOWN,
        )
    )


def treesitter_unresolved(query_kind: QueryKind) -> Credibility:
    """tree-sitter 语法层面没看到。注意:tree-sitter 的"没看到"只能是 unresolved,
    不能是 not_found —— 它无语义能力断言"确实不存在"(见 INV12)。"""
    return validate(
        Credibility(
            source=Source.TREE_SITTER,
            certainty=Certainty.SYNTACTIC,
            relation=Relation.NA,
            resolved=Resolved.UNRESOLVED,
            query_kind=query_kind,
            dependency=DependencyScope.not_applicable(),
            active_config=ActiveConfig.UNKNOWN,
        )
    )


def make_error_credibility(query_kind: QueryKind) -> Credibility:
    """FAILED/INVALID_REQUEST 等非 OK 状态的中性占位 credibility。"""
    return validate(
        Credibility(
            source=Source.CLANGD,
            certainty=Certainty.SYNTACTIC,
            relation=Relation.NA,
            resolved=Resolved.UNRESOLVED,
            query_kind=query_kind,
            symbol_kind=SymbolKind.UNKNOWN,
            dependency=DependencyScope(
                level=DepScopeLevel.NOT_APPLICABLE,
                status=DepStatus.UNKNOWN,
                missing=(),
            ),
            coverage=Coverage(
                index_scope=IndexScope.EXTERNAL_UNKNOWN,
                is_exhaustive_within_scope=False,
                negative_scope=NegativeScope.NONE,
            ),
            active_config=ActiveConfig.UNKNOWN,
            index_health=IndexHealth.UNKNOWN,
            index_backend=IndexBackend.BACKGROUND_INDEX,
            blind_spot_nearby=False,
            blind_spot_affects_result=False,
            consumer_hint=None,
        )
    )
