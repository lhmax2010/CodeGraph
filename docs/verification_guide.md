# CodeGraph 团队验证指南 v1.0

> 对象:验证组员(不需要了解开发历史)
> 版本:main@5506c9b(MVP 闭环,design v1.5.0)
> 仓库:https://github.com/lhmax2010/CodeGraph.git
> 目的:在【你自己的机器 + 你自己的项目】上验证 CodeGraph,暴露开发环境没覆盖到的问题。
> 环境越多样,验证越有价值。发现问题按文末模板报告。

---

## 0. CodeGraph 是什么(1 分钟)

本地 C/C++ 代码智能服务:给 LLM/agent 提供五种代码事实查询
(search_symbol / get_definition / find_references / find_callers / find_callees),
每条结果都带**可信度元数据**(credibility)。

**核心卖点不是"查得全",而是"绝不撒谎"**:
- 语义结果(clangd 证实的)和语法候选(tree-sitter 猜的)严格分开,后者永远带
  `consumer_warning=not_evidence`
- 查不到时明说 UNRESOLVED(看不到)——MVP 绝不说 not_found(确认不存在)
- 能力不支持时明说 FAILED——绝不静默返回空结果冒充"没有"

**所以验证的重点是:它有没有在任何情况下撒谎、丢元数据、或静默出错。**

---

## 1. ⚠️ 先读这个:什么是设计行为,不是 BUG(防误报)

下面这些**全部是正确行为**,不要报 bug:

| 现象 | 为什么是设计行为 |
|---|---|
| `find_callees` 在 clangd 18 返回 `FAILED` + note `CALLHIERARCHY_UNSUPPORTED` | clangd 18 没有 outgoingCalls 方法(需要 20+)。诚实报告不支持,不伪造 |
| 所有结果 `is_exhaustive_within_scope = False` | MVP 设计:永不声称穷尽(clangd background-index 无法证明完整性) |
| 查一个不存在的符号返回 `UNRESOLVED` 而不是 `NOT_FOUND` | MVP 的 background-index 无法证明"不存在",只能说"我没看到"。说 not_found 才是 bug |
| `syntactic_candidates` 里的结果带 `consumer_warning="not_evidence"` | 语法候选只是启发,必须带此标记。**没带才是 bug** |
| 无 stamp 的旧索引:`index_health=unknown`,结果范围缩到 `current_tu`(数量大减) | 版本未验证的 cache 不能声明项目级结论。恢复途径:确认来源后 `--stamp-existing-index` 显式追认,或【换一个空目录】从零重建。注意:直接对无 stamp 的非空 cache 重跑建库会被 `index_engine_unverified` 拒绝(fail-closed 守卫,不自动认领来历不明的分片)——这也是设计行为 |
| 用错版本 clangd 打开索引:秒级返回 `UNRESOLVED` + `INDEX_ENGINE_MISMATCH` | 所有权守卫,防跨版本污染。这是保护不是故障 |
| 另一个进程正在建库时查询:`index_engine_build_in_progress` | 建库互斥锁,等建完即可 |
| MCP 工具传了拼错/多余的参数:结构化 `invalid_params` 报错 | 参数白名单,防 agent 拼错参数被静默忽略 |
| 结果里的 file 指向 /usr/include 等系统路径 | 输出路径原样传出是设计(allowlist 只限制输入参数) |
| root 用户跑测试挂 1 个 `..._permission_error_...` | root 无视权限位,该测试必失真。**用普通用户跑** |
| search 返回 `unresolved` + note `tree_sitter_unavailable` | search 依赖 tree-sitter;环境缺 tree-sitter/tree-sitter-c/tree-sitter-cpp 时诚实降级(装齐三个包即恢复,见 §2)。这是诚实降级的活例子 |
| search/definition/references 的 `engine_version=None` | 设计:只有 callers/callees(call graph 类)填 engine_version,其余查询为 None |
| callers 数量随 clangd 版本略有不同 | 已知实证:同一符号在 18/21/22 上 387/386/386(18 多的那条是 clangd 18 的 false positive)。差 1-2 条是版本差异,不是 CodeGraph bug |
| 重跑建库后分片 mtime 全变了 | `build_index` 是每次从零的完整建库(非增量),"幂等"指结果状态一致,不指分片文件不动 |
| 正常查询(verified 同版本)后个别分片 mtime 变化 | clangd 自身可能刷新分片(原子替换),同版本刷新是正常行为,不等于跨版本污染 |
| 断电后索引状态异常 | 协议保证【进程崩溃/SIGKILL】可恢复,不承诺【断电】原子性(设计边界,§6.1 已声明)。断电后重建即可 |

**报 bug 前先对照这张表。** 拿不准就报,但注明"不确定是否设计行为"。

---

## 2. 环境准备

- Linux(开发环境 Ubuntu,其他发行版正是验证价值所在)
- Python ≥ 3.10;**普通用户,不要 root**
- clangd(任何版本;18/21/22 之外的版本也欢迎——版本多样性是验证点)
- 一个真实 C/C++ 项目的 `compile_commands.json`(你自己的项目最好)

```bash
git clone https://github.com/lhmax2010/CodeGraph.git && cd CodeGraph
sudo apt install -y python3-venv          # Ubuntu/Debian 需先装(缺它 venv 会失败)
python3 -m venv .venv && source .venv/bin/activate
pip install pytest pytest-cov tree-sitter tree-sitter-c tree-sitter-cpp
pip install -r requirements-mcp.txt        # mcp==1.28.1,仅 MCP 验证需要
# 若报 PyJWT 冲突:pip install --ignore-installed PyJWT mcp
clangd --version                            # 记下版本,报告时要写
```

---

## 3. L1:单元测试全套(15 分钟,必做)

```bash
PYTHONPATH=.:tools python -m pytest tests/ -q
```

**预期:365 passed**(数字可能随小版本浮动,但必须 0 failed)。
- root 下 1 个 permission 测试失败 → 换普通用户
- 缺 `tree_sitter_cpp` 大片失败 → 装依赖后重跑
- **其他任何失败 → 报告**(带完整输出)

再跑 5 遍看稳定性(并发/时序测试的抖动是有效发现):
```bash
for i in 1 2 3 4 5; do PYTHONPATH=.:tools python -m pytest tests/ -q | tail -1; done
```
**任何一轮出现 failed → 报告**(注明第几轮、哪个测试、机器 CPU 核数)。

---

## 4. L2:用你的项目建库(必做)

```bash
# CDB 已就绪(cmake -DCMAKE_EXPORT_COMPILE_COMMANDS=ON 或 bear 生成):
PYTHONPATH=.:tools python tools/build_index.py \
  --compile-commands-dir /path/to/dir-containing-compile_commands.json \
  --clangd $(which clangd) --jobs 4

# GBS/chroot 的 CDB(路径需重写):
PYTHONPATH=.:tools python tools/build_index.py \
  --input-cdb /path/to/gbs/compile_commands.json \
  --output-dir /path/to/rewritten --buildroot /path/to/buildroot \
  --clangd $(which clangd)
```

**预期**:
- 结束输出 JSON:`build.health_report.health` 为 `complete`(小项目几十秒;TU 数越大越久)
- CDB 目录下生成:
  - `.cache/clangd/index/`:*.idx 分片 + `.codegraph_engine`(内容=你的 clangd 版本,
    如 `clangd 18.1.3`)
  - `.cache/clangd/.codegraph_index.lock`(锁文件,在 clangd/ 下、不在 index/ 下;
    永久存在是设计,不要删)
- **`index/` 下的 `.codegraph_building` 不应残留**(残留=建库没收尾;但若是你 kill 过
  建库进程,残留是正常崩溃痕迹,见 L5-D)

**验证幂等**:同命令再跑一遍 → 仍 complete、不报错。

**该报告的**:health 卡在 incomplete 不收敛;进程 hang;stamp 内容不是你的 clangd 版本;
build 崩溃后重跑无法恢复(这个尤其重要——崩溃恢复是重点设计)。

---

## 5. L3:库 API 五能力(必做,核心)

存为 `verify_api.py`,改前六个变量后跑 `PYTHONPATH=.:tools python verify_api.py`:

```python
from codegraph.api import CodeGraph, BuildConfig
from codegraph.types import Pos

CDB_DIR    = "/path/to/your/cdb-dir"          # L2 建库的目录
CLANGD     = "/usr/bin/clangd"                 # 你的 clangd
SYMBOL     = "your_function_name"              # 你项目里一个【跨文件被调用】的函数
QUERY_FILE = "/abs/path/to/a/caller.c"        # 一个【调用】该函数的文件(绝对路径)
QUERY_POS  = Pos(42, 10)                       # 该文件里调用处、光标落在函数名上(行,列 0-based!)
EXPECTED_DEF_FILE = "lib.c"                    # 定义所在文件名(用于人工核对结果)

# 注意:查询位置用【调用点】,不是定义点——从定义点查 definition 会命中头文件声明
# 并降级 UNRESOLVED(clangd 语义),那不是 bug,但不是我们要验证的路径。

cfg = BuildConfig(
    "verify-local",                           # build_config_id
    CDB_DIR,                                  # compile_commands_dir
    clangd_path=CLANGD,
    background_index=True,
    index_ready_probe_symbol=SYMBOL,
    index_ready_probe_path_suffix=EXPECTED_DEF_FILE,
)
cg = CodeGraph(cfg)

def show(name, r):
    print(f"\n== {name}: status={r.status.value} health={r.index_health}"
          f" engine_version={r.engine_version}")
    print(f"   semantic={len(r.semantic_results)} candidates={len(r.syntactic_candidates)}"
          f" total_hits={r.total_hits}")
    for n in r.notes: print(f"   note: {n.code.value}: {n.detail[:80]}")
    for c in r.syntactic_candidates[:3]:
        assert c.consumer_warning == "not_evidence", "BUG! 候选缺 not_evidence 标记"
    for s in r.semantic_results[:2]:
        cr = s.credibility
        print(f"   sample: {s.data}")   # dataclass 全字段,直接人工核对
        print(f"           src={cr.source.value} cert={cr.certainty.value}"
              f" scope={cr.coverage.index_scope.value}"
              f" exhaustive={cr.coverage.is_exhaustive_within_scope}")

show("search",     cg.search_symbol(SYMBOL))
show("definition", cg.get_definition(SYMBOL, QUERY_FILE, QUERY_POS))
show("references", cg.find_references(SYMBOL, QUERY_FILE, QUERY_POS, limit=1000))
show("callers",    cg.find_callers(SYMBOL, QUERY_FILE, QUERY_POS, limit=1000))
show("callees",    cg.find_callees(SYMBOL, QUERY_FILE, QUERY_POS, limit=1000))
show("不存在的符号", cg.search_symbol("this_symbol_does_not_exist_xyz123"))
```

**逐项核对(核对属性,别核对具体数字——数字因项目而异)**:

| 查询 | 必须成立的属性 |
|---|---|
| search | status=ok;结果里有你的符号 |
| definition | ok;file/pos 指向真实定义(**打开文件人工核对!**) |
| references | ok;semantic 数 ≥ 你已知的引用数的大部分;**semantic 每条 certainty=semantic、source=clangd**;candidates(如有)全带 not_evidence;**is_exhaustive 恒 False** |
| callers | ok;**抽 3 条人工核对**:该行真的在调用 SYMBOL(不是注释/字符串/同名局部变量)|
| callees | clangd ≥20:ok+edges;clangd 18/19:**FAILED+CALLHIERARCHY_UNSUPPORTED(正确!)**;engine_version=你的 clangd 版本 |
| 不存在符号 | **status=unresolved(绝不能是 not_found)** |

**最有价值的验证:人工抽查**。挑 5 条 semantic 结果,逐条打开源码确认真实。
**任何一条 semantic 结果是错的(指向不存在的调用/引用)→ 最高优先级报告**——
semantic 撒谎直接打击立身之本。同理:**你知道存在的引用没被列出且没有任何降级提示**(health=complete、无 notes、却漏了)→ 报告。

---

## 6. L4:MCP server(必做)

写 `mcp-config.json`(格式见 docs/mcp_server.md,把 L2/L3 的路径填进去;
`allowed_read_roots` = 你的源码根目录列表)。

```bash
python -m codegraph.mcp_server --config mcp-config.json
# 应静默等待 stdio(不崩溃、不在 stdout 打印任何非协议内容)。Ctrl-C 退出。
```

用 MCP client(Claude Desktop/Cline/任何 MCP 客户端,或 SDK 脚本)连上后验证:
1. `list_tools` → **恰好 5 个**(search/definition/references/callers/callees),
   无 impact;每个描述含 not_evidence 提示语;**inputSchema 里没有 build_config_id**
2. 五工具各调一次 → 结果和 L3 库 API 一致,credibility/notes/engine_version 字段完整
3. **门禁攻击(重点)**——每条都应返回结构化 `invalid_params` 且不执行查询:
   - `search(symbol="x", unexpected_field=1)`(未知参数)
   - `search(symbol="x", build_config_id="hack")`(伪造注入)
   - `search()`(缺必填)
   - `references(..., limit=99999)` / `limit="5"` / `pos={"line":-1,...}`
   - `definition(file="/etc/passwd", ...)`(allowlist 外)
4. 报错格式必须是 `{"error":{"code":"invalid_params","field":...,"detail":...}}`
   ——**如果是裸 Python traceback 或 Pydantic 原始报错 → 报告**

---

## 7. L5:守卫场景(强烈建议,15 分钟)

CodeGraph 的 cache 所有权守卫经过六轮对抗加固。在你的环境复验核心场景:

```bash
IDX=/path/to/cdb-dir/.cache/clangd/index

# A. 错版本拦截(有第二个 clangd 版本才能做)
PYTHONPATH=.:tools python tools/build_index.py --compile-commands-dir <CDB_DIR> \
  --clangd /path/to/other-clangd --inspect-only
# 预期:秒级返回 index_engine_mismatch,分片文件 mtime/数量完全不变

# 备份到 mini 项目自己目录下,避免 /tmp 撞车;做完 B/C 务必恢复(可先 trap):
BAK=$IDX/../stamp.bak; trap 'test -f $BAK && cp $BAK $IDX/.codegraph_engine' EXIT

# B. 无 stamp 降级
cp $IDX/.codegraph_engine $BAK && rm $IDX/.codegraph_engine
#   → 跑 L3 references:health=unknown、结果缩到 current_tu(这是保护,见 §1)
cp $BAK $IDX/.codegraph_engine             # 恢复后 → 恢复 complete

# C. 损坏 stamp(必须拒绝,不能当"缺失"处理)
echo "garbage not a version" > $IDX/.codegraph_engine
#   → 查询:UNRESOLVED + stamp invalid 类信息;绝不能正常 complete
cp $BAK $IDX/.codegraph_engine             # 恢复

# D. 建库中 kill -9(崩溃恢复,重点;命令可直接复制,CDB_DIR/CLANGD 换成你的)
PYTHONPATH=.:tools python tools/build_index.py \
  --compile-commands-dir $CDB_DIR --clangd $CLANGD --jobs 4 &
BPID=$!; sleep 1                            # 等它进入建库(dirty marker 已写)
test -f $IDX/.codegraph_building && echo "dirty in place"
kill -9 $BPID; wait $BPID 2>/dev/null
ls $IDX/.codegraph_building                 # 残留 = 正常崩溃痕迹
PYTHONPATH=.:tools python tools/build_index.py \
  --compile-commands-dir $CDB_DIR --clangd $CLANGD --inspect-only
#   → 此时绝不能 health=complete(报 complete = 严重 BUG,立即报告)
PYTHONPATH=.:tools python tools/build_index.py \
  --compile-commands-dir $CDB_DIR --clangd $CLANGD --jobs 4
#   → 同一 clangd 重跑:自动接管、清旧、重建成功、恢复 complete

# E. 并发双建库(两个终端,或如下后台并发)
PYTHONPATH=.:tools python tools/build_index.py \
  --compile-commands-dir $CDB_DIR --clangd $CLANGD --jobs 4 &
PYTHONPATH=.:tools python tools/build_index.py \
  --compile-commands-dir $CDB_DIR --clangd $CLANGD --jobs 4
#   → 一个建成,另一个快速返回 index_engine_build_in_progress;绝不能两个都写
```

**A/C/D 任何一个没拦住(错版本建了库/损坏 stamp 当没事/崩溃残留被判 complete)→ 最高优先级报告。**

---

## 8. L6:可选进阶

- **多版本**:有多个 clangd 的,给每个版本独立 CDB 目录分别建库,验证:
  references 语义结果跨版本一致(总数应相同或极接近);callees 在 20+ 点亮;
  engine_version 如实标注;**互开对方 cache 全被 mismatch 拦**
- **大库**:CDB 越大越好(开发环境最大 1304 TU)。关注:建库时长、内存、
  health 是否收敛、`--stable-rounds` 调参
- **资源高压**:内存紧张/高负载下查询——预期是**诚实降级**
  (UNRESOLVED/超时),**绝不能返回残缺结果冒充 ok**、绝不能污染 cache
- **C++ 重载/模板/宏**:重载函数的 references 是否只命中正确重载;
  模板/宏场景 semantic 有没有撒谎(clangd 上游限制也值得记录)

---

## 9. 问题报告模板(发给 PM)

```
【CodeGraph 验证问题】
标题:一句话(如"references 漏报无任何降级提示")
严重度自评:S1 semantic 结果撒谎/守卫被绕过/cache 被污染
          S2 崩溃、hang、数据错误  S3 体验/文档/易用性
环境:发行版+内核 / Python 版本 / clangd 版本(clangd --version 全文)/
     普通用户还是 root / CPU 核数 / 项目规模(TU 数)
复现步骤:命令逐条(能复制粘贴执行)
预期:  (对照本指南哪一节)
实际:  (完整输出/截图;查询问题附 status/health/notes/engine_version 全字段)
已对照 §1 设计行为表:是/不确定
附件:build_index 输出 JSON、verify_api.py 输出、失败测试完整 log
```

**S1 立即报;S2 当天;S3 攒批。**

---

## 10. 验证覆盖清单(组长汇总用)

| 层 | 内容 | 必做 | 人 | 结果 |
|---|---|---|---|---|
| L1 | 全套测试 ×5 轮稳定 | ✅ | | |
| L2 | 自己项目建库 + 幂等 | ✅ | | |
| L3 | 五能力 + 人工抽查 semantic | ✅ | | |
| L4 | MCP 五工具 + 门禁攻击 | ✅ | | |
| L5 | 守卫 A-E 场景 | 建议 | | |
| L6 | 多版本/大库/高压/C++ 深水区 | 可选 | | |

> 指南对应 main@5506c9b。验证中 main 若有修复更新,PM 会通知重拉。
