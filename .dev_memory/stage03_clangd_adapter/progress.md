# Stage 03 - Clangd Adapter / Progress
> 开发过程持续追加，记录思考与决策，而非仅结果。

## 关键决策
- 决策：Phase 3 开 stage baseline 取 `main@e87543d`，从该提交新建 `phase/3-clangd-adapter`。
  - 原因：stage02_routing 已 Merge，`main` 干净且 P2 baseline 80 tests 全过。
  - 排除的方案：从旧 `phase/2-routing` 继续开发。该方案会绕开已 Merge 的 checkpoint 与 INDEX 状态。
- 决策：Phase 3 风险档先按高风险候选处理，等待开发者确认。
  - 原因：P3 首次接真实 clangd 子进程/LSP，涉及异步诊断、超时、callHierarchy 能力兼容与小型 CDB 真集成。
  - 排除的方案：按普通风险推进。该方案低估了真实引擎边界和超时/生命周期对后续 P6/P8 的影响。
- 决策：P3 只产 observation，不写任何 credibility/resolved/relation/certainty 判断。
  - 原因：可信度解释属于 P2 路由层；adapter 只报告 clangd 返回了什么和诊断事实。
  - 排除的方案：在 adapter 内直接把空结果解释为 not_found 或把调用边标 must。该方案越界并会破坏分层。
- 决策：callers/callees 必须用 clangd callHierarchy，不用 references+AST 近似推导。
  - 原因：设计明确要求调用关系来自 clangd callHierarchy；近似图会产出不可信关系。
  - 排除的方案：用 references 搜调用点再猜 caller/callee。该方案违反 P3/P8 contract。

## 改动摘要
- 文件/模块：`.dev_memory/INDEX.md`
  - 改动内容：登记 `stage03_clangd_adapter` 为当前活跃 stage，记录 baseline commit。
- 文件/模块：`.dev_memory/stage03_clangd_adapter/plan.md`
  - 改动内容：记录 Phase 3 目标、范围边界、计划步骤、baseline、环境和风险档候选。
- 文件/模块：`.dev_memory/stage03_clangd_adapter/progress.md`
  - 改动内容：记录开 stage 决策。
- 文件/模块：`.dev_memory/stage03_clangd_adapter/result.md`
  - 改动内容：创建进行中结果占位，等待 Phase 3 收尾时填写。

## 进度日志
- [2026-06-15] 读取 `AGENTS.md`、`docs/design.md` v1.4.3、`docs/design_changes/change_1/2/3/4.md`、`.dev_memory/INDEX.md`、stage01/stage02 result、stage02 plan/progress、review 记录和 `tools/verify_clangd.py`；确认 `change_4` 是 P6 前的 syntax-helper 设计决策，不属于 P3。
- [2026-06-15] 确认 stage02 已 Merge；`main` 位于 `e87543d [Phase 2] docs: close routing stage` / `checkpoint/phase_2_routing`。
- [2026-06-15] clangd 环境预检：`/usr/bin/clangd`，Ubuntu clangd `18.1.3 (1ubuntu1)` 可用。
- [2026-06-15] 在 `main@e87543d` 跑 baseline：`PYTHONPATH=.:tools python3 -m pytest tests/ -q` -> `80 passed in 0.07s`。
- [2026-06-15] 从 `main@e87543d` 新建分支 `phase/3-clangd-adapter`。
- [2026-06-15] 创建 `.dev_memory/stage03_clangd_adapter/` 计划与进度骨架；等待风险档与 restate gate 确认后再实现。
