# CodeGraph 按 SOP 部署开发 Guide（Codex + gstack）

> 把《外部 AI 开发 SOP（Codex / Claude Code + gstack）》套到 CodeGraph 这个具体项目上。
> 前置：`docs/design.md` 已 **Frozen**（v1.3）。本 guide 只讲 CodeGraph 的具体落法，
> 通用规则以那份 SOP + 项目根 `AGENTS.md` 为准。

---

## 0. 先认清 CodeGraph 的环境现实（决定哪些步骤要降级）

CodeGraph 和典型 GBS 嵌入式项目不同，先把环境对号入座，免得照搬 SOP 踩空：

| 维度 | CodeGraph 的现实 | 对 SOP 的影响 |
|---|---|---|
| 代码本体 | 纯 Python 3.10+，纯 stdlib 核心 | 无 GBS 交叉编译；"确定性检查"是 ruff/black/mypy/pytest，不是 clang-format/GBS 编译 |
| 覆盖率工具 | Python 有 pytest-cov（不是嵌入式那种缺 gcov） | coverage 门正常能跑，**不需要**降级为"关键路径清单" |
| 真机验证 | 不是 sdb/ssh 到设备，而是**在 GBS/ARM 环境跑 clangd 对真实 Tizen 代码** | "真机 gate"= 在有 GBS sysroot + clangd 的 Linux/WSL 上跑端到端（P5/P7 才真正需要） |
| subagent | Codex 环境通常没有 Task subagent | 第二道门多半走 **diff review checklist** 交三方，不假装独立复审 |
| gstack | 可选（你 SOP 已说装不上不阻塞） | 装上用 slash 命令；装不上走手动等价，主流程照跑 |

**关键推论**：
- P1–P4、P6、P8、P9 大多是**纯 Python 逻辑**，本机（含 Windows Git Bash）就能写+测+覆盖率，
  **不需要真机**。真机 gate 对它们是"N/A 或用测试 CDB 模拟"。
- **只有 P5（离线建库）、P7（find_references 跨 TU 真机验证）真正需要 GBS/ARM 环境**——
  这两个 Phase 的真机 gate 是硬的，要在 WSL2/Linux + GBS sysroot 上跑。
- 所以 CodeGraph 的开发可以**大部分在本机推进**，只在 P5/P7 切到 Linux 真机环境验证。

---

## 1. 一次性准备（对应 SOP 步骤 0-0 ~ 0-3）

**1.1 环境预检 + 装依赖**（SOP 步骤 0-0）
```bash
git --version
codex --version          # 用 Claude Code 则 claude --version
python --version         # 需 3.10+（CodeGraph 是 Python 项目，这条最关键）
node --version; npm --version; bun --version   # 仅 gstack 需要
gh --version             # 仅"AI 自动提 PR"需要
```
- Python 3.10+ 必须有（CodeGraph 本体）。gstack 那套（Node/Bun）是可选——装不上按 SOP
  步骤 0-1 的替代方案走手动流程，不阻塞。

**1.2 装 gstack**（SOP 步骤 0-1，可选）
- `--host codex` 装完，second-opinion 命令是 **`/gstack-claude`**（别认错成 /gstack-codex）。
- 企业网装不上 → 走 SOP 附录 B 的修法，或直接退手动流程。

**1.3 建项目骨架**（SOP 步骤 0-2，按 CodeGraph §9 目录）
```bash
git rev-parse --show-toplevel    # 确认在 git 仓库内
git remote get-url origin        # 确认远端是官方 GitHub

# SOP 标准目录 + CodeGraph 代码骨架
mkdir -p docs/design_changes docs/review docs/spinoffs docs/test-guides .dev_memory/_archived
mkdir -p codegraph/engines tools tests
touch docs/checkpoints.md .dev_memory/INDEX.md AGENTS.md codegraph/__init__.py
```
**把已验证资产放进去**（CodeGraph 特有，必做）：
- `cdb_rewriter.py`、`verify_clangd.py` → `tools/`
- 现有 `credibility.py`、`factories.py`、`test_credibility.py`（12 不变量/28 测试）
  → `codegraph/` 和 `tests/`。**P1 要在这上面扩展，必须先就位。**
- `docs/design.md`（Frozen v1.3）→ `docs/`

**1.4 写 AGENTS.md**（SOP 步骤 0-3）
- 把 SOP 附录 A 整段粘进 `AGENTS.md`。
- **CodeGraph 特化**：在 AGENTS.md 的"实现纪律"后追加几条项目硬约束（见本 guide §5）。

**1.5 首次提交**
```bash
git add . && git commit -m "chore: freeze design.md v1.3, scaffold CodeGraph repo"
```

---

## 2. CodeGraph 的 Phase ↔ SOP stage 映射

SOP 的"一个 stage = 一个 Phase"，CodeGraph 有 9 个 Phase（design.md §7）。逐个对：

| Phase | 内容 | 风险档（你确认用） | 真机？ | 备注 |
|---|---|---|---|---|
| P1 | 元数据+数据结构+协议 | **普通**（动 credibility 核心+不变量，偏高） | 否 | 最底层，纯 Python；28 旧测试不能破 |
| P2 | 路由判定+容器校验 QR1-9 | **普通** | 否 | 纯逻辑+桩 |
| P3 | clangd 适配 | 普通 | 否(测试CDB) | 复用 verify_clangd；真集成在 P6 |
| P4 | tree-sitter 兜底+评分 | 低~普通 | 否 | binding 不可得可降级 |
| P5 | 离线建库+index_health | **普通** | **是·GBS/ARM** | 真机 gate 硬：~50s 建库要复现 |
| P6 | search+definition（首集成） | **普通** | 是(接P5索引) | 第一个端到端 |
| P7 | find_references（跨TU验证） | **高**（验证核心价值） | **是·GBS/ARM** | 真机验证 2→389 跨 TU |
| P8 | callers/callees | **普通**（callHierarchy 风险） | 是 | R-技6 真机确认 callHierarchy |
| P9 | MCP 薄封装 | 低 | 否 | 协议转换 |

**串行建议**：你一个人盯，**严格串行 P1→P9**。SOP 说 P2/P3/P4/P5 理论可并行，但并行要开多会话、
上下文易错位，不值当。一个 Phase 走完整套（开 stage→实现→两道门→PR→三方review→拍板→merge→
checkpoint）再下一个。

---

## 3. 每个 Phase 的循环（对应 SOP 步骤 2~6）

每个 Phase 你只动手三次：**①确认风险档 ②PR后review ③拍板**。其余 Codex 跑。

**步骤 2 — 开 stage + 确认风险档**
对 Codex 说：
```
读 docs/design.md 和 .dev_memory/INDEX.md，开始下一个 Phase（当前应是 Phase N）。
按 AGENTS.md 规约做开 stage 准备：开分支 phase/N-<描述>、记 baseline commit、
跑 baseline 记录"改之前就失败的项"、在 .dev_memory/stageNN_<名>/ 建 plan.md。
告诉我你判断的风险档，等我确认。
```
→ 看它报的风险档，对照本 guide §2 的表确认/纠正。**P7 是高风险**（核心价值验证），
别让它判成普通。

**步骤 3 — 确认 restate（任务理解复述）**
Codex 用 `/gstack-autoplan`（或手动）出实现计划 + 复述。你看它有没有理解对：
- 特别检查它**没有越界**（P3 别去碰 tree-sitter，那是 P4；P2 别自己算评分，读 P4 的分）。
- 对 → "确认，开始"；偏了 → 指出。

**步骤 4 — 等实现 + 两道门（你不动手）**
Codex 实现 + 自检。CodeGraph 的两道门具体是：
- **第一道门·确定性检查**：`ruff check` / `black --check` / `mypy` / `pytest`（不是 clang 那套）。
- **第一道门·覆盖率**：`pytest --cov`，本次 touched files 行≥80%/分支≥70%/核心≥90%。
  Python 有 pytest-cov，**正常能跑，不用降级**。**P1 特别确认：28 个旧测试全过。**
- **第二道门·复审**：Codex 多半没 subagent → 出 **diff review checklist** 交步骤 5 的三方。
- **真机 gate**：P1-4/P6/P8/P9 本机即可；**P5/P7 若你本机非 Linux**，Codex 附真机 guide，
  你在 WSL2/Linux+GBS 上跑（见本 guide §4）。

**步骤 5 — 人工 review（你看 + 三方 AI）**
PR 来了（方式 A：gh 自动；方式 B：push 后你网页建 PR）。**外发前硬检查**：
CodeGraph 会接触真实 Tizen 代码路径/符号——转三方 AI 前确认 diff/日志/dev_memory 里
**不含内部代码路径、设备信息、受限符号名**。然后按风险档转 Claude/ChatGPT/Kimi（高风险三路）。
review 重点（CodeGraph 特化）：
- 不变量是否**逐条实现**且模块化（INV13-16/18/19 一个函数一个，别漏）；
- 预留值 log_search/exact_syntactic **放行而非写死白名单**；
- `from __future__ import annotations` 加了没（3.10 不加会崩）；
- 有没有引入第三方依赖（核心必须纯 stdlib）；
- 有没有越界做别的 Phase 的活。

**步骤 6 — 拍板放行**
review 闭环、`[BLOCKER]`/`[MAJOR]` 清完、（P5/P7）真机过了 → "通过，可以 merge"。
Codex 有权限就 merge + 写 result.md + 更新 INDEX + 打 checkpoint。

---

## 4. P5 / P7 的真机验证怎么落（CodeGraph 唯一硬真机点）

CodeGraph 的"真机"不是嵌入式设备，是 **GBS sysroot + clangd 的 Linux 环境**。

**你需要一台**：WSL2 或 Linux 机/容器，装好：clangd 18、GBS 能产出 sysroot、
已有那两份验证用的 CDB（rw_arm/ rw_x86/）。

- **P5 真机 gate**：在该环境跑离线建库脚本，确认 ARM ~50s 建出 ~47MB/3593 个 .idx 分片、
  index_health 判 complete。对照 design.md §5.1 性能预算。
- **P7 真机 gate**（最关键）：对 `gst_element_set_state` 跑 find_references，确认返回
  **389 处/62 文件**的跨 TU 结果（不是单 TU 的 2 处），且带 coverage(index_scope=indexed_project)、
  过双校验。**这是整个 CodeGraph 价值的真机证明，必须亲自看到这个数字。**

Windows 上：纯 Git Bash 跑不了 clangd+GBS（SOP 附录已说），P5/P7 切 WSL2/Linux。
P1-4/P6/P8/P9 在 Windows 本机 Python 就行。

---

## 5. 给 AGENTS.md 追加的 CodeGraph 硬约束

SOP 附录 A 是通用的。在其"实现纪律"段后，**追加这几条 CodeGraph 专属**：

```markdown
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
```

---

## 5.5 对 Codex / 三方 AI 的对话话术（可直接复制）

> 这套 SOP 把纪律沉淀进 AGENTS.md + design.md，所以你对 Codex **说的话很短**——
> 范围 Codex 自己读 design.md §7，纪律自己读 AGENTS.md，你只需发起 + 把关。
> 下面是每个环节实际要说的话，直接复制改 Phase 号即可。

### A. 开每个 Phase（SOP 步骤 2，你发起）
```
读 docs/design.md 和 .dev_memory/INDEX.md，开始 Phase <N>。
按 AGENTS.md 规约做开 stage 准备：开分支 phase/<N>-<短描述>、记 baseline commit、
跑 baseline 记录"改之前就失败的项"、在 .dev_memory/stage<NN>_<名>/ 建 plan.md。
告诉我你判断的风险档，等我确认。
```
> Phase 1 额外加一句（仅第一次）：
> `先确认现有 credibility.py 和 test_credibility.py(28测试)已在仓库且能跑通，再开始。`

### B. 确认 restate（SOP 步骤 3，你把关理解）
Codex 复述任务理解后，你对照 design.md §7 Phase N 的范围检查，重点看**有没有越界**：
- 对 → 回 `确认，开始。`
- 越界/偏了 → 指出，例如：
  `P3 只做 clangd LSP 封装，宏展开判定用 P4 的 syntax helper、不要自己解析 tree-sitter；
   重新复述。`（按实际 Phase 的边界改）

### C. 风险档确认（SOP 步骤 2，对照本 guide §2 表）
Codex 报风险档后：
- 一致 → `风险档确认：<普通/高/低>，继续。`
- 它判轻了（尤其 P7）→ `P7 验证 CodeGraph 核心价值(跨TU find_references)，定为高风险，走三路 review。`

### D. PR 后转三方 review（SOP 步骤 5，外发前先做硬检查）

> **本项目的实际 review 链路（按工具现状定）**：
> - **第一路 = gstack Claude（自动）**：Codex 用 `/gstack-claude`（或读 SKILL.md 跑 nested
>   `claude -p`）对 `git diff origin/main` 自动审，结果存 `docs/review/phase_N_review_result.md`。
>   这一路每个 Phase 都跑，不用你动手。
> - **第二/三路 = ChatGPT + Kimi Code + Gemini（手动，Phase 收口时）**：本机没有 ChatGPT/Kimi/
>   Gemini 的可调 CLI/API，所以**在每个 Phase 实现+gstack Claude 审完、准备 merge 前**，你开
>   **新的 ChatGPT / Kimi Code / Gemini 会话**手动转一轮（高风险三个都上，普通档至少再上一个）。
> - 严格说 gstack Claude + 你自己的核查已是两个异构视角；ChatGPT/Kimi/Gemini 是 merge 前的
>   加固层，把跨模型盲区补掉。

**外发前硬检查**：diff/result文件/dev_memory/日志里不含内部代码路径、设备信息、受限符号名。
然后开新会话转（每个模型独立一份，互不告知，最后你汇总）：
```
这是 CodeGraph（C/C++ 代码智能服务，Python 实现）Phase <N> 的代码改动，独立 review，
逐条标严重程度（[BLOCKER]/[MAJOR]/[MINOR]/[NIT]），只挑问题不肯定优点。重点查：
- 是否符合 design.md 冻结契约（§4 接口/§4.2 不变量/§4.4 路由/QR1-9），逐条对；
- 不变量是否模块化（每个 INV 一个函数）；预留值 log_search/exact_syntactic 是否放行而非写死白名单；
- 所有 X|None 模块是否加 from __future__ import annotations；
- 是否引入第三方依赖（核心必须纯 stdlib）；frozen dataclass 有无可变/hash 隐患；
- 是否越界做了别的 Phase 的活；测试是否覆盖"被拒非法 + 紧邻合法不误杀"两类。
本代码已过 gstack Claude review，已知 findings：<贴 phase_N_review_result.md 的 MAJOR/MINOR>，
请确认或反驳，并找新问题。
[贴 git diff origin/main]
```
> 第二个模型起的会话末尾，把第一个模型的新 finding 也带上，让它确认或补充（异构交叉）。


### E. 汇总意见交 Codex 修（SOP 步骤 5，R14 闭环）
```
三方 + 我的 review 意见如下，按等级处理：[BLOCKER]必修、[MAJOR]必修或我放行、
[MINOR]记 dev_memory TODO、[NIT]可选。修完更新代码+测试+dev_memory+review_result.md，
再更新 PR 等我复确认。
<贴汇总意见>
```

### F. 拍板放行（SOP 步骤 6）
review 闭环 +（P5/P7）真机过了：
```
通过，可以 merge。按收尾流程：merge（有权限且CI/分支保护满足，否则报告阻塞不强合）→
写 result.md → 更新 INDEX.md → 打 checkpoint → 准备开 Phase <N+1>。
```

### G. Codex 报 [DESIGN_ISSUE] 时（你回设计阶段决策）
不要让它绕过。判断是真问题还是它理解错：
- 真问题 → `这是真问题。我来更新 design.md（升版本+记 change_<N>.md），你先停，等我改完通知你。`
  （**只有你能改 design.md**，改完升版本）
- 它理解错 → `design.md 的本意是 <澄清>，不是缺陷。按原设计走，重新复述。`

---

## 6. 现在第一步（今天就能做）

1. §1 装 Python 3.10+，预检；gstack 可选（装不上就手动）。
2. 建仓库骨架（§1.3），把 design.md + 复用资产 + 旧 credibility/28测试 放进去，首次 commit。
3. AGENTS.md = SOP 附录 A + 本 guide §5 的追加约束。
4. 确认官方 GitHub 仓库 + push/PR 能力（走方式 A 则 `gh auth login`）。
5. 对 Codex 说 §5.5-A 的开 Phase 话术（Phase 1 加那句"先确认旧资产"），等它报风险档。
6. 之后每个 Phase 按 §3 循环 + §5.5 话术走，你只在 ①风险档 ②PR后review ③拍板 三处介入。

到 P5/P7 时，准备好 WSL2/Linux+GBS 环境做真机 gate（§4）。

---

## 7. 一页速查（贴墙上）

- **你只做三件事**：确认风险档、PR 后 review（你+三方AI）、拍板放行。
- **设计冻结**：design.md 不改，改走 [DESIGN_ISSUE]→change_N.md→你决策。
- **串行 9 个 Phase**：P1→...→P9，一个 Phase 整套走完再下一个。
- **两道门 + 真机 gate**：①ruff/black/mypy/pytest+cov ②diff checklist 交三方 ③P5/P7 真机过才 merge。
- **真机只在 P5/P7**：GBS/ARM 环境验证建库 + find_references 跨 TU（389/62 是必须看到的数字）。
- **纯 stdlib + from __future__ + 复用不重写 + 不越界 Phase**：CodeGraph 四条命脉。
- **dev_memory 双时点**：决策当下记 progress.md，收尾记 result.md。
- **P1 红线**：28 个旧测试不能破。
- **失败 3 次刹车；destructive git 先 status 后授权**。
- **对 Codex/三方实际说什么**：看 §5.5 话术卡，复制改 Phase 号即用。

需要时回来找我：Codex 报 [DESIGN_ISSUE] 你拿不准、写某个 Phase 的 review 重点清单、
或 P5/P7 真机环境搭建细节——接着帮你。
```

