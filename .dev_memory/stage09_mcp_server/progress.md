# Stage 09 - MCP 薄封装 / Progress

## 关键决策
- 采用官方 `mcp==1.28.1`，依赖单独固定在 `requirements-mcp.txt`，SDK import 只存在于
  `codegraph/mcp_server.py`；MVP 仅启用 stdio，不实现网络 transport。
  - 原因：保持核心库纯 stdlib，并把 MCP 依赖与运行面限制在最终协议适配层。
- QueryResult 使用单一递归 serializer：dataclass 按 `dataclasses.fields()` 全字段转换，Enum 转
  `.value`，容器递归；未知类型、非字符串 dict key 与非有限浮点直接失败，不 stringify。
  - 原因：字段白名单容易随 schema 演进漏字段；静默 stringify 会掩盖保真错误。
- FastMCP 参数注解使用 `Any + WithJsonSchema`：对 agent 公布精确类型/范围 schema，同时禁止
  Pydantic 在业务门禁前把字符串或整数做隐式 coercion。所有非法输入由统一 validator 产生稳定
  `invalid_params` JSON，验证失败时库 API 零调用。
- FastMCP 默认会给 tool 异常文本增加 SDK 前缀，因此工具边界显式返回 `CallToolResult`：成功和失败
  都同时提供完全相同的 text JSON 与 structuredContent，错误设置 `isError=True`。
- file allowlist 只约束 agent 输入的查询位置；QueryResult 输出路径完全不经过 allowlist，不过滤、
  不改写系统头或 sysroot 路径。
- `build_config_id` 只由 server 启动 JSON 注入并由闭包捕获，五个 MCP 工具 schema 均不暴露该字段。

## 改动摘要
- 新增 stdio MCP server、五工具薄映射、保真 serializer、协议参数门禁、启动 JSON loader 与独立依赖。
- 新增 serializer/工具 schema/门禁/stdout 隔离/真实 SDK client 测试及运行说明；P1-P8 核心模块未改。

## 进度日志
- 2026-07-17：从 `main@fe7a5d8` 创建 `phase/9-mcp-server`；baseline `271 passed in 4.63s`。
- 2026-07-17：项目 `.venv`/系统 Python 无 MCP SDK；内网源隔离安装 `mcp==1.28.1` 成功，
  FastMCP 与官方 stdio client 可用。确认 codegraph 无 stdout print，clangd 通道由 PIPE 隔离。
- 2026-07-17：定向测试增至 47 条；`codegraph/mcp_server.py` 定向 branch coverage 为 99%。
- 2026-07-17：官方 SDK stdio client 真机连接 verified clangd 18 cache，五工具全部通过：search 与
  definition 均命中 `gstbuffer.c`；references 为 `381 semantic + 8 not_evidence = 389/62`；callers
  为 `379 + 8 = 387/62`；callees 原样返回 `FAILED + CALLHIERARCHY_UNSUPPORTED`，engine_version
  为 `clangd 18.1.3`。server stderr 为空，agent 侧每个 payload 均完成全字段结构核对。
- 2026-07-17：真机 cache 前后快照均为 `3593 shards / 39932298 bytes / max mtime
  1783649150070320105ns`，确认复用 verified cache，未重建或改写。
- 2026-07-17：补 FastMCP 分发层错型参数测试与输入 symlink 逃逸测试；P9 定向 `53 passed`，
  `mcp_server.py` 行/分支覆盖均 100%。最终全套 branch coverage gate 为 `324 passed`、总计 93%。
- 2026-07-17：ruff、black --check、mypy（含 mcp/tree-sitter 固定依赖）、compileall、
  git diff --check 全绿；第三方 import 扫描确认只出现在 `mcp_server.py`。
- 2026-07-17：Codex 完整 staged diff 自审无 BLOCKER/MAJOR。Kimi 独立生产面审查给出
  `VERDICT: APPROVE`，无 BLOCKER/MAJOR；两条 MINOR 为内部错误保持 fail-loud 以及 serializer
  validation/response 两次 dumps 的轻微冗余，均符合已确认语义、不改。
- 2026-07-17：gstack Claude 完整 diff、聚焦生产 diff、只读 Consult 三次分别在 273s/200s/205s
  以 `aborted_streaming` 结束，均无最终审查文本，按能力失败不计票；达到三次上限后停止重试。
