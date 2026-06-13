# Phase 1 Design Review

## Review Scope
- 文档：`docs/design.md` v1.3 Frozen（2026-06-11）。
- 阶段：Phase 1，元数据层 + 数据结构 + 引擎观察协议。
- 审查项：需求覆盖、模块/数据流、接口契约、阶段拆分与依赖、非功能约束落地性。

## 结论
未发现需要变更冻结设计的阻塞问题。Phase 1 的设计边界清楚：只做类型、Credibility schema、不变量、factories 与引擎观察协议，不做 QR1-9 容器校验、路由、具体引擎、API 端到端或 MCP。

当前不能开始编码的原因不是设计缺陷，而是仓库状态：design §2.3 和部署 guide 要求复用的旧资产未在当前仓库中出现。

## 需求覆盖度
- MVP 第一批范围与 Phase 拆分覆盖核心目标：clangd 语义主路、tree-sitter 语法兜底、可信度元数据、离线索引、库 API 与 MCP 薄封装。
- Phase 1 覆盖最底层契约：§4.1 类型结构、§4.2 Credibility 字段与 INV1-16/18/19、engine protocol，能支撑 P2/P3/P4 并行或串行推进。
- Out of Scope 与二期清单明确，P1 不应触碰 locate_log_statement、clangd-indexer、get_impact 精度、staleness 等。

## 模块与数据流
- 元数据层处于最底层，依赖方向合理：P2 路由、P3/P4 引擎、P6+ API 都依赖 P1 类型和协议。
- 单条 credibility 校验与 P2 容器校验分层合理：候选身份约束 QR7 放在容器级，避免单条 Credibility 不知道自身所属列表的问题。
- `EngineObservation` / `SyntacticProvider` 在 P1 定义，便于 P2 用桩开发，也避免 P2 依赖具体引擎。

## 接口契约
- §4.1 对外 API、QueryResult、Result/Candidate 与 data schema 在 P1 中只定义类型，不实现端到端接口，边界合理。
- `from __future__ import annotations` 要求已在设计与 AGENTS 中双重记录，适配 Python 3.10+。
- 预留值 `log_search` / `exact_syntactic` 的放行规则明确，P1 实现时不能写死 `source`/`certainty` 白名单。

## 阶段拆分与依赖
- Phase DAG 无循环依赖。部署 guide 建议严格串行 P1→P9，适合当前单会话开发。
- P1 额外要求 R10/R12/R1 合理；当前 R12 扫描发现复用资产缺失，应在编码前处理。
- P5/P7 真机 gate 与 P1 无关，P1 可本机推进，但需先解决旧资产与工具链。

## 非功能约束落地性
- 核心纯 stdlib 可落地；P1 可以使用 dataclass/Enum/typing/Protocol 等标准库。
- 覆盖率目标可落地，但当前缺少 `pytest-cov`，需要安装开发依赖或配置本地 venv 后再进入验收。
- lint/type/format gate 可落地，但当前缺少 `ruff`、`black`、`mypy`。

## 启动风险
- 复用资产缺失：旧 12 不变量/28 测试不在仓库，无法验证“不破旧测试”。这是 P1 编码前阻塞项。
- 工具链缺失：`ruff`、`black`、`mypy`、`pytest-cov` 未安装，会阻塞第一道门。
- 远端为空：GitHub remote 存在且 gh 已登录，但初始化 commit 尚未 push；正式 PR 前需 push main/phase branch。
