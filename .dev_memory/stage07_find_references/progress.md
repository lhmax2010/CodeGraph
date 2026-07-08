# Stage 07 - find_references / Progress
> 开发过程持续追加，记录思考与决策，而非仅结果。

## 关键决策
- 决策：P7 复用 P6 background-index ready/prewarm/sentinel 骨架，不新建 LSP/prewarm 路径。
  - 原因：P6 已经为 search/definition 修过多层 ready 与虚假否定问题；P7 的风险是把同一套可靠消费方式扩到 references。
  - 排除的方案：重新封装 clangd references 或用 `verify_clangd.py` 单独跑查询；这会绕开 P6 安全逻辑。
- 决策：P7 默认高风险，需三路 review。
  - 原因：核心验收是 389 refs/62 files，且涉及 coverage/total_hits/空结果诚实性。
  - 排除的方案：按普通 API 增量处理；风险低估会重复 P6 的虚假否定问题。

## 改动摘要
- 文件/模块：
  - 待实现：`codegraph/api.py` 增加 `find_references`。
  - 待评估：`codegraph/engines/protocol.py` / `clangd_adapter.py` 如何保留 references raw total。
  - 待补测：`tests/test_api.py`、`tests/test_clangd_adapter.py`、必要时 `tests/test_phase2_routing.py`。

## 进度日志
- 2026-07-08 开 P7 分支 `phase/7-find-references`，baseline commit `1ce3499`。
- 2026-07-08 baseline：`PYTHONPATH=.:tools .venv/bin/python -m pytest tests/ -q` -> `142 passed in 2.06s`。
- 2026-07-08 真机探测：`rw_arm` 现有 3593 个 `.idx`、47M；CDB 1304 entries。直接 adapter 在 background-index + 正确 warm 后，`gst_element_set_state` 于 `.c` 定义点、`.h` 声明点、真实调用点均复现 `389 refs / 62 files`。一次不充分 warm/query 的探测只返回 `2 refs / 1 file`，说明 P7 必须复用并固定 P6 ready/warm 机制。

