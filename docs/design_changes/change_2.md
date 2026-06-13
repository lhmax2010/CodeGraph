# Design Change 提案 #2（P1 多路 review 发现的冻结设计矛盾）

> 状态：**已接受并应用（design.md v1.4.1）**；项3 的 is_exhaustive 半句经复核缩为"仅 unresolved"，不锁 positive
> 来源：Phase 1 收口多路 review（ChatGPT / Kimi Code / Gemini 四路），两路独立抓到 QR7×INV9
>       矛盾（BLOCKER），并经人工在真实代码上验证属实。
> 性质：**冻结设计（design.md）层面的契约矛盾**，非 P1 实现错误。P1 代码忠实照 design 实现，
>       是 design 本身的规则无法联合满足。必须改 design.md（走 R1），P1 代码随之微调。
> 影响：若不修，P2 实现 QR7 容器校验时会在最常见路径（entity 查询候选）上撞到不可满足契约。

---

## 项 1【BLOCKER】QR7 的 relation==may 与 INV9 在 entity 候选上不可联合满足

**矛盾三方**（design.md）：
- QR7（§4.1.4）：∀ syntactic_candidate，credibility.relation == may
- QR8（§4.1.4）：candidate.credibility.query_kind == query.kind
- INV9（§4.2.2）：query_kind == entity ⟹ relation == n/a

**推理**：search_symbol / get_definition / find_references 都是 entity 查询（§4.1.1），
且是 tree-sitter 候选的主要生产者（§4.4「search_symbol 自动补候选」；§4.1.4「search_symbol
若只有候选…syntactic_candidates 非空是合法可用结果」）。对这类候选：
QR8 ⟹ query_kind=entity ⟹ INV9 ⟹ relation=n/a ⟹ **违反 QR7 要求的 relation=may**。
没有任何 relation 取值能同时满足 QR7 + QR8 + INV9。

**P1 已暴露此矛盾**（验证）：
- factories.treesitter_entity_resolved() 产 relation=n/a，过 check_invariants（符合 INV9），
  但 P2 实现 QR7 时会拒它。
- test_phase1_metadata.py 把该 credibility 装进 Candidate，即 P1 测试已编码了 QR7 会拒的形状。

**修法（推荐）**：QR7 的 relation 规则放宽——
```
原：∀ candidate: relation == may
改：∀ candidate: relation ∈ {may, n/a}   （等价表述：relation != must）
```
保留真实意图「候选绝不声称 must（必然关系）」，同时兼容 INV9（entity 候选 n/a、relation 候选 may）。
design.md 需改：§4.1.4 QR7、§4.1.2 Candidate [契约] 注释（line ~334）、§4.4 line ~600。

**P1 随之微调**：treesitter_entity_resolved 工厂不变（它本就 n/a，现在合法了）；
不需要改 P1 代码逻辑，只需在 P1 加一条"候选 relation∈{may,n/a}"的预期说明（QR7 实现在 P2，
但 P1 的工厂/测试现在与修订后的 QR7 一致，无冲突）。

---

## 项 2【MAJOR】not_found 未锁死 clangd ∧ semantic ∧ ¬blind_spot —— 三种虚假否定能过校验

**问题**：整个系统的立身之本是「绝不向 not_found 误升」（§5.4）。INV12 只对 tree-sitter
做了这个约束（tree-sitter ⟹ ¬not_found），但底层原则——非语义/受盲区影响的结果无权断言
"不存在"——没有推广。以下三种组合当前都能过 check_invariants（已在真实代码验证通过）：

| 组合 | 应当 | 实测 |
|---|---|---|
| not_found + blind_spot_affects_result=True | 拒 | **通过** ← 漏洞 |
| not_found + source=clangd + certainty=syntactic | 拒 | **通过** ← 漏洞 |
| not_found + source=log_search (+ syntactic) | 拒 | **通过** ← 漏洞 |

第三条最尖锐：schema 为二期预留了 log_search/exact_syntactic（§4.2.1「避免二期破坏冻结契约」），
INV19 专门守了它的 certainty，**但没守它的 not_found**——日志匹配是 grep/AST 级，按 INV12
同样的道理根本无权确认"不存在"，却能声称 not_found。预留做了一半：值留了，虚假否定护栏没留。

**修法（推荐）**：新增一条单条不变量（归 P1，进 check_invariants）：
```
INV20  resolved==not_found ⟹ source==clangd ∧ certainty==semantic
                            ∧ blind_spot_affects_result==False
```
**验证**：唯一合法产 not_found 的工厂 clangd_not_found 正是 source=clangd, certainty=semantic,
blind_spot 默认 False —— 新不变量不破坏任何现有工厂/测试。它把 INV12（tree-sitter 专用）
泛化成「只有 clangd 语义无盲区才能断言不存在」，与系统立身之本一致。

**P1 随之改**：在 credibility.py 加 _check_inv20 独立函数 + 两类测试（被拒的三种虚假否定组合、
紧邻合法的 clangd_not_found 不误杀）。design.md §4.2.2 加 INV20。

---

## 项 3【MINOR】coverage 字段在 resolved≠not_found 时未锁中性（change_1 项1 的延伸）

resolved=resolved/unresolved 的结果可携带 negative_scope=current_tu、is_exhaustive=True 过校验，
让 positive 结果夹带负证明语义。建议加：resolved != not_found ⟹ negative_scope == none。
（可并入 INV20 同批，或作为 change_1 项1 一起处理。design call。）

---

## 处理建议
- 项1（BLOCKER）、项2（MAJOR）建议**接受修法**，更新 design.md（经两轮复核定稿为 v1.4.2），P1 随之微调（加 INV20/INV21、
  QR7 注释对齐），重测 + 复核后再 merge P1。
- 项3（MINOR）已加，但经复核【缩范围】：只锁 negative_scope=none；is_exhaustive 仅对 unresolved 强制 False（positive 结果允许 exhaustive=True，保留 P7 穷尽信号）。
- 三项都是 design 层修订；P1 代码改动小（加 INV20 检查 + 测试，QR7 是 P2 的不在此实现）。
- 本提案与 change_1.md 不冲突；change_1 的两项仍按"零改动加注"处理。
