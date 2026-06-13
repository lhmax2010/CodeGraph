# CodeGraph 复用资产包（验证过的 PoC 产物）

这是 design.md §2.3 列为"复用资产，不重写"的五个文件，均已实测验证：
- credibility 28 测试通过、cdb_rewriter 19 测试通过 = 共 47 测试。

## 文件与放置位置（按 design.md §9 目录）
| 文件 | 放到仓库的 | 说明 |
|---|---|---|
| codegraph/credibility.py | codegraph/ | 元数据 + 12 不变量(INV1-12)。P1 在此扩展 INV13-19 |
| codegraph/factories.py | codegraph/ | 合法 credibility 工厂。P1 扩展 make_error_credibility |
| tools/cdb_rewriter.py | tools/ | CDB 改写器（P5 复用，勿重写） |
| tools/verify_clangd.py | tools/ | LSP 客户端 + 语义验证（P3/P5 复用，勿重写） |
| tests/test_credibility.py | tests/ | 28 测试，import `from codegraph.credibility` |
| tests/test_cdb_rewriter.py | tests/ | 19 测试，import `from cdb_rewriter`（见下方 import 注意） |

## import 路径注意
两个测试 import 方式不同：
- test_credibility.py → `from codegraph.credibility import ...`（包内导入，仓库根跑 pytest 即可）
- test_cdb_rewriter.py → `from cdb_rewriter import ...`（平铺导入，假设 cdb_rewriter 在 sys.path）

cdb_rewriter.py 放到 tools/ 后，test_cdb_rewriter 默认找不到它。两个解法二选一：
- A（推荐）：在 tests/ 或仓库根加 conftest.py，把 tools/ 加入 sys.path：
    import sys, os; sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
- B：把 test_cdb_rewriter.py 的 import 改成 `from tools.cdb_rewriter import ...` 并给 tools/ 加 __init__.py

验证命令（放好后跑，应 47 passed）：
    PYTHONPATH=.:tools python3 -m pytest tests/ -q

## P1 红线
P1 在 credibility.py / factories.py 上扩展，扩展后这 28 个旧测试必须仍全过（回归基线）。
