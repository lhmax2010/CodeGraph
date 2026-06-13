# 外部 AI 开发 SOP（Codex / Claude Code + gstack）

> 三份文档里的**第 3 份 · 外部版开发执行**。适用：官方 GitHub 公开项目、实现工具 Codex 或 Claude Code。
> 前置：已用第 1 份《设计文档生成工具》产出并冻结了 `docs/design.md`。
>
> **怎么读这份文档（重要）**：
> - **加粗的「步骤 N」是开发人员要做的动作** ——你只需要做这些。
> - 每个步骤下方的 **🤖 AI 在能力/权限允许时做了什么** 是实现 AI 尝试自己干的活，**不用你操作**，
>   列出来让你知道幕后发生了什么。
> - 再下方的 **💡 为什么** 是原理，照做时可跳过，有疑问再看。
>
> **⚠️ 总原则（先读，避免误解）**：
> 本 SOP 是 Codex / Claude Code 的**执行协议，不是强制自动化引擎**。AI 应尽力按流程执行；
> 当 **gstack、subagent、真机环境、GitHub 权限、测试/覆盖率工具链，或更高优先级的平台/系统/
> developer 指令、当前用户明确指令**不支持某一步时，AI **必须停下并报告降级方案，不得假装已完成**。
> 也就是说——文档里"AI 做了 X"应理解为"AI 在条件允许时做 X，否则报告阻塞 + 给降级路径"。
>
> **优先级**：平台/系统/developer 指令 > 当前用户明确指令 > 本 SOP 与 AGENTS.md。AGENTS.md 和本 SOP 是**提示约束**，
> 不是强制执行器；冲突时以更高优先级指令为准。
>
> **一句话看懂分工**：顺利时从开 stage 到提 PR 大多由 AI 跑；**你真正要动手的只有三处**——
> ① 确认 AI 定的风险档；② PR 后做人工 + 三方 AI review；③ 拍板放行。merge 由 AI 在有权限时执行。

---

## 角色分工

- **你（开发人员）**：确认风险档、PR 后 review、拍板放行。**只评审决策，几乎不动手。**
- **实现 AI（Codex / Claude Code）**：开 stage、写代码、跑测试、subagent 复审或 checklist 复审、跑真机（有环境时）、提 PR、merge、收尾。
- **三方 Review AI**：Claude + ChatGPT + Kimi，**PR 之后由你手动 copy 代码过去**评审。
- **「人工 review」的完整含义**：= 你自己看 + 你把代码转给三方 AI review。两者合起来才是人工 review。

> 💡 **为什么这样分**：AI 负责执行（写、测、合），人负责把关。从开 stage 到提 PR 是 AI 的
> 条件允许时的自动化流水线；人只在「放行进主干」这个关键点介入，且介入时借三方异构 AI 补盲点。

---

# 一次性准备（每台机器/每个项目配一次）

> **Windows 用户先读**：本 SOP 命令按 **Git Bash** 写（Windows 推荐在 Git Bash 里跑）。两个坑：
> ① 必须在**真正的 Git Bash 终端**里跑，不要从 PowerShell 包一层调——`$HOME`、引号会被外层
>   提前展开导致出错；如必须从 PowerShell 调，用 `bash -s` 喂脚本才稳。
> ② **GBS 交叉编译 + 真机验证（sdb/ssh）跑不了纯 Git Bash**——GBS 工具链是 Linux 原生的，
>   这两步需要 WSL2 或一台 Linux 机/容器。Git Bash 只负责跑流程管理（git/dev_memory）。

## 步骤 0-0：环境预检 + 装依赖（每台机器一次，先做）

**先预检，看缺什么**（Git Bash）：
```bash
git --version       # 必需
codex --version     # 必需（用 Claude Code 则 claude --version）
node --version      # 必需（gstack 在 Windows 下要 Node 跑 Playwright）
npm --version       # 必需
bun --version       # gstack setup 必需
gh --version        # 仅当要 AI 自动提 PR 时需要（见步骤 5）
```
**缺什么按下面装（Windows）：**

- **Node.js + npm**（必装）：https://nodejs.org 下 LTS .msi，或 `winget install OpenJS.NodeJS.LTS`。
- **Bun**（gstack 必需）：PowerShell 里 `powershell -c "irm bun.sh/install.ps1 | iex"`。
  > 受限网络下这条可能 SSL/重定向失败；失败就 `npm install -g bun`（需先有 Node）。
- **gh（GitHub CLI）**（仅"AI 自动提 PR"用）：`winget install GitHub.cli`，装完 `gh auth login` 登录官方 GitHub。
  不想装 gh 也行——步骤 5 有"只 push、网页手动建 PR"的替代。

> 💡 **为什么先预检**：实测发现 gstack 的 `./setup` 在缺 Bun/Node 时直接报
> `Error: bun is required but not installed` 卡死。先把依赖补齐再装 gstack。

## 步骤 0-1：装 gstack（每台机器一次）

```bash
git clone --single-branch --depth 1 https://github.com/garrytan/gstack.git ~/gstack
cd ~/gstack
./setup --host codex --prefix
```
> 用 Claude Code 的人：把 `--host codex` 换成 `--host claude`，其余不变。
> `--host`+`--prefix` 组合官方无示例，装完务必实测确认命令真生成了。

**装成功的标志**（实测）：终端出现 `gstack ready (codex)`，且 `~/.codex/skills/` 下出现
一批 `gstack-*` skill（实测约 53 个）。用 Claude host 则在 `~/.claude/skills/`。

> ⚠️ **second-opinion 命令名取决于 host（实测重点，别搞错）**：`./setup --host codex` 装完，
> 跨模型 second-opinion 的命令是 **`/gstack-claude`**（因为本机已是 Codex，"另一个模型"是 Claude），
> **不是 `/gstack-codex`**。反过来 `--host claude` 装完才是 `/gstack-codex`。
> 本文后续凡提"second-opinion 命令"，Codex host 用户一律理解为 `/gstack-claude`。

> ⚠️ **gstack 安装可能受网络影响（实测两种结果都有）**：`setup` 会构建 browse binary、
> 拉 Playwright Chromium。实测在企业网下**有成功的**（Chromium 能启动），也**可能因 curl SSL
> 吊销检查失败**（见文末 Troubleshooting 第 ①②④ 条的修法）。若修了仍装不上，用下面替代方案。
> **替代方案（装不上 gstack 时）**：
> 1. **不用 gstack，退回纯手动流程**——本 SOP 里 gstack 命令（`/gstack-autoplan` 出计划、
>    `/gstack-review` Claude 审、second-opinion 命令做另一模型审、`/gstack-freeze` 锁范围）都有等价手动做法：
>    - `/gstack-autoplan` → 直接让 Codex/Claude Code 读 design.md 出实现计划
>    - `/gstack-review` / second-opinion 命令 → 本来步骤 5 的三方 review 就是手动的，照常做
>    - `/gstack-freeze` → 在 AGENTS.md 写死"只改本 stage 文件"（软约束）+ 你 PR 时把关
>    - `/gstack-learn` → 用 dev_memory 替代
>   也就是说：**gstack 装不上不阻塞主流程**，你照样能跑设计冻结→开发→PR 前两道门→PR→人工review→merge 前真机 gate。
> 2. 或在能联网的机器/WSL 装好 gstack 再带进内网（按公司策略）。

## 步骤 0-2：建项目目录骨架（每个项目一次）

> ⚠️ **先确认当前目录是 Git 仓库**（实测踩坑：不是仓库则开分支/baseline/PR/tag 全失败）：
> ```bash
> git rev-parse --show-toplevel   # 能输出仓库根路径才 OK
> git remote get-url origin       # 确认有远端（官方 GitHub）
> ```
> 不是仓库就先 `git init` 配好 remote 再继续。

```bash
# 注意 .dev_memory 带点、放项目根（与 AGENTS.md/附录 A 一致）
mkdir -p docs/design_changes docs/review docs/spinoffs docs/test-guides .dev_memory/_archived
touch docs/checkpoints.md .dev_memory/INDEX.md AGENTS.md
```
> ⚠️ **`.dev_memory` 统一放项目根、带点**。早期版本曾误写 `docs/dev_memory`，会导致 AI 按规约
> 建的 `.dev_memory` 和手动建的对不上——以本步为准。

## 步骤 0-3：把命令白名单 + 开发规约写进 AGENTS.md（每个项目一次）

把【附录 A】整段**原样粘贴**进 `AGENTS.md`。它含：gstack 命令白名单、R1–R14 执行约束、
dev_memory 完整模板。实现 AI 每个 task 自动读取，并在第一次干活时自动建好 `.dev_memory/` 骨架。

安装后跑 pre-flight：`/gstack-` 命令能出现、**second-opinion 命令**（Codex host=`/gstack-claude`，
Claude host=`/gstack-codex`）能调起第二模型、仓库 clean、远端是官方 GitHub。

> **登录 GitHub（用方式 A 自动提 PR 才需要）**：跑 `gh auth login` 登录官方 GitHub。
> 实测 `gh auth status` 默认是未登录的，不登录则 AI 无法自动建 PR/查 PR（可改用步骤 5 方式 B 手动建）。
> （Claude Code 一般已是登录态；Codex/gh 需各自登录。）

> **项目级 bootstrap（每个真实项目第一次）**：上面 0-2/0-3 要在**真实项目仓库根目录**做，不是在
> `~/gstack` 或随便一个目录。实测踩坑：在非项目目录跑会 `NOT_GIT` 且没有 `docs/design.md`。
> 进开发前确保：① 在项目 git 仓库内 ② 已 `gh auth login`（走方式 A 时）③ `docs/design.md` 存在且 Frozen。

> 💡 **为什么用白名单不手删目录**：gstack 很多 skill 面向网页/产品/部署，对嵌入式 C/C++ 没用，
> 浏览器栈还要下大依赖包受限网络装不动。但**别手删 gstack 目录**（会破坏它的升级和命令发现），
> 靠白名单 + pre-flight 控制。AGENTS.md 写的约束是软约束（降低跑偏概率），真正硬拦截靠后面的
> review gate、人工放行、`/gstack-freeze` 锁目录、git 回退。
> （若 gstack 没装上，本步的白名单不影响——按 0-1 的替代方案走手动流程即可。）

> ⚠️ **AGENTS.md 是提示约束，不是强制执行器**：AI 能遵守它的前提是——任务开始时读到了它，
> 且它不与更高优先级指令冲突。**优先级：平台/系统/developer 指令 > 当前用户明确指令 > AGENTS.md 与本 SOP。**
> 冲突时以更高优先级为准，AI 应说明冲突点，而不是盲目执行 AGENTS.md。

---

# 设计阶段（每个新功能/模块走一次）

## 步骤 1：确认总设计已冻结

确认 `docs/design.md` 存在且状态是 Frozen（第 1 份工具产出，且已过三方评审）。没有就先回第 1 份做。

预检命令（Git Bash）：
```bash
test -f docs/design.md && echo "design.md 存在" || echo "缺 design.md，先回第1份"
grep -i "Frozen" docs/design.md && echo "已冻结" || echo "未冻结，先走第1份的三方评审冻结"
```

> 🤖 **AI 在能力/权限允许时做了什么**：本步无 AI 动作，是你确认前置条件。
> 💡 **为什么**：开发必须有不漂移的基线。design.md 是"总设计"，每次具体变更从它派生，开发期不直接改。
> 实测踩坑：没有 design.md 就进开发阶段，AI 会无基线乱跑，所以这步硬卡。

---

# 开发阶段（每个 stage = 一个 Phase，循环执行）

> 下面步骤 2 到步骤 6，**绝大部分由 AI 在条件允许时执行**。你真正要做的只有：步骤 2 确认风险档、
> 步骤 5 做 review、步骤 6 拍板。其余你只是发起和等待。

## 步骤 2：让实现 AI 开新 stage，你确认它定的风险档

你只需对 Codex / Claude Code 说一句：
```
读 docs/design.md 和 .dev_memory/INDEX.md，开始下一个 Phase。
按 AGENTS.md 规约做开 stage 的准备，并告诉我你判断的风险档，等我确认。
```
然后**看它报上来的风险档，确认或纠正**：

| 改动碰到什么 | 风险档 | subagent复审 | 三方review |
|---|---|---|---|
| 平台稳定/播放路径/内存/线程/ABI/IPC | 高风险 | 做 | 三路 |
| 一般功能/跨模块重构 | 普通 | 做 | 两路 |
| 小修/单测/<200行 | 低风险 | 跳过 | 一路 |

> 🤖 **AI 在能力/权限允许时做了什么**：读 design.md + INDEX.md 确认当前进度 → 开分支 `phase/<N>-<描述>`
> → 记下 baseline commit hash → 跑一次 baseline 记录"改之前就失败的项" → 在对应 stage 的
> dev_memory 建 plan 部分 → **初步判断风险档报给你**。
> 💡 **为什么风险档要你确认**：它决定跑几路 review，直接影响成本和质量，值得你扫一眼。
> 20 行改到内存/线程/ABI 也算高风险——**先看改什么，再看改多少**，AI 可能判轻，你把关。
> 💡 **为什么先跑 baseline**：不先记"改之前就坏的项"，AI 改完后没法区分失败是新引入还是历史遗留。

## 步骤 3：确认 AI 复述的任务理解（restate 闸门）

实现 AI 起草实现计划后（`/gstack-autoplan`），会**用自己的话复述**这次要做什么、改哪些文件、验收标准。
你**看它复述对不对**：
- 对 → 回复「确认，开始」
- 不对 → 指出偏差，让它重新理解

> 🤖 **AI 在能力/权限允许时做了什么**：从 design.md 派生本 stage 的实施基线 + 追踪矩阵（每个决策对应验收）
> → `/gstack-autoplan` 起草计划 → 复述任务理解等你确认。
> 💡 **为什么要 restate 闸门**：让 AI 先证明它理解对了再动手，避免理解偏了写一大堆白干。
> 💡 **为什么追踪矩阵**：保证每个设计决策都落到实现+验收，否则会"设计写了但实现没覆盖全"。

## 步骤 4：等 AI 实现 + 自检（你不用操作，等结果）

确认后，**你等待**。实现 AI 尝试完成实现、确定性检查、覆盖率、subagent 复审、真机验证（有环境时）。
完成后报给你，进入步骤 5（提 PR）。**任一步因能力/权限/工具缺失做不了，AI 会停下报告 + 给降级方案，不假装完成。**

> 🤖 **AI 在能力/权限允许时做了什么**：
> 1. **实现**：若装了 gstack 用 `/gstack-freeze` 锁定改动目录；**没装 gstack 则用手动等价**
>    （AGENTS.md 写死"只改本 Phase 文件" + 自我克制），slash 命令不可用时 AI 会说明并走手动流程。
>    每做一个关键决策**当下就写进 dev_memory**。
> 2. **第一道门·确定性检查**：clang-format → clang-tidy → GBS 编译 → 冒烟，任一失败先修。
> 3. **第一道门·覆盖率**：跑 UT + coverage，行≥80%/分支≥70%（核心≥90%），**针对本次 touched files**
>    （不是全仓历史欠账）。按 R13 贴命令+输出。
>    - **没有 coverage 工具链时的 fallback**（嵌入式项目常见）：不要假装有覆盖率。三选一并报告你：
>      ① 补最小 coverage 工具（gcov/lcov 等）；② 降级为"关键路径测试清单"（列出本次改动必须覆盖的
>      场景 + 对应测试是否存在）；③ 标记为阻塞等你决定。**默认走 ②**，不让缺工具变成跳过测试。
> 4. **第二道门·subagent 内部复审**（普通档+；低风险跳过）：
>    - **有 subagent 工具**（如 Claude Code 的 Task subagent）→ 派独立子过程在干净上下文只读复审本次 diff。
>    - **没有 subagent 工具**（很多 Codex 环境）→ **不假装有**；改为生成一份 diff review checklist
>      （列出本次改动的风险点 + 待查项），交给步骤 5 的人工/三方 AI review 补上。
> 5. **第三道门·真机验证（merge 前 gate，不强求 PR 前）**：
>    - **有真机环境** → AI 在 PR 前跑（有真机环境时），对照追踪矩阵 TCT case，贴日志。
>    - **没真机环境** → AI 不跑，在步骤 5 提 PR 时**附一份真机验证 guide**，由你在 merge 前的人工 review
>      阶段在真实环境跑通。**真机没过不许 merge。**
> 6. 失败处理：同一问题最多试 3 次，第 3 次停下报告；GBS 配置/环境类错误停下报告不硬改。
>
> 💡 **为什么 gstack/subagent 要写 fallback**：它们不是 Codex 的默认能力——环境没装 gstack，slash
> 命令对 AI 就只是文字；没有 subagent 工具，"独立复审"也做不到。所以文档不把它们当必然能力，
> 没有就降级到手动等价 + 人工补，并显式报告，而不是假装跑过了。
> 💡 **为什么决策当下写 dev_memory**：LLM 收尾回忆决策会编造；当下记的是真实选择，可信。
> 💡 **为什么真机是 merge 前 gate 而非 PR 前**：AI 常没有真机环境，强求 PR 前会卡死；改成"merge 前
> 必须真机过"，既不挡住提 PR，又保证没真机验证的代码进不了主干。

## 步骤 5：人工 review（= 你自己看 + 转三方 AI review）

实现 AI 提 PR 后**停下等你**。这是你的核心介入点。**人工 review = 下面两件一起做**：

> **PR 怎么来（两种，按你环境选）**：
> - **方式 A·AI 自动建 PR**：装了 `gh` 并 `gh auth login` 过 → AI 直接用 `gh pr create` 建 PR。
> - **方式 B·手动建 PR**（没装 gh）：AI 只 `git push` 推分支到官方 GitHub → **你在 GitHub 网页
>   点 "Compare & pull request" 手动建 PR**，贴上 PR 描述（目标/改动/测试/风险）。
> 两种 PR 内容要求一样。告诉实现 AI 你用哪种，它照做。

**5.1 如果 AI 没真机环境**：先照它附的真机验证 guide，在真实环境（WSL/Linux）跑一遍，确认真机通过。
（真机没过不要 merge。）

> ⚠️ **外发前硬检查（转三方 AI 前必做）**：三方 review 要把内容贴给外部 AI（Claude/ChatGPT/Kimi），
> 即使是公开 repo，外发前也**必须确认不含**：secret/token/密钥、客户或个人数据、内部主机名/路径、
> 设备 IP、用户名、受限 license 片段。**检查范围不只是 diff——PR 描述、测试日志、dev_memory、真机
> 日志、截图都要查**（token、内部路径、设备 IP、用户名更常出现在日志而非 diff 里）。
> 有任何一项 → 先脱敏或不外发该部分。**这是硬门，不是建议。**

**5.2 你自己看 PR** + **把代码转给三方 AI review**（按风险档，你手动 copy diff 过去）：
- 第一路 **Claude**（若装了 gstack 也可用 `/gstack-review` 触发；没装就手动贴）：`这是代码改动，独立 review 找 bug，重点内存/线程/ABI/边界，逐条标严重程度。[贴diff]`
- 第二路 **ChatGPT**（普通档+；gstack second-opinion 命令：Codex host=`/gstack-claude`、Claude host=`/gstack-codex`，没装 gstack 就手动贴）：同上，末尾加 `Claude 已审，发现：<贴Claude致命/重要finding>，请确认或反驳并补充。`
- 第三路 **Kimi**（仅高风险）：同上格式，末尾贴前两路 finding。

**5.3 把三方 + 你自己的意见汇总，按等级交给实现 AI 处理**（R14 闭环）：

| 等级 | 处理 |
|---|---|
| `[BLOCKER]` | 必须修复才能合并 |
| `[MAJOR]` | 原则上必须修；不修需你在 review_result.md 显式确认放行 |
| `[MINOR]` | 记进 dev_memory 的"遗留 TODO" |
| `[NIT]` | 可选采纳 |

有问题 → 实现 AI 修 → 重跑测试 → 更新 PR → 你再 review，循环到通过。

> 🤖 **AI 在能力/权限允许时做了什么**：提 PR（标题 `[Phase N] <描述>`，描述含目标/改动/UT结果/覆盖率/R13命令
> 输出/关联 design.md 章节/已知风险；无真机环境时附真机验证 guide；推到官方 GitHub）→ 停下等你
> → 收到你汇总的意见后，按 R14 修复（更新 代码+测试+dev_memory+review_result.md），再更新 PR 等你复确认。
> 💡 **为什么三方 review 在 PR 之后**：subagent（PR前）已消除自审偏误，但消不了模型盲区；三方
> 异构评审补盲区，放在 PR 后作为"人工 review"的一部分——人工 review 不是只有人看，而是人+三方AI。
> 💡 **为什么按证据不按模型仲裁**：意见冲突时信 真机日志 > 静态工具 > 模块负责人 > 模型说法，
> 不写"安全以某模型为准"这种把模型权威化的规则。

## 步骤 6：拍板放行（你点头，AI 在有权限时执行 merge 和收尾）

review 通过后，你回复实现 AI「通过，可以 merge」。**之后 AI 在权限/CI 允许时执行收尾。**

> 🤖 **AI 在权限允许时做了什么**：执行 merge（你不手动合，但**前提是有 merge 权限、分支保护/CI
> 已满足**——若分支受保护、CI 未过、无权限，AI 会**停下报告"无法 merge + 原因"**，由你处理，不强行合）
> → 写 dev_memory 收尾（UT结果/覆盖率/PR链接/commit/状态/遗留TODO/下一步）→ 更新 INDEX.md →
> 打 checkpoint（高风险 `git tag checkpoint/phase_N_*` + 登记 checkpoints.md 含"回退后状态一句话"；
> 低风险只记 commit hash）→ 过一遍 spinoffs/ → 准备开下一个 stage。
> 💡 **为什么 merge 可能要你处理**：merge 受 GitHub 权限、分支保护、CI 必过等外部条件约束，不是 AI
> 单方能保证的。AI 有权限就合，没有就报告阻塞——绝不绕过 CI 或强推。
> 💡 **为什么 PR 后必须停下等你**：这是整条流程**唯一的人工强制 gate**。你确认前 AI 不准 merge、
> 不准开下一个 stage。

---

# 出问题时的快速处理（这些一般也是 AI 在做，你只需知道发生了什么 / 必要时下指令）

> 🔴 **destructive git 操作硬约束（最高优先级）**：执行 `git reset --hard`、强推（force-push）、
> 删分支、`checkout -- .` 等会**丢失未提交改动**的操作前，AI **必须**：① 先跑 `git status --short`
> 确认没有未提交/未跟踪的用户改动会被覆盖；② 把要执行的命令和影响**报告给你、得到你明确授权
> 目标后**才执行。AI 不得自行 reset/force-push/覆盖工作区。** 有未提交/未跟踪改动时，
> **AI 只报告，不得自行 stash、reset、checkout、clean**——由用户决定 stash/commit/备份/丢弃。

| 情况 | 怎么办 |
|---|---|
| AI 改坏代码 | AI 先 `git status --short` 检查 → 报告要回退到哪个 baseline/tag → **你授权后**才 `git reset --hard <目标>` |
| 同一问题改 3 次还不对 | AI 会自动停下报告。你让它先查根因再修，或人介入 |
| AI 发现 design.md 矛盾 | 它会停下输出 [DESIGN_ISSUE] + 建 change_N.md。**你**回设计阶段决策，它不自行改 |
| 编译失败像环境问题 | AI 会停下报告。人查 GBS 配置/路径/依赖，别让它改源码硬怼 |
| subagent 派不出/收不到报告 | 模型可能撑不住或环境没有 subagent 工具。改用开一个全新会话手动贴 diff 复审，或转人工/三方 |
| 怀疑 AI 记忆混乱/和代码对不上（Rollback） | **你**指定可信检查点 → AI 把该点之后的 stage 记忆归档 → **先 `git status --short` 确认无未提交改动、经你授权** → `git reset --hard checkpoint/phase_X_*` 退到该点 → 更新 INDEX 指回检查点 → AI 丢弃当前记忆，只以 INDEX+检查点 memory 重读重规划 |

> 💡 **为什么要 Rollback**：AI 长对话会"记忆在 stage03、代码却在 stage05"错位。Rollback 让记忆和
> 代码一起退回同一可信点，比"挽救"乱掉的会话有效。归档的 stage 不读不引用。

---

# 核心铁律（一页速查）

1. **你只做三件事**：确认风险档、PR 后 review（人+三方AI）、拍板放行。其余由 AI 在条件允许时执行。
2. **设计冻结**：design.md 总设计基线，任何人/AI 不直接改；改走 R1 提案流程。
3. **三道门**：① 确定性检查+覆盖率 → ② subagent 复审或 checklist 复审（PR 前完成；有 subagent 工具
   就用，没有就出 diff review checklist 交人工/三方）→ ③ 真机验证（**是 merge 前的 gate，不强求 PR
   前**：有真机环境就 PR 前跑；没有就 PR 时附 guide，由你在 merge 前的人工 review 阶段跑通）。三道门全过才能 merge。
4. **人工 review = 人 + 三方AI**，在 PR 之后；通过后 AI 在**有权限且 CI/分支保护满足时执行 merge，否则报告阻塞**。
5. **dev_memory 双时点**：决策当下记原因（防编造），收尾记客观事实（PR/commit/结果）。
6. **真机为唯一最终验收**：有环境 AI 跑，没环境 AI 附 guide 你跑；真机过了才算 done。
7. **restate 闸门 + 范围约束**：实现前 AI 先复述理解，确认才动手；装了 gstack 用 `/gstack-freeze`
   锁定/约束改动范围，无 gstack 时为软约束（自我克制）+ review gate 把关，不是物理锁。
8. **失败 3 次刹车**：AI 自动停下查根因，不堆 patch。
9. **数据边界**：用官方 GitHub 公开项目。但**公开 repo 不等于可无脑外发**——日志/dev_memory/截图
   仍可能带内部路径、设备 IP、用户名。外发前一律按硬检查过滤 diff / PR 描述 / 日志 / dev_memory / 截图。

> 许可证提醒：高风险模块 AI 生成的 C/C++ 合入前过许可证扫描（按公司政策），防混入 GPL/Apache 片段。

---

# 附录 A：`AGENTS.md` 完整内容（步骤 0-3 粘贴用）

> 把下面整段（从 `# gstack 命令白名单` 到最后）粘贴进项目根的 `AGENTS.md`。

~~~markdown
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
~~~

---

# 附录 B：Windows 企业网络 Troubleshooting（实测踩坑）

> 以下是在 Windows 企业网 + Git Bash 环境实测遇到的坑和修法。装依赖/装 gstack 卡住时查这里。

## ① curl 报 `CRYPT_E_NO_REVOCATION_CHECK`（证书吊销检查失败）

企业网代理常拦截证书吊销检查（CRL/OCSP），导致 Git Bash 的 curl 失败。临时加参数跳过吊销检查：
```bash
curl --ssl-no-revoke <url>
```
> 仅用于内网可信源；这是跳过吊销检查，不是跳过证书校验。

## ② Bun 官方 installer 失败（它内部调用不带 --ssl-no-revoke 的 curl）

Bun 的一键脚本（`irm bun.sh/install.ps1` 或 `curl ... bun.sh/install`）内部会再调 curl，
没法注入 `--ssl-no-revoke`，所以在 ① 的环境下会失败。**手动装 Bun**：
```bash
# 1. 浏览器/可信渠道下载 Bun release zip：
#    https://github.com/oven-sh/bun/releases  → bun-windows-x64.zip
# 2. 解压，把 bun.exe 放到一个固定目录，例如：
mkdir -p ~/.bun/bin
cp /path/to/bun.exe ~/.bun/bin/
# 3. 创建 bunx shim（bunx = bun x）：
printf '#!/bin/sh\nexec "$HOME/.bun/bin/bun.exe" x "$@"\n' > ~/.bun/bin/bunx
chmod +x ~/.bun/bin/bunx
# 4. 加进 PATH（写进 ~/.bashrc）：
echo 'export PATH="$HOME/.bun/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
bun --version   # 验证
```

## ③ gstack setup 在 Windows 强依赖 Node.js（不只是 Bun）

实测：Windows 上 `./setup` 需要 **Node.js**（Playwright 那套靠 Node 跑），不是只有 Bun 就行。
所以 0-0 的强前置是 **Node + Bun 都要装**，缺 Node 也会失败。

## ④ Playwright Chromium 下载失败 → 手动缓存

gstack setup 会拉 Playwright Chromium，企业网可能下不动。手动放进缓存目录：
```bash
# 1. 可信渠道下载对应版本的：
#    chrome-win64.zip 和 chrome-headless-shell-win64.zip
# 2. 解压到 Playwright 缓存目录（版本号目录名按 Playwright 要求）：
#    %LOCALAPPDATA%\ms-playwright\chromium-<rev>\
#    %LOCALAPPDATA%\ms-playwright\chromium_headless_shell-<rev>\
# 3. 在对应目录放一个空标记文件，告诉 Playwright "已装好"：
#    在每个 chromium 目录下创建 INSTALLATION_COMPLETE 空文件
```
> 具体 `<rev>` 版本号看 setup 报错里 Playwright 期望的版本，或 `npx playwright install --dry-run` 查。
> 实测这套手动缓存做完后，Chromium 能正常启动、gstack setup 通过。

## ⑤ second-opinion 命令名认错（最容易踩）

`--host codex` 装出来的跨模型命令是 `/gstack-claude` **不是** `/gstack-codex`。
认错会以为"命令没装上"。见 §0-1 的说明：Codex host 用 `/gstack-claude`，Claude host 用 `/gstack-codex`。

## ⑥ PowerShell 包 Git Bash 导致变量被提前展开

从 PowerShell 里包一层调 Git Bash 命令时，`$HOME`、引号会被外层 PowerShell 先展开，导致路径/引号错乱。
**对策**：直接在 Git Bash 终端里跑；若必须从 PowerShell 驱动，用 `bash -s` 把脚本喂进去最稳。
