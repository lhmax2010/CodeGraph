"""
test_credibility.py — 逐条钉死不变量。

原则:每条不变量都要有 (a) 至少一个被它正确拒绝的非法组合,
(b) 紧邻的合法组合不被误杀。不变量不被测到 = 等于没有不变量。
纯标准库 + pytest,不依赖 pydantic(便于内网环境复用)。
"""

import pytest

from codegraph.credibility import (
    Credibility, Source, Certainty, Relation, Resolved, QueryKind,
    DependencyScope, DepScopeLevel, DepStatus,
    InvariantError, check_invariants, soft_warnings,
)
from codegraph import factories as F


DEP_OK = DependencyScope.complete()
DEP_UNK = DependencyScope.unknown()
DEP_INC = DependencyScope.incomplete(("ri-module-api.h",))
DEP_NA = DependencyScope.not_applicable()


def mk(**kw) -> Credibility:
    """构造一个 Credibility,缺省填一组合法基线,再用 kw 覆盖。"""
    base = dict(
        source=Source.CLANGD, certainty=Certainty.SEMANTIC,
        relation=Relation.NA, resolved=Resolved.RESOLVED,
        query_kind=QueryKind.ENTITY, dependency=DEP_OK,
    )
    base.update(kw)
    return Credibility(**base)


def assert_violates(code_substr: str, **kw):
    with pytest.raises(InvariantError) as ei:
        check_invariants(mk(**kw))
    assert code_substr in ei.value.code, f"expected {code_substr}, got {ei.value.code}"


# ---------------------------------------------------------------------------
# 逐条不变量:非法被拒
# ---------------------------------------------------------------------------

def test_inv1_treesitter_must_be_syntactic():
    assert_violates("INV1", source=Source.TREE_SITTER, certainty=Certainty.SEMANTIC,
                    dependency=DEP_NA)

def test_inv2_semantic_must_be_clangd():
    # semantic + tree-sitter 先被 INV1 抓(等价违规);构造一个只触 INV2 的:
    # source 必须非 clangd 又非 tree-sitter 不可能,所以 INV2 实际由 INV1 兜住。
    # 这里验证 semantic 必来自 clangd 的正向:clangd+semantic 合法。
    check_invariants(mk(source=Source.CLANGD, certainty=Certainty.SEMANTIC))

def test_inv3_unresolved_relation_must_be_na():
    assert_violates("INV3_4", resolved=Resolved.UNRESOLVED, relation=Relation.MAY,
                    query_kind=QueryKind.RELATION)

def test_inv4_notfound_relation_must_be_na():
    assert_violates("INV3_4", resolved=Resolved.NOT_FOUND, relation=Relation.MAY,
                    query_kind=QueryKind.RELATION, dependency=DEP_OK)

def test_inv5_blindspot_affects_forbids_semantic():
    assert_violates("INV5", blind_spot_affects_result=True, certainty=Certainty.SEMANTIC)

def test_inv5_blindspot_affects_forbids_must():
    assert_violates("INV5", blind_spot_affects_result=True, certainty=Certainty.SYNTACTIC,
                    source=Source.TREE_SITTER, relation=Relation.MUST,
                    query_kind=QueryKind.RELATION, dependency=DEP_NA)

def test_inv6_notfound_requires_complete_deps():
    assert_violates("INV6", resolved=Resolved.NOT_FOUND, relation=Relation.NA,
                    query_kind=QueryKind.ENTITY, dependency=DEP_INC)

def test_inv7_unknown_deps_forbid_notfound():
    # unknown deps + not_found:INV6 先抓(unknown != complete),验证确实被挡
    with pytest.raises(InvariantError) as ei:
        check_invariants(mk(resolved=Resolved.NOT_FOUND, relation=Relation.NA,
                            query_kind=QueryKind.ENTITY, dependency=DEP_UNK))
    assert ei.value.code in ("INV6", "INV7")

def test_inv8_must_requires_semantic():
    assert_violates("INV8", relation=Relation.MUST, certainty=Certainty.SYNTACTIC,
                    source=Source.TREE_SITTER, query_kind=QueryKind.RELATION,
                    resolved=Resolved.RESOLVED, dependency=DEP_NA)

def test_inv9_entity_relation_must_be_na():
    assert_violates("INV9", query_kind=QueryKind.ENTITY, relation=Relation.MAY,
                    resolved=Resolved.RESOLVED)

def test_inv10_treesitter_not_incomplete():
    assert_violates("INV10", source=Source.TREE_SITTER, certainty=Certainty.SYNTACTIC,
                    dependency=DEP_INC)

def test_inv11_must_requires_resolved():
    # must + 非 resolved。但 not_found/unresolved 已被 INV3_4 要求 relation=n/a,
    # 所以 must+unresolved 会先撞 INV3_4。验证它确实被某条挡住:
    with pytest.raises(InvariantError):
        check_invariants(mk(relation=Relation.MUST, resolved=Resolved.UNRESOLVED,
                            query_kind=QueryKind.RELATION))

def test_inv12_treesitter_cannot_notfound():
    assert_violates("INV12", source=Source.TREE_SITTER, certainty=Certainty.SYNTACTIC,
                    resolved=Resolved.NOT_FOUND, relation=Relation.NA,
                    query_kind=QueryKind.ENTITY, dependency=DEP_NA)


# ---------------------------------------------------------------------------
# 工厂:合法组合全部放行
# ---------------------------------------------------------------------------

def test_factory_clangd_entity_resolved():
    F.clangd_entity_resolved(DEP_OK)

def test_factory_clangd_relation_must():
    F.clangd_relation_must(DEP_OK)

def test_factory_clangd_relation_may():
    F.clangd_relation_may(DEP_OK)
    F.clangd_relation_may(DEP_OK, blind_spot_affects=True)  # may+盲区影响 合法

def test_factory_clangd_not_found_complete_ok():
    F.clangd_not_found(QueryKind.ENTITY, DEP_OK)

def test_factory_clangd_not_found_incomplete_rejected():
    with pytest.raises(InvariantError):
        F.clangd_not_found(QueryKind.ENTITY, DEP_INC)

def test_factory_clangd_not_found_unknown_rejected():
    with pytest.raises(InvariantError):
        F.clangd_not_found(QueryKind.ENTITY, DEP_UNK)

def test_factory_clangd_unresolved():
    F.clangd_unresolved(QueryKind.ENTITY, DEP_INC)
    F.clangd_unresolved(QueryKind.RELATION, DEP_UNK, blind_spot_affects=True)

def test_factory_treesitter_entity():
    F.treesitter_entity_resolved()

def test_factory_treesitter_relation_may():
    F.treesitter_relation_may()

def test_factory_treesitter_unresolved():
    F.treesitter_unresolved(QueryKind.RELATION)


# ---------------------------------------------------------------------------
# 关键场景:防虚假否定(把"看不到"误当"没有")
# ---------------------------------------------------------------------------

def test_false_negative_guard_incomplete_dep():
    """依赖不全时不允许 not_found —— 必须降级为 unresolved。"""
    # 非法:依赖不全却说 not_found
    with pytest.raises(InvariantError):
        F.clangd_not_found(QueryKind.ENTITY, DEP_INC)
    # 合法替代:同场景用 unresolved
    c = F.clangd_unresolved(QueryKind.ENTITY, DEP_INC)
    assert c.resolved == Resolved.UNRESOLVED

def test_false_negative_guard_treesitter():
    """tree-sitter 的'没看到'不能伪装成'没有'。"""
    with pytest.raises(InvariantError):
        check_invariants(Credibility(
            source=Source.TREE_SITTER, certainty=Certainty.SYNTACTIC,
            relation=Relation.NA, resolved=Resolved.NOT_FOUND,
            query_kind=QueryKind.ENTITY, dependency=DEP_NA))

def test_callback_honest_not_found():
    """PoC S5 场景:clangd 对依赖齐全的代码,回调确实无静态调用者 -> 合法 not_found。"""
    c = F.clangd_not_found(QueryKind.RELATION, DEP_OK)
    assert c.resolved == Resolved.NOT_FOUND
    assert c.relation == Relation.NA


# ---------------------------------------------------------------------------
# soft warnings(非阻断)
# ---------------------------------------------------------------------------

def test_soft_warning_clangd_complete_but_unresolved():
    c = F.clangd_unresolved(QueryKind.ENTITY, DEP_OK)  # 依赖齐全却 unresolved
    w = soft_warnings(c)
    assert any("corner case" in x for x in w)

def test_soft_warning_blindspot_nearby_not_affecting():
    c = Credibility(
        source=Source.CLANGD, certainty=Certainty.SEMANTIC,
        relation=Relation.NA, resolved=Resolved.RESOLVED,
        query_kind=QueryKind.ENTITY, dependency=DEP_OK,
        blind_spot_nearby=True, blind_spot_affects_result=False)
    check_invariants(c)  # 合法:附近有盲区但不影响本结果,仍可 semantic
    w = soft_warnings(c)
    assert any("nearby" in x for x in w)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
