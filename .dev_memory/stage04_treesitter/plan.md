# Stage 04 - Treesitter / Plan

## 目标
启动 CodeGraph Phase 4：tree-sitter 兜底适配器 + syntax helper。按 `docs/design.md` v1.4.4 §7 Phase 4 与 change_4 落地：
- 实现 P1 `SyntacticProvider` 协议：`search_candidates()`、`candidates_near()`、`is_preprocessor_location()`。
- 用真实 tree-sitter C/C++ grammar 解析源码，产出只进入 `syntactic_candidates` 的候选。
- 实现 P4 评分算法：精确查询四维（名字 +15、同文件 +10、同作用域 +10、类型 +5）和 search 两维（名字 +15、类型 +5）。
- 实现要素2 syntax helper：按 **position** 判断是否落在宏展开/生成的伪位置，不按 symbol_kind 判断。
- 移除 P2 保守期遗留的 `symbol_kind == SymbolKind.MACRO` 短路，只保留 `syntactic_provider is None -> True` 的无 helper 保守降级。

## 范围边界
做：
- 新增 tree-sitter adapter 模块，实现真实解析、候选抽取、评分、护栏 1/2 标注。
- 候选统一带 `consumer_warning="not_evidence"`、`certainty=syntactic`、`active_config=unknown`、`relation in {may, n/a}`，并提供 `relevance_score`。
- `is_preprocessor_location(file, pos)` 使用 tree-sitter AST 的 `preproc_*` 节点按位置判断：`#define` 宏定义位置应返回 False；宏展开/生成伪位置应返回 True。
- 对 binding 不可得提供可观测降级：候选能力不可用，路由缺 helper 时要素2 保守降级。
- 精确修改 `codegraph/routing.py` 中 `_has_preprocessor_blind_spot()` 的 P2 遗留条件：只删除 `symbol_kind == SymbolKind.MACRO` 这一项，保留 `syntactic_provider is None` 分支，不改 QR1-9、状态机、降级真值表。
- fake/deterministic 单测 + 真实 tree-sitter 集成测试；补宏定义可 OK 与宏展开处降级回归。

不做：
- 不修改 `docs/design.md` 或 §4 接口/INV/QR 契约。
- 不做 P2 阈值过滤决策；P4 只计算 `relevance_score`，P2 按 20/15 阈值过滤。
- 不下任何语义结论，不产 not_found，不参与负证明。
- 不做 P3 clangd adapter、P5 离线建库、P6 API 端到端。
- 不用手写 stdlib parser 兜底；change_4 选择方案 A，tree-sitter 可得，实战有问题再走设计变更。

## 计划步骤
1. 复核 P1 `SyntacticProvider` 协议和 P2 `routing.py` 消费点，锁定只改 `_has_preprocessor_blind_spot()` 的 `symbol_kind==MACRO` 短路。
2. 设计 `codegraph/engines/treesitter_adapter.py`：可选导入 tree-sitter/tree-sitter-c/tree-sitter-cpp；binding 不可得时构造 unavailable provider 或抛清晰错误，供调用方传 `None` 触发 P2 既有降级。
3. 实现源码读取与 parser 缓存，支持 C/C++ 文件；路径读取保持在 adapter 层，不改路由契约。
4. 实现候选抽取：函数/宏/类型等基础 symbol 节点，映射为 `Candidate` + `LocationResult`；候选 credibility 可完整填写，尽管 P2 `_normalize_fallback_candidate()` 当前会重造 credibility 并只保留 `symbol_kind` 与 `relevance_score`。
5. 实现评分算法：精确查询按名字、同文件、同作用域、类型累计；search 按名字、类型累计。P4 不过滤，只返回分数。
6. 实现 syntax helper：基于 AST `preproc_*` 节点按 position 判断。测试覆盖 `#define` 定义位置 -> 非伪位置；宏展开/生成位置 -> 盲区。
7. 外科手术式修改 P2：删除 `_has_preprocessor_blind_spot()` 中 `symbol_kind == SymbolKind.MACRO` 条件；新增宏定义可 OK 回归，确保无 helper 仍降级。
8. 跑 gate：P4 单测、全量 pytest、ruff、black、mypy、coverage；把结果写入 progress。

## 依赖前置阶段
- 已完成并 Merge：stage01_metadata、stage02_routing、stage03_clangd_adapter。
- P4 依赖 P1 协议和 P2 路由接缝；不依赖 P3/P5/P6 的真实集成。

## Baseline（改前状态）
- Git baseline：`46ed936` (`[design] apply change_4 v1.4.4: tree-sitter as 要素2 semantic dependency (方案A)`)。
- 分支：从 `main@46ed936` 新建 `phase/4-treesitter`。
- Baseline 测试命令：`PYTHONPATH=.:tools python3 -m pytest tests/ -q`
- Baseline 测试结果：`90 passed in 0.21s`。
- tree-sitter 环境：
  - 当前系统 `python3` 直接 `import tree_sitter` 失败，说明裸环境尚未安装 binding。
  - `uv tool run --with tree-sitter==0.25.2 --with tree-sitter-c==0.24.2 --with tree-sitter-cpp==0.23.4 python ...` 可成功 import。
  - 微型 parse 验证通过：C grammar 可解析 `#define FOO 1`，AST 中出现 `preproc_def` / `preproc_arg`。
  - 已用 `uv venv --allow-existing --seed .venv` 建立项目本地 `.venv`，并安装 `tree-sitter==0.25.2`、`tree-sitter-c==0.24.2`、`tree-sitter-cpp==0.23.4`、`pytest`、`pytest-cov`；`.venv/bin/python` 可直接 import tree-sitter 并跑现有 90 测试。

## 风险档判断
Phase 4 风险档候选：高。

理由：
- P4 第一次引入允许的第三方 runtime 例外；当前裸系统 `python3` 受 PEP 668 管理，P4 开发/测试改用项目本地 `.venv`，最终部署也应使用装有 tree-sitter binding 的服务 Python/venv。
- change_4 要求回头修改已 Merge 的 P2 核心路由代码，必须只移除 `symbol_kind==MACRO` 一个短路条件，避免影响 QR1-9 和状态机。
- syntax helper 是 P6 产出 OK 语义结果的前置；要素2误判会直接导致虚假可信或误降级。
- tree-sitter AST 节点、坐标和 C/C++ grammar 差异会影响候选抽取与 preproc 位置判断，需要真实集成测试锁住。

## 当前暂停点
stage04 已开，等待风险档与 restate gate 确认后再实现。
