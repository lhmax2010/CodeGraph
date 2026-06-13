# Design Change 提案 #1（P1 实现期发现）

> 状态：**待 design owner 决策**（记录，不阻塞 P1 merge）
> 来源：Phase 1 实现 + gstack Claude review + 人工核查，发现两处 design.md 元数据层小瑕疵。
> 性质：均非实现错误，是 frozen design 本身的设计层遗留，实现忠实照 design 写出后暴露。

---

## 项 1：INV13 与 INV14a 在 NegativeScope 三值下逻辑重叠（INV14a 不可达）

**现状**：design.md §4.2.2
- INV13：not_found ⟹ is_exhaustive_within_scope ∧ negative_scope ≠ none
- INV14a：not_found ⟹ negative_scope ∈ {current_tu, indexed_project}

**问题**：NegativeScope 枚举只有 {current_tu, indexed_project, none} 三个值。
INV13 已拒绝 none，则 INV14a 的"∈ {current_tu, indexed_project}"等价于"≠ none"，
与 INV13 后半句重复。check_invariants 按顺序执行时，_check_inv14a 永远不会触发（死代码）。

**影响**：无功能 bug（逻辑仍正确，只是冗余）。但 INV14a 作为独立检查函数永不命中，
其单测只能验证"合法组合不被误杀"，无法验证"非法组合被拒"（因为非法组合先被 INV13 拦）。

**建议选项**：
- A（推荐·零改动）：接受现状，在 design.md INV14a 处加注"在当前 NegativeScope 三值下，
  其否定面已由 INV13 覆盖；INV14a 保留为显式契约表达 + 防 NegativeScope 未来扩值时的护栏"。
- B：把 INV14a 并入 INV13 描述，去掉独立编号。
- 倾向 A：保留 INV14a 作为"未来若 NegativeScope 加值（如 global）时的占位防线"，语义更清晰。

---

## 项 2：make_error_credibility 占位 source=clangd 语义不够中性

**现状**：design.md §4.3 规定 INVALID_REQUEST/FAILED 的 status_credibility 占位用
source=clangd, certainty=syntactic, ...

**问题**：INVALID_REQUEST（参数错误）/部分 FAILED（如引擎未初始化）与 clangd 无关，
却标 source=clangd。invariant-legal（能过校验），但语义上"把一个和 clangd 无关的错误
归因到 clangd"不够干净。根因：Source 枚举无 UNKNOWN/NONE 中性值。

**影响**：无功能 bug。消费方若按 source 统计引擎健康度，会把参数错误误计入 clangd。

**建议选项**：
- A：design.md 给 Source 增加 NONE/UNKNOWN 值，make_error_credibility 用它占位。
  代价：动 source 枚举（冻结字段），需评估对 INV1/INV2 的影响（NONE 不该触发 semantic⟹clangd）。
- B（推荐·零改动）：接受现状，在 design.md §4.3 注明"占位 source=clangd 仅为满足
  schema 必填，不代表错误来自 clangd；消费方统计引擎健康度时应按 status 而非 source 过滤
  INVALID_REQUEST/FAILED"。
- 倾向 B：动 Source 枚举牵连不变量，收益（语义微洁）不抵风险；加注澄清成本最低。

---

## 处理建议
两项均为零功能影响的设计层小瑕疵。**建议都走"选项 B/A 的零改动 + design.md 加注"**，
在某次设计微调时统一更新 design.md 注释，不单独为此返工。P1 代码无需改动，可正常 merge。
