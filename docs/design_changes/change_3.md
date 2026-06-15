# Design Change 提案 #3（P2 多路 review 发现的设计字段缺口）

> 状态：**已接受并应用（design.md v1.4.3）**——项1 P2 同步删有损转换，P8 实现调用边降级用之；项2 QR7 加 consumer_warning 校验
> 来源：Phase 2 收口四路 review，P2 真实消费暴露两处冻结设计的字段/校验缺口。
> 性质：非 P2 实现错误（P2 在现有契约约束下已做了能做的）；是 design.md 的类型/校验
>       覆盖不全，被 P2 的真实使用暴露。
> 与 P2 merge 的关系：均不阻塞 P2 merge（P2 的 syntax-helper bug 另行修复后即可 merge）；
>       项1 必须在 P8（callers/callees）前修，项2 可随时加固。

---

## 项 1【MAJOR · P8 前必修】CandidateData 缺 CallEdgeResult，调用边降级有损

**现状**：design.md §4.1.2 `CandidateData = LocationResult | ReferenceResult`（types.py:103）。
不含 CallEdgeResult。

**问题**：§4.4 + INV5 要求受盲区/歧义影响的结果降级入 syntactic_candidates。但 find_callers/
find_callees 的结果是 CallEdgeResult，而 Candidate.data 装不下它。P2 只能有损转换
（routing.py: `ReferenceResult(data.call_site, data.from_symbol.file, "reference")`）——
丢掉 to_symbol（被调方）、调用方向，而这正是调用边的全部 payload。

**触发场景**：find_callers/find_callees（P8）的任一调用边因盲区/歧义降级时。P2 不触发
（P2 用桩、不实现真实 callHierarchy），但 P8 实现后必然触发。

**修法（推荐）**：CandidateData 增加 CallEdgeResult：
```
原：CandidateData = LocationResult | ReferenceResult
改：CandidateData = LocationResult | ReferenceResult | CallEdgeResult
```
QR7/容器校验逻辑不受影响（只校验 credibility，不校验 data 类型）。P2 的 _candidate_data
有损转换可删除，直接保留 CallEdgeResult。

**影响**：types.py 一行；P2 的 _candidate_data 简化（移除有损分支）；P8 实现时调用边
可无损降级入候选。

---

## 项 2【MINOR · 可随时加固】consumer_warning 未在容器校验强制

**现状**：Candidate.consumer_warning 是 `Literal["not_evidence"]`（types.py），但 Literal
是静态标注，运行时不强制；Candidate 是可变 dataclass。QR7 只校验 candidate 的 credibility
三项（resolved/relation/certainty），不查 consumer_warning。

**问题**：实测把候选 consumer_warning 改成 "evidence" 后 validate_query_result 仍接受。
即"候选不得自称证据"这道护栏在运行时没有被容器校验兜住——只靠路由自己填对。

**修法（推荐）**：QR7 增加一条 `∀c ∈ syntactic_candidates: c.consumer_warning == "not_evidence"`，
或单列 QR10。design.md §4.1.4 QR7 + routing.py check_query_result_invariants 同步。

**影响**：design.md §4.1.4 加一句；routing.py QR7 循环加一个 assert；加一个测试
（候选 consumer_warning≠not_evidence 被拒）。

---

## 处理建议
- 项1：接受修法，但**可在 P8 启动前再改 design**（P2 不触发）；现在登记，P8 前执行。
  或并入本轮一起改（一行，风险极低），由 design owner 定。
- 项2：接受修法，可并入本轮或下次加固批次。
- 两项都不阻塞 P2 merge。P2 自身的 syntax-helper 乐观误升 bug 是实现问题，另行修复后 merge。
