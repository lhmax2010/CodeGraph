# Stage 09 - MCP 薄封装 / Result

## 最终状态
Review MAJOR 已修，待四路聚焦复核。实现、确定性 gate 与真实 SDK stdio client 真机复攻均完成，
尚未 merge。

## 测试情况
- Baseline：`271 passed in 4.63s`。
- 初版全套：`324 passed in 6.03s`；总 branch coverage 93%。
- Review 修复后最终全套：`PYTHONPATH=.:tools .venv/bin/python -m pytest tests/ -q --cov=codegraph
  --cov-branch` -> `354 passed in 6.32s`；总 branch coverage 92%。
- P9 定向：`83 passed`；`codegraph/mcp_server.py` branch coverage 97%。
- 静态 gate：ruff、black --check、mypy、compileall、git diff --check 全绿。
- 补测内容：五种 status、三类结果、嵌套 credibility/候选/notes/engine_version 全字段 JSON
  roundtrip；未知类型 fail-loud；五工具 schema/映射；错型/越界/allowlist/symlink 输入门禁与 API
  零调用；五工具 raw unknown/伪造 build_config_id/missing required；严格启动配置；真实 SDK
  initialize/list/call 与 stdout 协议隔离。

## 真机验收
- 环境：官方 MCP SDK `1.28.1`；系统 clangd `18.1.3`；版本专用 verified cache 为
  `3593` shards、health COMPLETE，复用查询未重建。
- 官方 SDK stdio client 独立启动 server 后完成五工具：
  - search `gst_buffer_ref`：OK/complete，命中 `gstbuffer.c`。
  - definition：OK/complete，跨文件命中 `gstbuffer.c:3014`。
  - references `gst_element_set_state`：OK/complete，`381 semantic + 8 not_evidence = 389`，
    覆盖 62 files。
  - callers：OK/complete，`379 semantic + 8 candidates = 387`，覆盖 62 files，
    `engine_version=clangd 18.1.3`。
  - callees：原样返回 FAILED/unknown、CALLHIERARCHY_UNSUPPORTED、
    `engine_version=clangd 18.1.3`。
- agent 侧逐项校验 QueryResult、QueryMeta、Credibility、Result/Candidate 与 Note 字段集合；text JSON
  与 structuredContent 完全一致。server stderr 为空，工具 schema 无 `build_config_id`。
- cache 前后快照一致：`3593 shards / 39932298 bytes / max mtime 1783649150070320105ns`。
- Review 修复后真实复攻：unknown 与伪造 build_config_id 均在 1ms 内结构化拒绝，missing required
  结构化拒绝；之后五工具结果与 cache 快照均保持上述基线。

## PR 与代码
- PR：N/A（按用户要求只 push，不创建 PR）。
- 分支：`phase/9-mcp-server`。
- Commit：本阶段 Phase 9 实现提交（branch HEAD；merge 收口时回填最终 hash）。

## Review
- Codex：完整 staged diff 自审，无 BLOCKER/MAJOR。
- Kimi：独立生产面审查 `VERDICT: APPROVE`，无 BLOCKER/MAJOR；两条非阻塞 MINOR（内部错误
  fail-loud、serializer 验证性二次 dumps）符合冻结约束，不修改。
- gstack Claude：完整 diff、聚焦生产 diff、只读 Consult 三种调用均以 `aborted_streaming`
  结束且没有最终审查文本，明确不计票；已按三次上限停止。
- 初版四路裁决：三票同意；一票发现 unknown raw argument 被 Pydantic 静默忽略的 MAJOR，实测
  属实并已修复。当前等待各路聚焦确认 pre-Pydantic 门禁闭合、无新绕过。

## 遗留问题 / 风险
- MCP SDK 是 P9 独立可选依赖，固定在 `requirements-mcp.txt`；核心库未引入该依赖。
- 当前只实现 stdio，不存在网络监听面；SSE/HTTP 不在 MVP 范围。
- 合入前需四路聚焦复核本轮门禁修复并全票通过。

## 下一阶段计划
- P9 是 MVP 最后一个 phase；完成后进入 MVP 总体验收/收口。
