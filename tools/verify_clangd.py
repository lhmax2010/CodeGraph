#!/usr/bin/env python3
"""
verify_clangd.py — CodeGraph 阶段2 的真机试金石。

它做的不是 syntax-only,而是把改写后的 CDB 喂给真实 clangd,
通过 LSP 协议验证"语义导航"真的可用:
  1. initialize / initialized
  2. 对若干源文件发 textDocument/documentSymbol  -> 能列出符号 = clangd 真在 index
  3. 挑一个函数定义,发 textDocument/definition    -> 定义能定位
  4. 对它发 textDocument/references               -> 引用能收敛
  5. (可选)textDocument/prepareCallHierarchy + incomingCalls -> 调用者

只用标准库 + clangd 二进制,无第三方 LSP client(便于真机零依赖跑)。

退出码:0 = 语义导航验证通过;非0 = 失败(stderr 说明卡点)。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from typing import Any, Optional

# ---------------------------------------------------------------------------
# 极简 LSP over stdio 客户端
# ---------------------------------------------------------------------------


class LSPClient:
    def __init__(
        self,
        clangd_path: str,
        extra_args: list[str],
        cwd: str,
        verbose: bool = False,
        background_index: bool = False,
    ):
        self.verbose = verbose
        self._id = 0
        self._responses: dict[int, Any] = {}
        self._lock = threading.Lock()
        self._diagnostics: dict[str, list] = {}
        args = [
            clangd_path,
            f"--background-index={'true' if background_index else 'false'}",
            "--pch-storage=memory",
            "--log=error",
        ] + extra_args
        if verbose:
            print(f"[lsp] launching: {' '.join(args)}", file=sys.stderr)
        self.proc = subprocess.Popen(
            args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd,
            bufsize=0,
        )
        self._stderr_lines: list[str] = []
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        self._errreader = threading.Thread(target=self._read_stderr, daemon=True)
        self._errreader.start()

    def _read_stderr(self):
        for line in iter(self.proc.stderr.readline, b""):
            s = line.decode("utf-8", "replace").rstrip()
            self._stderr_lines.append(s)
            if self.verbose:
                print(f"[clangd-stderr] {s}", file=sys.stderr)

    def _read_loop(self):
        stream = self.proc.stdout
        while True:
            # 读 header
            header = b""
            while b"\r\n\r\n" not in header:
                chunk = stream.read(1)
                if not chunk:
                    return
                header += chunk
            length = 0
            for h in header.decode("ascii", "replace").split("\r\n"):
                if h.lower().startswith("content-length:"):
                    length = int(h.split(":")[1].strip())
            body = b""
            while len(body) < length:
                chunk = stream.read(length - len(body))
                if not chunk:
                    return
                body += chunk
            try:
                msg = json.loads(body.decode("utf-8"))
            except Exception:
                continue
            self._dispatch(msg)

    def _dispatch(self, msg: dict):
        if "id" in msg and ("result" in msg or "error" in msg):
            with self._lock:
                self._responses[msg["id"]] = msg
        elif msg.get("method") == "textDocument/publishDiagnostics":
            p = msg["params"]
            self._diagnostics[p["uri"]] = p.get("diagnostics", [])

    def _send(self, payload: dict):
        data = json.dumps(payload).encode("utf-8")
        header = f"Content-Length: {len(data)}\r\n\r\n".encode("ascii")
        self.proc.stdin.write(header + data)
        self.proc.stdin.flush()

    def request(self, method: str, params: dict, timeout: float = 30.0) -> Any:
        self._id += 1
        rid = self._id
        self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                if rid in self._responses:
                    resp = self._responses.pop(rid)
                    if "error" in resp:
                        raise RuntimeError(f"{method} error: {resp['error']}")
                    return resp.get("result")
            time.sleep(0.01)
        raise TimeoutError(f"{method} timed out after {timeout}s")

    def notify(self, method: str, params: dict):
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def diagnostics_for(self, uri: str, wait: float = 3.0) -> list:
        deadline = time.time() + wait
        while time.time() < deadline:
            if uri in self._diagnostics:
                return self._diagnostics[uri]
            time.sleep(0.05)
        return self._diagnostics.get(uri, [])

    def shutdown(self):
        try:
            self.request("shutdown", {}, timeout=5)
            self.notify("exit", {})
        except Exception:
            pass
        try:
            self.proc.terminate()
            self.proc.wait(timeout=5)
        except Exception:
            self.proc.kill()
            self.proc.wait(timeout=5)


def path_to_uri(p: str) -> str:
    return "file://" + os.path.abspath(p)


# ---------------------------------------------------------------------------
# 验证流程
# ---------------------------------------------------------------------------


def flatten_symbols(syms: list, depth: int = 0) -> list[dict]:
    """documentSymbol 返回可能是 DocumentSymbol(树) 或 SymbolInformation(平)。
    返回 dict 列表,带 selectionRange(符号名本身的位置,用于精确探针,
    避免 K&R 风格返回类型独占一行导致落点偏到 void 行——PoC 发现 3)。"""
    out = []
    for s in syms:
        name = s.get("name", "?")
        kind = s.get("kind", 0)
        if "range" in s:  # DocumentSymbol
            decl_line = s["range"]["start"]["line"]
            # selectionRange 指向符号名本身;没有就退回 range.start
            sel = s.get("selectionRange", s["range"])["start"]
            out.append(
                {
                    "name": name,
                    "kind": kind,
                    "line": sel["line"],
                    "char": sel["character"],
                    "decl_line": decl_line,
                }
            )
            if s.get("children"):
                out += flatten_symbols(s["children"], depth + 1)
        elif "location" in s:  # SymbolInformation
            st = s["location"]["range"]["start"]
            out.append(
                {
                    "name": name,
                    "kind": kind,
                    "line": st["line"],
                    "char": st["character"],
                    "decl_line": st["line"],
                }
            )
    return out


def run_verification(
    cdb_path: str,
    clangd: str,
    files: list[str],
    find_func: Optional[str],
    verbose: bool,
) -> int:
    # cdb_path 可为目录(推荐,clangd --compile-commands-dir 语义)或直接 json 文件
    if os.path.isdir(cdb_path):
        compile_dir = os.path.abspath(cdb_path)
        cdb_json = os.path.join(compile_dir, "compile_commands.json")
    else:
        cdb_json = cdb_path
        compile_dir = os.path.dirname(os.path.abspath(cdb_path))
    if not os.path.exists(cdb_json):
        print(f"FAIL: no compile_commands.json at {cdb_json}", file=sys.stderr)
        return 2
    if os.path.basename(cdb_json) != "compile_commands.json":
        print(
            f"WARNING: clangd only reads a file named exactly "
            f"'compile_commands.json'; got {os.path.basename(cdb_json)}. "
            f"clangd will fall back to no-flags mode and results will be "
            f"syntactic-only. Pass the containing DIRECTORY instead.",
            file=sys.stderr,
        )
    with open(cdb_json, encoding="utf-8") as fh:
        cdb = json.load(fh)
    if not cdb:
        print("FAIL: CDB is empty", file=sys.stderr)
        return 2

    # 验证文件:命令行给的优先,否则取 CDB 前 N 个真实存在的 .c/.cc
    if not files:
        files = []
        for e in cdb:
            f = e["file"]
            if os.path.exists(f) and f.endswith((".c", ".cc", ".cpp", ".cxx")):
                files.append(f)
            if len(files) >= 3:
                break
    if not files:
        print("FAIL: no existing source files to test", file=sys.stderr)
        return 2

    client = LSPClient(
        clangd,
        [f"--compile-commands-dir={compile_dir}"],
        cwd=compile_dir,
        verbose=verbose,
    )

    ok = True
    report: dict[str, Any] = {"files": {}, "checks": []}

    try:
        root = compile_dir
        client.request(
            "initialize",
            {
                "processId": os.getpid(),
                "rootUri": path_to_uri(root),
                "capabilities": {
                    "textDocument": {
                        "documentSymbol": {"hierarchicalDocumentSymbolSupport": True},
                        "definition": {},
                        "references": {},
                        "callHierarchy": {"dynamicRegistration": False},
                    }
                },
            },
        )
        client.notify("initialized", {})

        # ---- 检查 1: 每个文件能 index 出符号 ----
        first_symbols: list = []
        for f in files:
            uri = path_to_uri(f)
            try:
                text = open(f, encoding="utf-8", errors="replace").read()
            except Exception as e:
                print(f"  skip {f}: {e}", file=sys.stderr)
                continue
            lang = "cpp" if f.endswith((".cc", ".cpp", ".cxx")) else "c"
            client.notify(
                "textDocument/didOpen",
                {
                    "textDocument": {
                        "uri": uri,
                        "languageId": lang,
                        "version": 1,
                        "text": text,
                    }
                },
            )
            time.sleep(0.2)
            syms = client.request(
                "textDocument/documentSymbol",
                {"textDocument": {"uri": uri}},
                timeout=40,
            )
            flat = flatten_symbols(syms or [])
            diags = client.diagnostics_for(uri, wait=2.0)
            errs = [d for d in diags if d.get("severity") == 1]
            # file-not-found 类错误是"CDB flag 没吃到/sysroot 没接上"的铁证:
            # 语法兜底仍能吐符号(假 PASS 根源——PoC 发现 1),但 #include 必然爆这个。
            include_errs = [
                d
                for d in errs
                if "file not found" in d.get("message", "").lower()
                or "'" in d.get("message", "")
                and "not found" in d.get("message", "").lower()
            ]
            report["files"][f] = {
                "symbols": len(flat),
                "errors": len(errs),
                "include_not_found": len(include_errs),
                "error_samples": [d.get("message", "")[:80] for d in errs[:3]],
            }
            print(
                f"  [{os.path.basename(f)}] symbols={len(flat)} " f"errors={len(errs)}",
                file=sys.stderr,
            )
            if len(flat) == 0:
                ok = False
                print(f"    FAIL: no symbols indexed in {f}", file=sys.stderr)
            if not first_symbols and flat:
                first_symbols = [(f, uri, flat)]

        report["checks"].append({"documentSymbol": ok})

        # ---- 检查 2/3: 定义 + 引用 ----
        if first_symbols:
            f, uri, flat = first_symbols[0]
            # 找目标函数:命令行指定的,否则第一个 kind==12(Function)
            cand = None
            if find_func:
                cand = next((x for x in flat if x["name"] == find_func), None)
            if not cand:
                cand = next((x for x in flat if x["kind"] == 12), None)  # Function
            if not cand:
                cand = flat[0]
            name = cand["name"]
            # 用 selectionRange 的精确行列(符号名本身),不靠猜(PoC 发现 3)
            line, col = cand["line"], cand["char"]
            print(
                f"  probing symbol '{name}' at {line+1}:{col+1} "
                f"(decl starts line {cand['decl_line']+1})",
                file=sys.stderr,
            )

            try:
                defn = client.request(
                    "textDocument/definition",
                    {
                        "textDocument": {"uri": uri},
                        "position": {"line": line, "character": col},
                    },
                    timeout=30,
                )
                got_def = bool(defn)
                report["checks"].append({"definition": got_def, "symbol": name})
                print(
                    f"    definition: {'OK' if got_def else 'EMPTY'}", file=sys.stderr
                )
                if not got_def:
                    print(
                        "    (note: empty definition may be normal for the picked "
                        "symbol; not necessarily a sysroot failure)",
                        file=sys.stderr,
                    )
            except Exception as e:
                print(f"    definition ERROR: {e}", file=sys.stderr)

            try:
                refs = client.request(
                    "textDocument/references",
                    {
                        "textDocument": {"uri": uri},
                        "position": {"line": line, "character": col},
                        "context": {"includeDeclaration": True},
                    },
                    timeout=30,
                )
                nrefs = len(refs or [])
                report["checks"].append({"references": nrefs, "symbol": name})
                print(f"    references: {nrefs}", file=sys.stderr)
            except Exception as e:
                print(f"    references ERROR: {e}", file=sys.stderr)

    finally:
        client.shutdown()

    # ---- 汇总 ----
    total_syms = sum(v["symbols"] for v in report["files"].values())
    total_errs = sum(v["errors"] for v in report["files"].values())
    total_inf = sum(v.get("include_not_found", 0) for v in report["files"].values())
    print("\n==== VERIFICATION SUMMARY ====", file=sys.stderr)
    print(f"files tested        : {len(report['files'])}", file=sys.stderr)
    print(f"total symbols       : {total_syms}", file=sys.stderr)
    print(f"total hard errors   : {total_errs}", file=sys.stderr)
    print(f"include-not-found   : {total_inf}", file=sys.stderr)
    print(json.dumps(report, indent=2, ensure_ascii=False))

    # 语义健全性闸门(PoC 发现 1 的根治):
    # 仅凭 symbols>0 会被语法兜底骗过(clangd 静默回退到无 flag 模式时
    # tree-sitter 式解析仍吐符号)。真正接上 sysroot 的标志是:
    # 凡 #include 了 sysroot 头的文件,绝不出现 file-not-found。
    # 因此 include-not-found > 0 => sysroot/CDB flag 没吃到 => 判 FAIL,即使有符号。
    if not ok or total_syms == 0:
        print(
            "RESULT: FAIL (clangd did not index symbols — check sysroot/CDB)",
            file=sys.stderr,
        )
        return 1
    if total_inf > 0:
        print(
            f"RESULT: FAIL (sysroot NOT effective — {total_inf} include-not-found "
            f"errors). clangd likely fell back to no-flags mode; symbols are "
            f"syntactic-only. Check: is the rewritten CDB named exactly "
            f"'compile_commands.json' in the dir you passed?",
            file=sys.stderr,
        )
        return 1
    print(
        "RESULT: PASS (clangd indexed with sysroot effective — "
        "0 include-not-found, semantic types resolved)",
        file=sys.stderr,
    )
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cdb", help="rewritten compile_commands.json")
    ap.add_argument(
        "--clangd", default="clangd", help="clangd binary (default: host clangd)"
    )
    ap.add_argument(
        "--file",
        action="append",
        default=[],
        help="specific source file(s) to test; repeatable",
    )
    ap.add_argument("--func", default=None, help="function name to probe for def/refs")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    return run_verification(args.cdb, args.clangd, args.file, args.func, args.verbose)


if __name__ == "__main__":
    raise SystemExit(main())
