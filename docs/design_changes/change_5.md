# change_5：MVP（background-index）下 search_symbol / get_definition 不产 not_found

- 变更类型：R1 变更（DESIGN_ISSUE 修正）
- 触发阶段：Phase 6（search_symbol + get_definition 首次端到端集成）
- 发现方式：P6 多路异构 review（四轮逐层 + 一轮整体审查）
- 决策日期：2026-07-02
- design 版本：v1.4.4 → v1.4.5

---

## 1. 问题

P6 首次把 P1–P5 接起来跑真实查询。`search_symbol` 的"项目级 not_found"能力经四轮多路
review 逐层挖出**四层虚假否定**，逐层修复：

1. **bg=False 借 complete health 做负证明**：单 TU 模式没消费全局索引，却把 P5 的
   `complete` index_health 传给 P2，P2 据此断言 not_found。修：bg=False 降 unknown/current_tu。
2. **ready 判据被 header 命中误触发**：用用户查询 symbol 判 ready，symbol 在单 TU/header
   就可见 → 全局索引没加载完就误判 ready → get_definition 拿到 .h 声明而非 .c 实现。
   修：sentinel 探针 + path_suffix 匹配。
3. **截断窗口致 total 算成 0**：`workspace/symbol` 是 fuzzy，前 100 条可能全是近似结果，
   exact 被挤到窗口外 → total_hits 算成 0 → 误判 not_found。修：窗口可能截断且 total=0 时
   不 not_found。
4. **kind_filter=None 默认成可穷尽 function**：不过滤（任意符号）却被当成"查普通函数"，
   把"不是函数"误报"不存在"。修：kind=None → symbol_kind=UNKNOWN（不可穷尽），
   只有明确 function/type/variable 才允许 not_found；get_definition 同样改 UNKNOWN。

四层修复后，三路整体审查（heterogeneous multi-AI）**独立收敛到同一结论**：剩下的是
**第五层、且是结构性的、补丁不可达的**虚假否定。

---

## 2. 根因（为什么补丁不可达）

`search_symbol` 底层是 clangd 的 `workspace/symbol`——一个 **fuzzy 匹配、无"结果已穷尽"
信号**的查询。`total_hits==0` 只能证明"返回窗口里没有 exact"，**不能证明"项目里不存在"**。
更深的、四层补丁都够不着的洞：

- **R-技1（design 自己的 Top-1 风险）静默漏 TU**：一个函数定义在某个未被索引的 TU 里
  （clangd 索引该 TU 失败但未报错）→ `workspace/symbol` 返回空。但 P5 的 index_health 是
  `shards ≥ unique_TU` 的**粗判下界**（~2.75 shards/TU），其他 TU 的富余 shard 可让
  `shards ≥ unique_TU` 成立 → `complete`。于是"存在但未索引到"的空结果，与"真不存在"的
  空结果，**在可观测输出层完全不可区分**。
- **dependency guard 对 search 恒空**：`ClangdAdapter.search_symbol` 返回 observation 不带
  diagnostics，P2 的 `_dependency_from_diagnostics` 永远得到 complete——"依赖完整"这个
  not_found 前提对 search 恒真、什么都没守。
- **current_tu clamp 对无 TU 的查询不自洽**：INV14c 把 background-index 的 not_found 钳到
  `negative_scope=current_tu`，但 `search_symbol` 无 file/pos、没有"当前 TU"，
  `current_tu of nothing` 语义错乱；消费方看 `status=not_found` 会理解成"项目级不存在"，
  而这恰恰是不能保证的。

**结论**：区分"真不存在"与"存在但未索引到"，需要 background-index 没有的**逐 TU 台账**。
这不是可观测输出层加条件能解决的——补丁不可达。

---

## 3. 决策（方案 B）

**MVP（background-index）阶段，`search_symbol` 与 `get_definition` 均不产 not_found，
空结果一律 `unresolved`。诚实的 not_found（项目级与 TU 级）待二期 clangd-indexer 的逐 TU 台账。**

- `search_symbol`：无 file/pos、无合法 negative_scope，结构性不能 not_found。
- `get_definition`：虽有 file/pos，其 current_tu 级 not_found 仍受 R-技1 静默漏 TU 与
  diagnostics 异步等待影响，无法诚实证明，故 MVP 一并不产 not_found（此举同时关闭了
  get_definition 的 diagnostics-race 虚假否定路径）。

### 候选方案对比
- **方案 A**（收集 warmed file 的 diagnostics）：只覆盖一个 TU，不能根治漏 TU。否决。
- **方案 B1**（只砍 search_symbol，保留 get_definition 的 current_tu 级 not_found）：
  search_symbol 无 file/pos 结构性不能 not_found；get_definition 有 file/pos，其 current_tu 级
  not_found 结构上自洽。但 get_definition 的 current_tu not_found 仍受 R-技1 静默漏 TU 与
  diagnostics 异步竞态影响——空结果无法诚实区分"真不存在"与"存在但未索引/未等到诊断"。
  B1 保留了 get_definition 能力，代价是留一个已被证明不可靠的负证明通道。可在二期前恢复
  （若 diagnostics-wait 竞态修复 + 确认定义所在 TU 已索引），但 MVP 阶段收益小、风险实。
  否决（倾向保守）。
- **方案 B2**（search_symbol 与 get_definition 均不产 not_found，一律 unresolved）：诚实、简单、
  彻底根除虚假否定面（含 get_definition 的 diagnostics-race 路径）。**采纳**。相对 B1 更保守——
  用"MVP 阶段 get_definition 也不 not_found"换"零虚假否定面 + 实现最简（不维护任何 MVP
  not_found 路径）"，与"MVP 先诚实保守、二期 clangd-indexer 统一恢复"的分期思路一致。
- **方案 C**（保留 not_found 但标 BEST_EFFORT、消费方自行降级）：把不可信的 not_found
  抛给消费方，违背"诚实的可信度标注"立身之本。否决。
- **方案 D**（等二期恢复）：与 B2 等价，B2 已含"二期恢复"。

---

## 4. 理由

1. **与现有不变量的隐含结论一致（search_symbol 部分严格，get_definition 部分为额外判断）**：
   INV14a（not_found ⟹ negative_scope ∈ {current_tu, indexed_project}）+ INV14c
   （background-index ⟹ ≠ indexed_project）已隐含"background-index 下 not_found 只能
   current_tu 级"。
   - **search_symbol**：无 file/pos ⟹ 无 current_tu ⟹ 无合法 negative_scope ⟹ 本就不该
     not_found。这部分由 14a+14c **直接隐含**，INV14d 只是显式化。
   - **get_definition**：有 file/pos，14a+14c 本**允许**其 current_tu 级 not_found；INV14d 把它
     也纳入"不产 not_found"是**额外的可靠性判断**（受 R-技1 漏 TU / diagnostics 异步影响不可
     诚实证明），不是 14a+14c 的直接推论。此处 INV14d 强于现有不变量的隐含结论。
   本变更整体落实到实现（P1 check_invariants + P6 路径）。
2. **与 design 已指明方向一致**：C-1（MVP 项目级排除法需降级）、R-依2/§3.5（诚实项目级
   负证明待 clangd-indexer 逐 TU 台账）早已指明。本变更是落实，不是新方向。
3. **补丁不可达**：第五层在可观测输出层不可区分，唯一诚实选择是不产出。
4. **固化 P6 现状、对齐改动最小**：第四层修复已让 search_symbol/get_definition 默认不
   not_found；方案 B 固化并显式化，P6 对齐主要是确认 + 去掉 explicit-kind_filter 的
   not_found 残留路径。

---

## 5. design 改动清单（v1.4.5）

1. **新增 INV14d**：index_backend=background-index ⟹ 不产 not_found（结果 unresolved）。
   含推导链 + "放行约定"（对二期 clangd-indexer 的合法 not_found 放行，与 INV19 同构）。
2. **C-1 改写**：不产 not_found、一律 unresolved（不再让消费方降 BEST_EFFORT）。
3. **§4.1.1 签名契约注释**：MVP not_found 契约。
4. **R-技1 缓解措施**：三重钳制 → 四重（含 14d，落实到 MVP 不产 not_found）。
5. **§4.4 路由状态机分支 2**：not_found 规则加"二期 / MVP"分叉（MVP 走 unresolved）。
6. **§3.3 数据流**：空结果去向 → unresolved。
7. **INV20 交叉引用**：与 INV14d 正交（来源资格 vs 后端可用性）。
8. **P5 注 / 验收清单**：INV14c → 含 14d 的钳制验证。
9. **§0 版本号 + changelog**：v1.4.4 → v1.4.5。
10. **散落引用同步（两轮多路 review 揪出的 6 处漏扫）**：改主条款（INV14d/C-1/R-技1）时，
    以下散落的 not_found/current_tu 规范性引用经两轮异构 review 逐处同步为 change_5 语义
    （体现"改冻结文档易漏连带引用"这一反复出现的风险，靠多轮多路兜住）：
    - §4.3 状态表 `status=NOT_FOUND` 行（原"MVP 仅 current_tu 级、可作负证据"→ MVP 不产出）
    - §4.3 状态表 `index_health=incomplete/unknown` 两行（补"MVP 本就不产 not_found"）
    - §4.4 路由状态机分支 2 not_found 规则（加二期/MVP 分叉）
    - §4.2 兼容矩阵 `negative_scope=current_tu` 行注释（原"MVP 也可…只对当前 TU 诚实否定
      负责"→ 矩阵仅形状兼容、供二期校验、MVP 恒不触发）【第二轮 Codex 补抓】
    - §5.4 降级策略（原"降为 current_tu 或 unresolved"→ 一律 unresolved）
    - §6 Top3 / §10 DoD（三重→四重、INV14a/b/c → INV14a/b/c/d）
    第一轮抓 5 处、第二轮又抓 1 处（兼容矩阵）、第三轮穷尽确认无第 7 处 → 清零冻结。

---

## 6. 二期恢复条件

clangd-indexer 提供**逐 TU 索引台账**后，可区分"真不存在"与"存在但未索引到"，届时：
- `search_symbol` 可恢复项目级 not_found（negative_scope=indexed_project）；
- `get_definition` 可恢复 TU 级 not_found；
- INV14d 的"放行约定"已为此预留（check_invariants 对 clangd-indexer 后端的合法
  not_found 放行）。

---

## 7. 对 P7（find_references）的警示

P7 的 find_references 同样面对"证明穷尽"问题（枚举全部引用、确认没漏）。两点直接适用：

1. **INV14d 直接管 find_references**：background-index 下，空 find_references 结果**不是**
   "确认无引用"，必须是 unresolved（同 search_symbol/get_definition，受 R-技1 漏 TU 影响，
   空结果不可诚实证明"项目里无引用"）。P7 继承"空结果→unresolved"规则。
2. **穷尽性声明的诚实性**：find_references 的 is_exhaustive_within_scope=True 是有意义的
   "已穷尽"信号（INV21 允许 positive 结果声明 exhaustive），但在 background-index 下同样受
   R-技1 漏 TU 影响——若某 TU 静默未索引，其中的引用会被漏掉，此时声明 exhaustive 是虚假的。
   P7 要么不在 background-index 下声明 exhaustive，要么给出独立的完整性证据。

P6 四层 + 结构性第五层的总教训：**任何"证明完整/穷尽/不存在"的判断，都要问"我的数据
窗口可能不全吗？不全就不能下结论"**——这对 find_references 的空结果（→unresolved）和
穷尽性声明（→审慎）都适用。
