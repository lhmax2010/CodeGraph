"""
factories.py — 构造合法 Credibility 的便利工厂。

直接 new Credibility(...) 容易拼出非法组合;这些工厂封装"引擎+查询类型"的
典型合法形态,并在返回前跑一遍 check_invariants(),把错误挡在构造期。
引擎包装器(clangd / tree-sitter adapter)应优先用这些工厂,而非裸构造。
"""

from __future__ import annotations

from .credibility import (
    Credibility, Source, Certainty, Relation, Resolved, QueryKind,
    DependencyScope, DepScopeLevel, DepStatus, validate,
)


# ---- clangd(语义级)----

def clangd_entity_resolved(dep: DependencyScope) -> Credibility:
    """clangd 成功解析一个实体(定义/符号位置)。"""
    return validate(Credibility(
        source=Source.CLANGD, certainty=Certainty.SEMANTIC,
        relation=Relation.NA, resolved=Resolved.RESOLVED,
        query_kind=QueryKind.ENTITY, dependency=dep))


def clangd_relation_must(dep: DependencyScope) -> Credibility:
    """clangd 语义确认的必然关系(精确调用边)。要求依赖闭包齐全。"""
    return validate(Credibility(
        source=Source.CLANGD, certainty=Certainty.SEMANTIC,
        relation=Relation.MUST, resolved=Resolved.RESOLVED,
        query_kind=QueryKind.RELATION, dependency=dep))


def clangd_relation_may(dep: DependencyScope, *,
                        blind_spot_affects: bool = False) -> Credibility:
    """clangd 给出"可能"关系(如经盲区,只能 may)。
    若盲区影响了本结果,certainty 必须降为 syntactic(INV5):此时关系已非纯
    语义确认。"""
    cert = Certainty.SYNTACTIC if blind_spot_affects else Certainty.SEMANTIC
    return validate(Credibility(
        source=Source.CLANGD, certainty=cert,
        relation=Relation.MAY, resolved=Resolved.RESOLVED,
        query_kind=QueryKind.RELATION, dependency=dep,
        blind_spot_affects_result=blind_spot_affects))


def clangd_not_found(query_kind: QueryKind, dep: DependencyScope) -> Credibility:
    """clangd 确认不存在(诚实的 not_found)。仅当依赖闭包 complete 才合法(INV6)。"""
    return validate(Credibility(
        source=Source.CLANGD, certainty=Certainty.SEMANTIC,
        relation=Relation.NA, resolved=Resolved.NOT_FOUND,
        query_kind=query_kind, dependency=dep))


def clangd_unresolved(query_kind: QueryKind, dep: DependencyScope, *,
                      blind_spot_affects: bool = False) -> Credibility:
    """clangd 看不到(依赖缺失/盲区)。这是"看不到",不是"没有"。"""
    cert = Certainty.SYNTACTIC if blind_spot_affects else Certainty.SEMANTIC
    return validate(Credibility(
        source=Source.CLANGD, certainty=cert,
        relation=Relation.NA, resolved=Resolved.UNRESOLVED,
        query_kind=query_kind, dependency=dep,
        blind_spot_affects_result=blind_spot_affects))


# ---- tree-sitter(语法级)----

def treesitter_entity_resolved() -> Credibility:
    """tree-sitter 语法定位到实体。永远 syntactic,依赖 n/a。"""
    return validate(Credibility(
        source=Source.TREE_SITTER, certainty=Certainty.SYNTACTIC,
        relation=Relation.NA, resolved=Resolved.RESOLVED,
        query_kind=QueryKind.ENTITY, dependency=DependencyScope.not_applicable()))


def treesitter_relation_may() -> Credibility:
    """tree-sitter 语法层面的关系猜测,只能 may,绝不能 must(INV8)。"""
    return validate(Credibility(
        source=Source.TREE_SITTER, certainty=Certainty.SYNTACTIC,
        relation=Relation.MAY, resolved=Resolved.RESOLVED,
        query_kind=QueryKind.RELATION, dependency=DependencyScope.not_applicable()))


def treesitter_unresolved(query_kind: QueryKind) -> Credibility:
    """tree-sitter 语法层面没看到。注意:tree-sitter 的"没看到"只能是 unresolved,
    不能是 not_found —— 它无语义能力断言"确实不存在"(见 INV12)。"""
    return validate(Credibility(
        source=Source.TREE_SITTER, certainty=Certainty.SYNTACTIC,
        relation=Relation.NA, resolved=Resolved.UNRESOLVED,
        query_kind=query_kind, dependency=DependencyScope.not_applicable()))
