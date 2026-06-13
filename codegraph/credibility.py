"""
credibility.py — CodeGraph 查询结果的可信度元数据模型。

这是 CodeGraph 区别于普通 LSP 封装的核心:每条查询结果都携带"它有多可信"的
元数据,由上层(诊断系统等消费方)据此决定它能支撑多强的结论。CodeGraph 自己
只做诚实标注,不做"够不够判责"这类业务判断(那是消费方的事)。

设计经过多轮多模型交叉 review,关键演化:
  - dependency_complete 从 bool 升级为结构化 DependencyScope(scope/status/missing),
    消除"全局完整 vs 本结果所需依赖闭包完整"的歧义。
  - blind_spot 拆成 nearby(信息性,附近存在盲区)+ affects_result(本结果是否
    真受盲区影响,只有它进硬不变量),避免误杀"附近有盲区但本结果仍可语义确认"。
  - 引入 query_kind(entity/relation),由接口自动填,使 relation 字段的合法性清晰。

不变量在 check_invariants() 中以**纯标准库**实现(不依赖 pydantic),便于在
仅有 stdlib 的环境(如内网 Cline)中复用与测试;pydantic 模型只是其上的便利封装。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# 枚举(用 str Enum,JSON 友好)
# ---------------------------------------------------------------------------

class Source(str, Enum):
    CLANGD = "clangd"
    TREE_SITTER = "tree-sitter"


class Certainty(str, Enum):
    SEMANTIC = "semantic"
    SYNTACTIC = "syntactic"


class Relation(str, Enum):
    MUST = "must"
    MAY = "may"
    NA = "n/a"


class Resolved(str, Enum):
    RESOLVED = "resolved"      # 成功解析到结果
    NOT_FOUND = "not_found"    # 成功解析,且确实不存在(诚实的"没有")
    UNRESOLVED = "unresolved"  # 解析不了(盲区/依赖缺失)——是"看不到",不是"没有"


class QueryKind(str, Enum):
    ENTITY = "entity"       # 符号定位/定义/引用列表 —— relation 天然 n/a
    RELATION = "relation"   # 调用边/别名/数据流 —— relation 才有意义


# DependencyScope
class DepScopeLevel(str, Enum):
    QUERY_LOCAL = "query_local"            # 仅本结果所需依赖闭包
    TRANSLATION_UNIT = "translation_unit"  # 整个 TU
    GLOBAL = "global"                      # 整个工程
    NOT_APPLICABLE = "n/a"                 # 不依赖编译环境(tree-sitter)


class DepStatus(str, Enum):
    COMPLETE = "complete"      # 该 scope 内依赖齐全
    INCOMPLETE = "incomplete"  # 有缺失(missing 非空)
    UNKNOWN = "unknown"        # 无法判定缺失是否影响本结果 —— 存疑从严


@dataclass(frozen=True)
class DependencyScope:
    """支撑本条结果的依赖闭包完整性。

    关键语义:这里说的"完整"不是整个代码库/工程,而是"足以支撑本条结果的依赖闭包"。
    无法判断缺失依赖是否影响本结果时,status 必须是 UNKNOWN,不得乐观标 COMPLETE。
    """
    level: DepScopeLevel
    status: DepStatus
    missing: tuple[str, ...] = ()   # 缺失的头/TU 列表;仅 INCOMPLETE 时应非空

    @staticmethod
    def not_applicable() -> "DependencyScope":
        """tree-sitter 等不依赖编译环境的引擎用这个。"""
        return DependencyScope(level=DepScopeLevel.NOT_APPLICABLE,
                               status=DepStatus.COMPLETE)

    @staticmethod
    def complete(level: DepScopeLevel = DepScopeLevel.QUERY_LOCAL) -> "DependencyScope":
        return DependencyScope(level=level, status=DepStatus.COMPLETE)

    @staticmethod
    def incomplete(missing: tuple[str, ...],
                   level: DepScopeLevel = DepScopeLevel.QUERY_LOCAL) -> "DependencyScope":
        return DependencyScope(level=level, status=DepStatus.INCOMPLETE, missing=missing)

    @staticmethod
    def unknown(level: DepScopeLevel = DepScopeLevel.QUERY_LOCAL) -> "DependencyScope":
        return DependencyScope(level=level, status=DepStatus.UNKNOWN)


# ---------------------------------------------------------------------------
# 核心数据(纯 dataclass,不依赖 pydantic)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Credibility:
    """一条查询结果的可信度元数据。"""
    source: Source
    certainty: Certainty
    relation: Relation
    resolved: Resolved
    query_kind: QueryKind
    dependency: DependencyScope
    blind_spot_nearby: bool = False     # 附近存在盲区(信息性,不触发降级)
    blind_spot_affects_result: bool = False  # 盲区影响本结果(进硬不变量)
    # 消费方扩展点:CodeGraph 自己永远不填,留给主系统贴业务标注(如"够判责")。
    consumer_hint: Optional[dict] = None


# ---------------------------------------------------------------------------
# 不变量(纯标准库实现,可独立测试/复用)
# ---------------------------------------------------------------------------

class InvariantError(ValueError):
    """某条可信度元数据违反了不变量。"""
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"[{code}] {message}")


def check_invariants(c: Credibility) -> None:
    """逐条强制不变量。违反则抛 InvariantError(带编号,便于定位)。

    不变量集合(经多模型交叉 review 定稿):

    INV1  source==tree-sitter        => certainty==syntactic
          语法引擎不产出语义结论。
    INV2  certainty==semantic        => source==clangd
          语义级只能来自 clangd。
    INV3  resolved==unresolved       => relation==n/a
    INV4  resolved==not_found        => relation==n/a
          (INV3+INV4 合:没找到/看不到时关系只能 n/a,杜绝 not_found+may 这种含糊组合)
    INV5  blind_spot_affects_result  => certainty!=semantic 且 relation!=must
          盲区"影响本结果"时才降级(用 affects_result 而非 nearby,避免误杀)。
    INV6  resolved==not_found        => dependency.status==complete
          只有支撑本结果的依赖闭包齐全,"我确认没有"才成立。
    INV7  dependency.status==unknown => resolved!=not_found
          依赖完整性未知时,任何"没找到"必须降级为 unresolved(存疑从严)。
    INV8  relation==must             => certainty==semantic
          C/C++ 里宏/函数指针使语法级无法安全断言"必然"关系;must 由语义垄断。
    INV9  query_kind==entity         => relation==n/a
          实体型查询(定义/引用)没有关系维度。
    INV10 source==tree-sitter        => dependency.level==n/a 或 status!=incomplete 误导性
          tree-sitter 不吃编译依赖,不应标 incomplete;用 not_applicable level。
    INV11 relation==must             => resolved==resolved
          只有真解析到结果,才谈得上"必然关系"。
    INV12 source==tree-sitter        => resolved!=not_found
          语法引擎无权断言"确实不存在";它的"没看到"只能是 unresolved。
          (这条 review 未覆盖,设计时自查发现:tree-sitter 的 not_applicable
           依赖使其能绕过 INV6,故需单独一条挡住。)
    """
    src, cert, rel, res = c.source, c.certainty, c.relation, c.resolved
    dep = c.dependency

    # INV1
    if src == Source.TREE_SITTER and cert != Certainty.SYNTACTIC:
        raise InvariantError("INV1",
            "tree-sitter source must carry syntactic certainty")
    # INV2
    if cert == Certainty.SEMANTIC and src != Source.CLANGD:
        raise InvariantError("INV2",
            "semantic certainty must come from clangd")
    # INV3 / INV4
    if res in (Resolved.UNRESOLVED, Resolved.NOT_FOUND) and rel != Relation.NA:
        raise InvariantError("INV3_4",
            f"resolved={res.value} requires relation=n/a, got {rel.value}")
    # INV5
    if c.blind_spot_affects_result:
        if cert == Certainty.SEMANTIC:
            raise InvariantError("INV5",
                "blind_spot_affects_result forbids semantic certainty")
        if rel == Relation.MUST:
            raise InvariantError("INV5",
                "blind_spot_affects_result forbids must relation")
    # INV6
    if res == Resolved.NOT_FOUND and dep.status != DepStatus.COMPLETE:
        raise InvariantError("INV6",
            f"not_found requires dependency.status=complete, got {dep.status.value} "
            f"(incomplete/unknown deps mean we cannot see, not that it's absent)")
    # INV7
    if dep.status == DepStatus.UNKNOWN and res == Resolved.NOT_FOUND:
        raise InvariantError("INV7",
            "dependency.status=unknown forbids not_found (downgrade to unresolved)")
    # INV8
    if rel == Relation.MUST and cert != Certainty.SEMANTIC:
        raise InvariantError("INV8",
            "must relation requires semantic certainty")
    # INV9
    if c.query_kind == QueryKind.ENTITY and rel != Relation.NA:
        raise InvariantError("INV9",
            f"entity query requires relation=n/a, got {rel.value}")
    # INV10
    if src == Source.TREE_SITTER and dep.status == DepStatus.INCOMPLETE:
        raise InvariantError("INV10",
            "tree-sitter does not consume compile deps; must not be 'incomplete' "
            "(use level=n/a)")
    # INV11
    if rel == Relation.MUST and res != Resolved.RESOLVED:
        raise InvariantError("INV11",
            f"must relation requires resolved=resolved, got {res.value}")
    # INV12
    if src == Source.TREE_SITTER and res == Resolved.NOT_FOUND:
        raise InvariantError("INV12",
            "tree-sitter cannot assert not_found: syntactic analysis has no "
            "authority to claim 'truly absent'. Use unresolved instead "
            "('not seen syntactically' != 'confirmed absent').")


# linter 级别的"软"检查:不阻断,只提示可疑组合(不进硬不变量,见 review inv10 讨论)
def soft_warnings(c: Credibility) -> list[str]:
    """返回非阻断的可疑组合提示。例:clangd + 依赖齐全 + 无盲区却 unresolved。"""
    w: list[str] = []
    if (c.source == Source.CLANGD
            and c.dependency.status == DepStatus.COMPLETE
            and not c.blind_spot_affects_result
            and c.resolved == Resolved.UNRESOLVED):
        w.append("clangd with complete deps and no blind spot yet unresolved — "
                 "possible corner case (template meta / complex macro / clangd limit)")
    if c.blind_spot_nearby and not c.blind_spot_affects_result:
        w.append("blind spot exists nearby but marked as not affecting this result — "
                 "ensure this judgment is sound")
    return w


def validate(c: Credibility) -> Credibility:
    """校验并原样返回(便于链式)。违反硬不变量则抛 InvariantError。"""
    check_invariants(c)
    return c
