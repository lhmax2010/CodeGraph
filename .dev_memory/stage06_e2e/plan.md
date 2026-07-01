# Stage 06 - E2E Search/Definition / Plan

## 目标
交付 `search_symbol` 与 `get_definition` 的首次端到端集成：把 P1 metadata/credibility、P2 routing、P3 clangd adapter、P4 tree-sitter syntax helper、P5 index_health/background-index 串起来，返回经过双校验的 `QueryResult`。

## 风险档
高风险。P6 是首个跨阶段真实集成，风险主要来自组件接缝：clangd 是否消费 P5 全局索引、P4 helper 是否足以支撑要素2、P2 路由契约是否能承接真实 observation、真实 Tizen CDB/索引是否暴露小型测试没有覆盖的问题。

## 范围边界
- 做：`search_symbol`、`get_definition` API/组装层；真实 clangd observation 接 P2 routing；P4 syntax helper 接入；P5 `index_health` 作为输入；开发机小工程端到端测试；真机 ARM/Tizen 查询验收。
- 不做：`find_references`、`find_callers`、`find_callees`（P7/P8）；MCP 封装（P9）；P5 建库流程改造；负证明语义扩展；设计契约变更。
- 若发现 frozen design 矛盾，按 R1 输出 `[DESIGN_ISSUE]` 与 design change 草案，等待 design owner 决策，不自行改 `design.md`。

## 集成问题与决策
1. P6 必须处理 P5 全局索引接入。当前 `ClangdAdapter` 复用 `tools.verify_clangd.LSPClient`，而该客户端默认启动参数含 `--background-index=false`；这意味着当前模式是单 TU/同步可预测模式，不会消费 P5 全局分片。P6 若要验证真实跨文件 `get_definition`，需要在不破坏 P3 小型测试可预测性的前提下，为 P6 API 路径提供可启用 background-index 的 clangd 启动配置。
2. P6 前遗留项采取“先接链路、用真实查询暴露问题，再针对性修”的策略。P3 `diagnostics_wait=0.5s`、P4 候选过度采集、宏体保守近似、真实宏位置粒度都在 P6 真机/端到端测试中观察；只有实际影响 `search_symbol`/`get_definition` DoD 或造成虚假可信/虚假否定时才在 P6 修复，否则继续登记到后续阶段。
3. P6 需要分层验收：开发机小 CDB 用于确定性链路测试；真机 ARM/Tizen + P5 真实索引用于价值验收，确认 `get_definition` 能在真实项目里走全链路并拿到跨文件结果。P6 DoD 没要求重建索引，复用 P5 已验收的健康分片即可；若索引缺失或 clangd 行为异常，停下报告。

## 计划步骤
1. 开 stage：从 `main` 建 `phase/6-e2e-search-def`，记录 baseline `7717257`，确认 baseline `113 passed`。
2. 梳理 P6 API 入口：优先复用现有协议类型、factories、routing，新增最薄的组装层，不改变 P1-P5 契约。
3. 增加 clangd adapter 的 background-index 可配置能力：默认保持 P3 兼容；P6 路径显式启用全局索引或使用可消费 P5 分片的启动方式。
4. 接入 P5 `index_health`：按 build config 定位 CDB/索引，读取 `IndexHealth` 事实，只把三态事实传给 P2，不在 P6/P5 判定 not_found。
5. 接入 P4 `SyntacticProvider`：用于要素2 helper 和按查询类型补候选；不让候选参与证据通道。
6. 写测试：小工程 `search_symbol`/`get_definition` 端到端、background-index 参数行为、tree-sitter helper 可用/不可用降级、真实 P2 routing 接缝、P5 health 三态输入。
7. 真机验收：使用 `/home/linhao/Toolchain/codes/rw_arm/compile_commands.json` 与现有 3593 分片，跑代表性真实查询；记录跨文件 definition、diagnostics_wait 观察、宏相关位置观察。
8. 跑 gate：`.venv` 下 pytest、ruff、black、mypy、coverage；写 result，送多路 review。

## 依赖前置阶段
P1-P5 均已 Merge。P6 依赖 P4 syntax helper 与 P5 已完成的 background-index/index_health。
