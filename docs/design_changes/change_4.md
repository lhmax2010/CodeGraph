# Design Change 提案 #4（P2 最终 review 发现的 design 内部矛盾）

> 状态：**待 design owner 决策**
> 来源：Phase 2 最终收口 review，一路（最较真路）抓到 §7 P6 与 R-依1 两条冻结陈述矛盾，
>       经人工在代码+design 双向核实属实。
> 性质：**design.md 两处冻结陈述互相矛盾**，非 P2 实现错误（P2 忠实实现了 §7 P6）。
> 与 P2 merge 的关系：**不阻塞 P2 merge**（P2 桩开发、不接真实 tree-sitter，不触发此矛盾）；
>       **必须在 P6（首次真实集成 clangd+tree-sitter）前解决**，否则 P6 行为不确定。

---

## 项 1【MAJOR · P6 前必修】§7 P6「无 helper 降级一切」与 R-依1「功能不受损只是少候选」矛盾

**矛盾两方**（design.md）：
- §7 P6 (line 859)：「P4 缺失时要素2 保守标'不满足'并降级」
- R-依1 (line 723) / line 705：tree-sitter binding 不可得时「功能不受损只是少候选」

**矛盾推理**：要素2 的 preproc 判定由 tree-sitter 实现（MVP 用 tree-sitter AST preproc_* 判定）。
故「无 syntax helper」≡「tree-sitter 不可用」。于是：
- 按 §7 P6：tree-sitter 不可用 → 要素2 全判盲区 → 所有语义结果降级入候选 → **P6 永远出不了 OK**。
- 但 R-依1 承诺：tree-sitter 不可用 → 功能不受损，**只是少候选**（仍应能出 OK 语义结果）。

两者不可能同时成立：丢 tree-sitter 要么「只丢候选」（R-依1），要么「连 OK 都没了」（§7 P6 后果）。
P2 已忠实实现 §7 P6（_has_preprocessor_blind_spot: provider is None → True），内部安全，
但这使 R-依1 的承诺无法兑现。

**修法（二选一，design owner 定）**：
- A：接受 tree-sitter 为「语义 OK」的硬依赖。修 R-依1 措辞为「tree-sitter 不可用时无法
  确认要素2，语义结果降级为候选；clangd 仍工作但不产 OK 语义」。诚实但削弱可用性。
- B：提供一个最小的 stdlib preproc 启发式（不依赖 tree-sitter，如基于行内 `#`/已知宏名的
  粗判），使 syntax helper「总是存在」。tree-sitter 仅增强候选能力。保住 R-依1 承诺。
- 倾向 B：保住「丢 tree-sitter 只丢候选」的设计承诺，代价是写一个粗糙但纯 stdlib 的 preproc
  判定。具体取舍由 design owner 在 P6 前定。

---

## 项 2【MINOR · P6 前厘清】MACRO symbol_kind 一律降级，宏定义永远 OK 不了

**现状**：routing.py `_has_preprocessor_blind_spot`：`symbol_kind == MACRO → return True`（一律盲区）。

**问题**：这混淆了两件事——
- 「符号本身是宏」（get_definition 查一个宏的定义）：宏的**定义位置**是真实源码行，应能 OK；
- 「位置是宏展开伪位置」（要素2 真正关心的）：clangd 把某符号解析到宏展开处，不可信。
当前一刀切：只要 symbol_kind==MACRO 就降级，导致 get_definition/search 一个宏永远返回
UNRESOLVED+候选，出不了 OK。这比 §4.4 要素2 的本意更严，且 design 未写明此行为。

**修法**：design owner 厘清 MACRO 的预期——
- 若「宏定义可以是 OK 语义结果」：去掉 symbol_kind==MACRO 短路，只靠位置判定要素2；
- 若「宏一律保守降级」是有意为之：在 design §4.4 写明此约定。
建议前者（宏定义是真实源码，应可 OK），但由 design owner 定。

---

## 处理建议
- 两项均 **P6 前必须解决**（P6 首次真实集成 tree-sitter 才触发），**不阻塞 P2 merge**。
- 项1 是真矛盾必须二选一；项2 是行为澄清。
- P2 代码无需为此改动（它忠实于现行 §7 P6）；解决方案在 P6 实现 tree-sitter adapter 时落地。
