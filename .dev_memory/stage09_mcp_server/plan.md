# Stage 09 - MCP 薄封装 / Plan

## 目标
把 P6-P8 已 Merge 的五个库 API 以 stdio MCP server 暴露给本地 agent，同时完整保留
`QueryResult` 的全部诚实性元数据；MVP 不注册 `impact`，不引入任何查询、过滤、降级或可信度逻辑。

## 风险档
- 高风险：实现体量预计不大，但这是 agent-facing 协议与信任边界。字段丢失、输入绕过或 stdout
  污染会让前八个阶段的诚实性约束在最终出口失效。实现后需异构多路 Review + 真实 stdio MCP
  client 真机验收。

## 基线与环境探测
- Git baseline：`main@fe7a5d8`；分支：`phase/9-mcp-server`。
- Baseline：`PYTHONPATH=.:tools .venv/bin/python -m pytest tests/ -q` -> `271 passed in 4.63s`。
- 项目 `.venv` 与系统 Python 当前均未安装 `mcp`；内网源可取官方 `mcp==1.28.1`，隔离环境已
  验证 `FastMCP`、`ClientSession` 与 stdio client 可 import。
- stdout 探测：`codegraph/` 无 `print`；复用 LSP client 将 clangd stdout/stderr 接到 PIPE，verbose
  诊断只写 stderr；MCP SDK stdio transport 独占 stdout 写 JSON-RPC。实现仍需 subprocess 测试锁定。

## 范围边界
### 做
- 新增 `codegraph/mcp_server.py`；MCP SDK import 仅出现在该模块，核心库保持现状。
- 注册 `search` / `definition` / `references` / `callers` / `callees`，一对一调用现有库 API。
- server 启动配置注入 `BuildConfig`/`build_config_id`；工具 schema 不出现 `build_config_id`。
- 递归、无损地把 dataclass / str Enum / tuple / list / dict 转成 JSON-safe 数据，保留全部字段。
- stdio-only CLI、协议参数白名单、结构化 tool error、stderr 日志。
- 固定 MCP 运行依赖与安装说明；确定性单测、真实 SDK stdio client 集成测试、rw_arm 真机验收。

### 不做
- 不在 MCP 层过滤、分页重算、候选简化、可信度判断、状态改写或能力兜底。
- 不注册 `impact`；不实现 SSE/HTTP/网络监听；不改 P1-P8 核心契约或路由。
- 不因 clangd 版本加工结果；FAILED/IssueCode/engine_version 原样序列化。

## 实现方案（待 restate 确认）
1. **SDK 与启动**
   - 使用官方 `mcp==1.28.1`，建议新增独立 `requirements-mcp.txt` 固定版本；不把 SDK import
     扩散到 `codegraph/__init__.py` 或任何核心模块。
   - `create_mcp_server(config, allowed_read_roots=...)` 供库/测试调用；`python -m codegraph.mcp_server
     --config <json>` 仅运行 stdio。启动 JSON 含完整 BuildConfig 与 MCP 只读路径 allowlist，工具参数
     不含 `build_config_id`。
2. **五工具直映射**
   - 闭包捕获 server config，直接调用 `codegraph.api` 同名能力并注入固定 build_config_id。
   - 五个 tool description 均包含冻结原文：`syntactic_candidates 仅作启发，带
     consumer_warning=not_evidence，不得作为确定性证据使用。`
3. **序列化保真**
   - 单一递归 serializer：dataclass 按 `dataclasses.fields()` 输出每个声明字段；Enum 输出 `.value`；
     tuple/list 输出 JSON array；dict 递归；JSON 原语原样。遇到不支持值 fail-loud，不 stringify。
   - 覆盖 query、status、status_credibility 全字段、semantic_results 每条 data/credibility、
     syntactic_candidates 的 data/credibility/relevance_score/consumer_warning、index_health、
     total_hits、notes code/detail、engine_version。
   - 测试构造各 QueryStatus、Location/Reference/CallEdge、semantic/candidate/notes/engine_version，做
     JSON dump/load + 测试侧反序列化，逐字段比较；consumer_hint 单独比较，避免其 compare=False 漏检。
4. **协议输入门禁**
   - 推荐阈值：symbol 1..512 字符且无 NUL/CR/LF；file 1..4096 字符、realpath 位于启动 allowlist；
     pos 为恰含 line/character 的对象，两者为非 bool int 且 0..2^31-1；limit 1..1000；offset
     0..1,000,000；kind_filter 为 None 或 function/variable/type/macro（大小写不敏感）；fallback
     必须为 bool。
   - 任一非法参数抛 SDK ToolError，内容为稳定 JSON：`code=invalid_params` + field/detail；验证失败
     前不调用库 API。真实文件行/列范围继续由现有库 API 判断，不在 MCP 重复业务逻辑。
5. **stdio 隔离**
   - server 自身日志显式走 stderr；不启用网络 transport。
   - subprocess + 官方 `mcp.client.stdio` 完成 initialize/list_tools/invalid call，确认协议可解析、
     stderr 与 MCP 消息分离、五工具存在且 impact/build_config_id 不在 schema。
6. **真机 DoD**
   - 复用 verified committed rw_arm cache，不重建；真实 MCP client 依次调用 search、definition、
     references、callers、callees。
   - 验证 gst_buffer_ref、gst_element_set_state 389/62、callers 387、clangd 18 callees FAILED +
     CALLHIERARCHY_UNSUPPORTED；逐项核对 credibility/not_evidence/engine_version 完整保真。

## 计划步骤
1. 用户确认高风险档、SDK/启动配置、校验阈值与序列化方案。
2. 固定 MCP 可选依赖，新增 server/serializer/validator 与 stdio CLI。
3. 补序列化保真、参数门禁、工具 schema、stdout 隔离和薄封装调用测试。
4. 跑 pytest/coverage、ruff、black、mypy、compileall、diff-check。
5. 用真实 SDK client + rw_arm verified cache 完成五工具真机验收。
6. 异构多路 Review；按 review 结论修复、复验、push，不创建 PR。

## 依赖前置阶段
- P6 search/definition、P7 references、P8 callers/callees、change_6 多版本 support：均已 Merge。
