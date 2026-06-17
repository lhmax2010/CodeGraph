# Design Change 提案 #4（P2 review 发现的 design 内部矛盾）

> 状态：**已决策并应用（design.md v1.4.4）** —— 项1 采纳方案 A，项2 采纳澄清。
> 来源：Phase 2 最终 review 抓到 §7 P6 与 R-依1 矛盾；Phase 3 后、Phase 4 前决策。
> 决策依据：tree-sitter 内网可用性验证通过（见下）。

---

## 验证前提（决策的支点）
在目标 x86 开发环境实测：tree-sitter 0.25.2 + tree-sitter-c 0.24.2/cpp 0.23.4 直连 pip 可装、
可 import、能解析 C 并正确识别 preproc_def 节点。CodeGraph 跑在 x86 开发机，syntax helper
在此运行，不涉及 ARM 板。**结论：tree-sitter 内网可用。**

---

## 项 1【MAJOR】§7 P6「无 helper 降级」与 R-依1「功能不受损只是少候选」矛盾

**矛盾**：要素2（宏伪位置判定）由 tree-sitter 实现。§7 P6 说无 helper 就降级（P2 已实现），
意味着无 tree-sitter 时所有需要素2 的语义结果降级为候选、出不了 OK；但 R-依1 承诺无 tree-sitter
「功能不受损只是少候选」。二者不可能同真——丢 tree-sitter 不只丢候选，还丢 OK 语义。

**决策：方案 A —— 采纳 §7 P6 行为（已实现、安全），修正 R-依1 等处的过度乐观措辞。**
理由：tree-sitter 内网已验证可得，"硬依赖"不会让 CodeGraph 在实际环境残废；为不会发生的
"装不上"场景写 stdlib 兜底（方案 B）是解决不存在的问题，且 B 的糙启发式本身是 bug 源/维护负担。
保留 B 作为后备：**若 P6 实战发现 tree-sitter 有意外问题，再启 B。**（用户决策："先 A，实战有问题再定"）

**修法（design.md v1.4.4，行为不变只改措辞 + 一处实现约束）**：
- §1.4 [ASSUMPTION]→[VERIFIED]：tree-sitter 内网已验证可得，作要素2 语义依赖；不可得时诚实降级。
- §5.4 / §6 R-依1 / §4.3 IssueCode 表：把"功能不受损只是少候选"改为诚实的两层降级语义
  （失候选 + 要素2 无 helper 致语义降级为候选，clangd 仍工作但不产 OK 语义）。
- §7 P6 行为不动（P2 已正确实现）。不写 stdlib 兜底代码。

---

## 项 2【MINOR】要素2 应按位置判、不按 symbol_kind

**问题**：P2 的保守要素2 修复在 routing.py 引入 symbol_kind==MACRO 短路一律判盲区降级（注：短路在 P2 routing.py:510，非 P3；P3 的 clangd adapter 不产 MACRO，只在 P6 API 传 kind_filter=macro 时触发），导致 get_definition 查宏定义永远 OK 不了。
但宏的**定义位置**（#define 那行）是真实源码，与"位置落在宏展开伪位置"是两回事。

**决策：澄清要素2 判定对象是"位置"，非"符号类型"。**

**修法（design.md v1.4.4）**：§4.4 要素2 加 [change_4 澄清]：syntax helper 按 position 判 preproc
归属，不得用 symbol_kind==MACRO 短路；宏定义位置应可 OK。P4/P6 实现据此（P2 routing.py:510 现有的
symbol_kind==MACRO 短路在 P4 接真实 helper 时移除）。

---

## 处理
- 两项已应用至 design.md v1.4.4，均不改 §4 代码契约（接口/不变量/QR 不动）。
- 项1 是措辞自洽化（行为 P2 已实现）；项2 是要素2 语义澄清 + P4 实现约束。
- 本变更又改了 frozen design，应过一轮 AI review 确认措辞自洽、无新矛盾。
