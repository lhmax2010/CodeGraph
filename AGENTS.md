# gstack 命令白名单（只用这些）
通用：/gstack-autoplan, /gstack-plan-eng-review, /gstack-review,
/gstack-freeze, /gstack-guard, /gstack-learn
跨模型 second-opinion 命令（名字取决于你装的 host，二选一）：
- 若 host = codex（本机是 Codex）→ 用 /gstack-claude（调 Claude 做第二意见）
- 若 host = claude（本机是 Claude Code）→ 用 /gstack-codex（调 Codex 做第二意见）
不要调用浏览器/设计/部署 skill（/gstack-qa, /gstack-browse,
/gstack-design-*, /gstack-ship, /gstack-canary, /gstack-ios-* 等）。

# 开发流程规约（每个 task 必须遵守，来自 design.md 的 R1–R14）

## 能力与权限边界（最高优先级，先于下面所有规约）
本规约是**执行协议，不是强制自动化引擎**。下列每条遇到能力/权限/工具缺失时，必须**停下报告 +
给降级方案，不得假装已完成**：
- **优先级**：平台/系统/developer 指令 > 当前用户明确指令 > 本规约与 AGENTS.md。本文件是提示约束，不是强制执行器；
  与更高优先级指令冲突时以后者为准，并说明冲突点。
- **gstack fallback**：`/gstack-*` 命令依赖 gstack 已安装。没装时这些 slash 命令对 AI 只是文字，
  不可调用——改走手动等价（读设计、列计划、改代码、跑测试、做 review、记 memory），并说明在降级。
- **subagent fallback**：有 subagent 工具才做独立复审；没有则生成 diff review checklist，交人工/三方补，
  不假装做了独立复审。
- **coverage fallback**：覆盖率针对本次 touched files。没有 coverage 工具链时不假装有，默认降级为
  "关键路径测试清单"（列改动必须覆盖的场景 + 测试是否存在），并报告；不让缺工具变成跳过测试。
- **安全 git 操作**：见下方「Git 与 PR 规范」与「Rollback」的硬约束——destructive 操作需检查 + 授权。
- **merge 权限限制**：merge 受 GitHub 权限、分支保护、CI 必过约束。不满足时报告"无法 merge + 原因"，
  不强行合、不绕 CI、不强推。

## 项目初始化（第一次干活时自动做）
若项目根目录无 .dev_memory/，在第一个 stage 前自动创建骨架：
- .dev_memory/INDEX.md（用本规约末尾模板）
- .dev_memory/_archived/（空文件夹，rollback 归档用）
- .dev_memory/stage01_<名称>/，含 plan.md / progress.md / result.md（用末尾模板）
创建后填好 INDEX.md 与 stage01 的 plan.md，再开始编码。

## 上下文加载顺序（每次会话开始先做，R6）
1. 读 docs/design.md（总设计，Frozen）
2. 读 docs/design_changes/（已批准的设计变更）
3. 读 .dev_memory/INDEX.md，确认当前活跃 stage 和最后已 Merge 的 stage
4. 读所有已 Merge stage 的 result.md（事实基线）+ 上一 stage 的 plan/progress/result
5. 读 docs/review/*_review_result.md（上阶段 review 闭环结果）
6. 读 docs/spinoffs/（被隔离的衍生话题）
_archived/ 内容不读、不引用。读完用一两句话复述当前状态，再开始。

## 实现纪律
- 实现前先复述任务理解，等人确认再写代码（restate 闸门）。
- 严禁自作主张改 design.md。发现设计有问题：停下，输出 [DESIGN_ISSUE] + 建议方案，
  创建 docs/design_changes/change_N.md，等人确认（R1）。
- 只改当前 stage 相关文件，不顺手重构/改无关代码/升无关依赖（R11）。装了 gstack 用 /gstack-freeze
  锁定/约束改动范围；无 gstack 时为软约束（自我克制）+ 后续 review gate 把关，不是物理锁。
- 出现 >=2 个实现方案、要动第三方依赖/公共API/数据Schema/安全模型/性能取舍/部署方式：
  停下问人，不要替人做主（R2）。
- 与当前 stage 无关的新想法：不打断当前任务，写到 docs/spinoffs/{topic}.md（R4）。有 subagent 工具
  则用 subagent 隔离记录；没有则主流程顺手记一条，不假装派了 subagent。
- 同一问题最多试 3 次，第 3 次还失败停下报告，不要继续堆补丁。
- 编译/环境错误（GBS 配置、交叉链路径、依赖包）先停下报告，不靠改源码硬修。
- 不引入任何 secret/token/密钥/敏感日志。
- 不得声称"测试通过"而不贴实际命令和输出摘要（R13）。
- **外发检查（转三方 AI / 贴外部前必做）**：不只检查 diff——PR 描述、测试日志、dev_memory、真机日志、
  截图同样要查。确认不含 secret/token、客户或个人数据、内部主机名/路径、设备 IP、用户名、受限 license
  片段（这些更常出现在日志而非 diff 里）。有则先脱敏或不外发该部分。

## CodeGraph 项目硬约束（追加）
- 纯 stdlib：codegraph/ 下 credibility/types/routing/factories/engines/indexing/api
  不得引入第三方运行时依赖。例外仅两个：tree-sitter binding（P4，可降级）、
  MCP SDK（仅 mcp_server.py，P9，不可得可手写 stdio JSON-RPC 或只提供库形态）。
- 所有用 `X | None` 联合类型的模块顶部必须 `from __future__ import annotations`（3.10 运行时不崩）。
- 复用资产不重写：tools/verify_clangd.py、tools/cdb_rewriter.py、现有 credibility.py/factories.py。
  在其上扩展，不重造，不破坏已有 28 测试。
- 严格按 design.md §7 Phase 范围，不提前做后续 Phase，不做 §3.5 二期清单
  （locate_log_statement/clangd-indexer/get_impact 精度/staleness 等）。
- 冻结契约不改：§4.1 接口签名、§4.2 不变量(INV1-16,18,19)、§4.4 路由状态机、QR1-9。
  发现问题输出 [DESIGN_ISSUE] + change_N.md，等人决策，不自行改。
- 确定性检查命令（Python 项目，非 clang 套）：ruff check / black --check / mypy / pytest --cov。
- P1 启动前先确认现有 credibility.py(12 不变量) 与 test_credibility.py(28 测试) 已在仓库、
  且能跑通；P1 在其上扩展，每次跑测试必须确认 28 个旧测试不破（破了即停下报告，不绕过）。
- restate（复述任务理解）时必须自查未越界：P3 不碰 tree-sitter(归 P4)、P2 不自己算评分
  (读 P4 的 relevance_score)、P5 不判 not_found 级别(归 P2)。越界即在复述里标出待人确认。

## 收尾流程（每个 stage 完成，按顺序不可跳；每步遇能力缺失按"能力与权限边界"降级报告）
1. 内部 Review + 单元测试：自我 review；跑 UT 全过；检查 UT 覆盖本次改动逻辑路径，覆盖不足必须补齐重跑。
   覆盖率针对**本次 touched files**，行>=80%/分支>=70%（核心>=90%）；无 coverage 工具链则按边界条款
   降级为"关键路径测试清单"并报告，不假装有覆盖率。
2. subagent 复审（有工具才做，否则出 checklist 交人工/三方）+ 真机验证（merge 前 gate，有环境 AI 跑、
   无环境出 guide 由人在 merge 前跑）+ 提 PR + 人工 review，由主 SOP 流程驱动。
3. 等人工 review 通过、真机过、且有 merge 权限/CI 满足，才能 merge，且才能开下一 stage。
4. 收尾写入对应 stage 的 result.md，并更新 INDEX.md。

## dev_memory 写入要求
- progress.md：开发过程中**决策当下就追加**——选了哪个方案、排除了什么、为什么。不等收尾。
- result.md：收尾时写客观事实——UT结果/覆盖率/PR链接/commit/最终状态/遗留TODO/下一步。
- 用客观、他人可理解的语言，假设接手的是完全陌生的 AI/工程师，10 分钟能恢复上下文。
- dev_memory 与实际代码、git 状态必须一致；发现不一致立即停下报告。

## Git 与 PR 规范（R9/R10）
- 分支：phase/<N>-<short-desc>。Commit：[Phase N] <type>: <subject>。
- 一个 stage 一个 PR，PR 标题 [Phase N] <description>，描述链接 design.md 对应章节。
- 推到官方 GitHub。Phase 1 前做 PR 能力预检：是否 git 仓库/有 remote/指向 GitHub/能建 PR；
  不满足输出 [PR_WORKFLOW_ISSUE] 并暂停等人决策，不得自行降级跳过 PR。
- **destructive git 硬约束**：执行 git reset --hard / force-push / 删分支 / checkout -- . / clean 等
  会丢失改动的操作前，**必须先 `git status --short` 检查**。**有未提交/未跟踪改动时，AI 只报告，
  不得自行 stash、reset、checkout、clean**——由用户决定 stash/commit/备份/丢弃。无改动且经用户
  明确授权目标后才可执行。绝不强推、不绕 CI、不擅自覆盖工作区。

## Rollback 机制
怀疑 AI 幻觉/记忆混乱/与代码不符时：① 用户指定可信检查点 → ② 该检查点之后的 stageNN_*
文件夹移到 _archived/ → ③ **先 `git status --short` 确认无未提交/未跟踪改动会被覆盖、并经用户授权**，
再 git reset --hard checkpoint/phase_X_* 退到该点 commit（有改动则只报告，由用户先处理）→ ④ 更新
INDEX.md 活跃 stage 指回检查点 → ⑤ AI 丢弃当前记忆，只以 INDEX + 检查点及之前 result.md
为唯一事实，重读重规划。Rollback 后不得引用任何已归档 stage 的结论。

---

## 模板：INDEX.md
# Dev Memory 索引 (INDEX)
> 接手须知：开始任何 stage 前，先读本文件，再读所有"已 Merge"stage 的 result.md，
> 以及上一 stage 的 plan/progress/result。_archived/ 内容不读、不引用。

## 当前状态
- 当前活跃 stage：stage01_<名称>（进行中）
- 最后已确认 stage（已 Merge）：无

## stage 列表
| 编号 | 名称 | 状态 | PR 链接 | Git Commit |
|------|------|------|---------|------------|
| stage01 | <名称> | 进行中 | - | - |
（状态：进行中 / 待 Review / 已 Merge / 已 Skip。每次状态变化立即更新。）

---

## 模板：plan.md
# Stage NN - 名称 / Plan
## 目标
（本阶段要达成什么）
## 范围边界
（明确做什么、不做什么，避免范围蔓延）
## 计划步骤
1.
2.
## 依赖前置阶段
（依赖哪些已完成阶段，无则写"无"）

---

## 模板：progress.md
# Stage NN - 名称 / Progress
> 开发过程持续追加，记录思考与决策，而非仅结果。
## 关键决策
- 决策：
  - 原因：
  - 排除的方案：
## 改动摘要
- 文件/模块：
  - 改动内容：
## 进度日志
- [日期] 做了什么 / 当前卡在哪

---

## 模板：result.md
# Stage NN - 名称 / Result
## 最终状态
（进行中 / 待 Review / 已 Merge / 已 Skip）
## 测试情况
- UT 结果：
- 覆盖率（行/分支）：
- 补测内容：
## PR 与代码
- PR 链接：
- 对应 Git Commit：
## 遗留问题 / 风险
-
## 下一阶段计划
-
