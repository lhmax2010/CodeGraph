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

## 改动摘要
- 文件/模块：`AGENTS.md`
  - 改动内容：写入 SOP 附录 A，并追加 CodeGraph 项目硬约束。
- 文件/模块：`.dev_memory/INDEX.md`
  - 改动内容：记录环境预检、远端状态、缺失资产、当前 stage。
- 文件/模块：仓库骨架
  - 改动内容：创建 `codegraph/`、`codegraph/engines/`、`tools/`、`tests/`、docs 标准子目录与 checkpoints 文件。
- 文件/模块：`docs/review/design_review_phase_1.md`
  - 改动内容：记录 Phase 1 启动前设计 review。

## 进度日志
- [2026-06-13] 阅读 `docs/CodeGraph-SOP部署开发Guide.md`，确认一次性准备、Phase 串行策略、P1 启动要求。
- [2026-06-13] 阅读 SOP 附录 A、design §7/§8/§9/§10，并通读 `docs/design.md`。
- [2026-06-13] 完成环境预检：Git/Codex/GitHub CLI 可用；Python 需用 `python3`；Node/npm/Bun 缺失。
- [2026-06-13] 创建初始化骨架并提交 baseline：`804d50c`。
- [2026-06-13] 切分支 `phase/1-metadata`，记录 baseline 检查结果。
