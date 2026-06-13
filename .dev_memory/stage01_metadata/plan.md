# Stage 01 - Metadata / Plan

## 目标
启动 CodeGraph Phase 1：元数据层 + 数据结构 + 引擎观察协议。按 `docs/design.md` §7 Phase 1 落地：
- 扩展 `codegraph/credibility.py`：coverage / active_config / build_config_id / symbol_kind / index_health / index_backend / dependency。
- 新增并校验 INV13-16、INV18、INV19，保持旧 12 个不变量与旧 28 测试不破。
- 定义 `codegraph/types.py` 中 §4.1 的 dataclass/Enum 类型。
- 定义 `codegraph/engines/protocol.py` 中 `EngineObservation` / `SyntacticProvider` 协议。
- 扩展 `codegraph/factories.py`，包含 `make_error_credibility()`。

## 范围边界
做：
- §4.1.0 / §4.1.2 / §4.1.3 的类型定义。
- §4.2 的 Credibility schema 与 INV1-16、INV18、INV19。
- 每个不变量一个独立检查函数。
- P1 所需 factories 与 engine protocol。
- P1 单测，包含非法组合拒绝与紧邻合法组合不误杀。

不做：
- `check_query_result_invariants()` 与 QR1-9 实现（P2）。
- 路由状态机、tree-sitter、clangd adapter、离线建库、API 端到端、MCP。
- §3.5 二期清单。
- 修改 `docs/design.md`。

## 计划步骤
1. 完成 R10/R12/R1 预检与设计 review。
2. 确认复用资产是否已就位：`credibility.py`、`factories.py`、`test_credibility.py` 28 测试、`verify_clangd.py`、`cdb_rewriter.py`。
3. 若旧 credibility 资产补齐且 28 测试 baseline 通过，再开始 P1 编码。
4. 若开发者确认旧资产不可得并授权从冻结设计重建，则先记录该决策，再按设计重建 P1 基线。
5. 实现 P1 类型、Credibility schema、不变量、factories、engine protocol。
6. 补齐 P1 单测与覆盖率，跑 `ruff check` / `black --check` / `mypy` / `pytest --cov`。
7. 生成 review prompt/checklist，等待人工 review 与放行。

## 依赖前置阶段
无已完成开发阶段。当前依赖初始化 baseline commit `804d50c`。

## Baseline（改前状态）
- Git baseline：`804d50c`。
- 分支：`phase/1-metadata`。
- `ruff check`：失败，`ruff` 命令不存在。
- `black --check .`：失败，`black` 命令不存在。
- `mypy codegraph`：失败，`mypy` 命令不存在。
- `python3 -m pytest`：可运行，但当前收集 0 个测试，退出码 5。
- `python3 -m pytest --cov=codegraph --cov-branch`：失败，pytest 不识别 `--cov`，`pytest-cov` 未安装。

## 风险档判断
Phase 1 风险档：普通。

理由：P1 位于最底层，涉及 Credibility 核心 schema、不变量与后续所有 Phase 的数据契约；但实现范围纯 Python/stdlib，本机可测，不需要 P5/P7 真机 gate。

## 当前暂停点
P1 编码前必须先处理复用资产缺失：
- `codegraph/credibility.py`
- `codegraph/factories.py`
- `tests/test_credibility.py`（旧 28 测试）
- `tools/verify_clangd.py`
- `tools/cdb_rewriter.py`

其中前三项直接阻塞 P1，因为 guide 明确要求 P1 在既有 12 不变量/28 测试上增量扩展。
