# Stage 01 - Metadata / Progress
> 开发过程持续追加，记录思考与决策，而非仅结果。

## 关键决策
- 决策：按 `docs/CodeGraph-SOP部署开发Guide.md` 使用项目根 `.dev_memory/`，不使用 design §9 中旧示例的 `docs/dev_memory/`。
  - 原因：部署 guide 明确指出早期版本曾误写 `docs/dev_memory`，以 `.dev_memory` 为准。
  - 排除的方案：同时维护两套 dev memory。该方案会制造上下文分叉。
- 决策：gstack 降级为手动等价流程。
  - 原因：当前环境无 Node/npm/Bun，无法安装或运行 gstack slash 命令。
  - 排除的方案：假装 `/gstack-*` 可用。SOP 明确禁止。
- 决策：P1 编码暂停，先等待复用资产或开发者确认重建。
  - 原因：当前仓库缺少 guide 要求的旧 `credibility.py` / `factories.py` / 28 测试，P1 不能声称“扩展且不破旧测试”。
  - 排除的方案：直接从设计重写 P1。该方案与“复用资产不重写”硬约束冲突，除非开发者明确授权。
- 决策：复用资产已补入后，在旧 `credibility.py` / `factories.py` 上增量扩展，不重写资产逻辑。
  - 原因：资产基线 `PYTHONPATH=.:tools python3 -m pytest tests/ -q` 已通过 47 tests，满足 P1 红线前置。
  - 排除的方案：删除旧实现从 design 重建。该方案会丢失已验证 PoC 行为。
- 决策：P1 不实现 INV17。
  - 原因：design.md 明确原 INV17 已并入容器级 QR7，QR1-9 属 P2。
  - 排除的方案：在 `check_invariants` 中强行校验候选身份。单条 Credibility 不知道自身是否属于 syntactic_candidates。
- 决策：`QueryMeta` 使用 `@dataclass(frozen=True)`，不用 TypedDict。
  - 原因：design.md §4.1.2 已拍板，避免 3.10/3.11 分叉；字段为 kind/symbol/build_config_id 必填，file/pos 可选。
  - 排除的方案：TypedDict/NotRequired。该方案与冻结契约冲突。
- 决策：预留值按 INV19 放行并校验，不写死 source/certainty 白名单。
  - 原因：`log_search` / `exact_syntactic` 是二期预留 schema，P1 需要允许合法组合并拒绝非法组合。
  - 排除的方案：仅允许 clangd/tree-sitter 或 semantic/syntactic。该方案会破坏冻结契约的二期兼容性。
- 决策：删除传输容器 `codegraph_assets.tar.gz` 并加入 `.gitignore`；将 `ASSETS_README.md` 移入 `docs/reuse-assets.md`。
  - 原因：压缩包资产已解压且冗余，不该入库；资产说明有后续接手价值，保留在 docs 更合适。
  - 排除的方案：保留根目录未跟踪文件。该方案会污染后续 `git status`。
- 决策：针对 review 提出的 §2.1 future annotations 风险，补 AST 守护测试而非重复修改已合规文件。
  - 原因：当前 `factories.py`、`credibility.py`、`types.py`、`engines/protocol.py`、`tools/cdb_rewriter.py` 均已含 `from __future__ import annotations`；守护测试能防止后续新增 `|` 注解时漏加。
  - 排除的方案：重复添加 future import 或只在 progress 里口头确认。前者无效，后者不能防回归。

## 改动摘要
- 文件/模块：`AGENTS.md`
  - 改动内容：写入 SOP 附录 A，并追加 CodeGraph 项目硬约束。
- 文件/模块：`.dev_memory/INDEX.md`
  - 改动内容：记录环境预检、远端状态、缺失资产、当前 stage。
- 文件/模块：仓库骨架
  - 改动内容：创建 `codegraph/`、`codegraph/engines/`、`tools/`、`tests/`、docs 标准子目录与 checkpoints 文件。
- 文件/模块：`docs/review/design_review_phase_1.md`
  - 改动内容：记录 Phase 1 启动前设计 review。
- 文件/模块：`.gitignore`
  - 改动内容：忽略 Python 缓存与 `codegraph_assets.tar.gz`。
- 文件/模块：`docs/reuse-assets.md`
  - 改动内容：保存复用资产包说明，替代根目录未跟踪 `ASSETS_README.md`。
- 文件/模块：`codegraph/credibility.py`
  - 改动内容：扩展 Source/Certainty/Coverage/active_config/index/symbol/dependency schema，新增 INV13-16/18/19，保留 INV17 给 P2 QR7。
- 文件/模块：`codegraph/factories.py`
  - 改动内容：旧 factory 签名保持兼容，补充新字段参数与 `make_error_credibility()`。
- 文件/模块：`codegraph/types.py`
  - 改动内容：定义 §4.1 Pos/Range/SymbolId/QueryStatus/IssueCode/QueryMeta/Note/QueryResult/Result/Candidate/Result data schema。
- 文件/模块：`codegraph/engines/protocol.py`
  - 改动内容：定义 P1 的 EngineObservation/SyntacticProvider 协议形状。
- 文件/模块：`tests/test_phase1_metadata.py`
  - 改动内容：新增 P1 不变量、预留值、QueryMeta、QueryResult/Candidate、协议导出测试。
- 文件/模块：`tests/test_phase1_metadata.py`
  - 改动内容：新增 §2.1 守护测试，扫描 `codegraph/` 与 `tools/` 中使用 PEP604 `|` 类型语法的文件必须声明 future annotations。

## 进度日志
- [2026-06-13] 阅读 `docs/CodeGraph-SOP部署开发Guide.md`，确认一次性准备、Phase 串行策略、P1 启动要求。
- [2026-06-13] 阅读 SOP 附录 A、design §7/§8/§9/§10，并通读 `docs/design.md`。
- [2026-06-13] 完成环境预检：Git/Codex/GitHub CLI 可用；Python 需用 `python3`；Node/npm/Bun 缺失。
- [2026-06-13] 创建初始化骨架并提交 baseline：`804d50c`。
- [2026-06-13] 切分支 `phase/1-metadata`，记录 baseline 检查结果。
- [2026-06-13] 导入复用资产并提交：`7222155`；资产基线 47 tests 通过。
- [2026-06-13] 开始 Phase 1 编码前确认：INV17 属 P2 QR7、QueryMeta 用 frozen dataclass、预留值按 INV19 放行。
- [2026-06-13] 完成 Phase 1 元数据实现；`PYTHONPATH=.:tools python3 -m pytest tests/ -q` 通过 59 tests。
- [2026-06-13] 旧 credibility 回归基线单跑通过：`PYTHONPATH=.:tools python3 -m pytest tests/test_credibility.py -q` 通过 28 tests。
- [2026-06-13] Review 修复：确认 `factories.py` 已有 future import；`credibility.py` 无 PEP604 `|` 联合注解但已有 future import；`types.py` / `engines/protocol.py` 已有 future import；`tools/cdb_rewriter.py` 使用 `list[str] | None` 且已有 future import。补充 AST 守护测试防回归。
