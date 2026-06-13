#!/usr/bin/env python3
"""
cdb_rewriter.py — 把 GBS chroot 视角的 compile_commands.json 改写成
宿主机 clangd 能直接 index 的形式。

转换规则全部来自 GBS-clangd-feasibility-report.md 的实测结论:
  1. directory: chroot 内绝对路径 -> 加 <BUILDROOT> 前缀
  2. 绝对路径 -I/-isystem/-iquote (/usr/... 等) -> 加 <BUILDROOT> 前缀
  3. 相对 -I -> 保留原样(靠 directory 已被前缀解决)
  4. 注入 --target=<triple>(从 <BUILDROOT>/usr/lib/gcc/ 目录名动态取,或显式给)
  5. 注入 --sysroot=<BUILDROOT>
  6. 丢弃语法检查无关的 flag:-Wa,* / -Wl,* / -frecord-gcc-switches / -c / -o <x> / -MD 等
  7. -m* (codegen) flag 原样保留
  8. file 字段:相对 -> 基于(已前缀的)directory 解析为绝对路径

设计原则(对应 CodeGraph 定位):
  - 纯函数式、可单测、无副作用(不碰文件系统,除了最外层 main)
  - 不假设 driver 是 clang 还是 gcc;clangd 只解析参数不执行 driver
  - 默认面向"宿主机 clangd"运行时:不注入 -resource-dir(clangd 自带)
    若 inject_resource_dir 给了值,则注入(留给"直接调 clang 二进制"的场景)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import sys
from dataclasses import dataclass, field
from typing import Optional

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RewriteConfig:
    buildroot: str  # <BUILDROOT> 绝对路径(宿主机上的实际位置)
    target: Optional[str] = None  # --target=...;None 则尝试从 buildroot 自动探测
    inject_resource_dir: Optional[str] = (
        None  # 仅"直调 clang 二进制"场景需要;clangd 留空
    )
    # chroot 内会被加前缀的绝对路径根(只含真正可能承载 include/库的根)。
    # 注意:不含 /etc —— /etc 是目标设备的运行期路径,不是 include 根,
    # 误前缀会把 -DSYSCONFDIR="/etc" 改坏(见 PoC 发现 2)。
    chroot_abs_roots: tuple[str, ...] = (
        "/usr",
        "/lib",
        "/lib64",
        "/opt",
        "/home/abuild",
    )
    # 语法检查无关、应丢弃的 flag(精确匹配或前缀匹配)
    drop_exact: tuple[str, ...] = ("-c", "-frecord-gcc-switches", "-pipe", "-g")
    drop_prefix: tuple[str, ...] = ("-Wa,", "-Wl,", "-Wp,", "-MF", "-MT", "-MQ")
    # 带一个独立参数、需要连参数一起丢的 flag
    drop_with_arg: tuple[str, ...] = ("-o", "-MT", "-MF", "-MQ", "-MJ")
    keep_unknown: bool = True  # 不认识的 flag 默认保留(宁可多留)


# ---------------------------------------------------------------------------
# 路径改写
# ---------------------------------------------------------------------------


def prefix_chroot_path(path: str, cfg: RewriteConfig) -> str:
    """若 path 是 chroot 内绝对路径,加上 buildroot 前缀;否则原样返回。"""
    if not path.startswith("/"):
        return path  # 相对路径不动
    # 已经带了 buildroot 前缀的不重复加
    if path.startswith(cfg.buildroot):
        return path
    for root in cfg.chroot_abs_roots:
        if path == root or path.startswith(root + "/"):
            # /usr/include/glib-2.0 -> <BUILDROOT>/usr/include/glib-2.0
            return cfg.buildroot.rstrip("/") + path
    # 不在已知 chroot 根下的绝对路径(可能是宿主机工程源码树)——保持原样
    return path


# -I/-isystem/-iquote/-idirafter 等带路径的 include flag
_INCLUDE_FLAGS_GLUED = ("-I", "-iquote")  # 可能 -I/path 粘连
_INCLUDE_FLAGS_SPACED = ("-isystem", "-idirafter", "-iquote", "-include", "-isysroot")


def rewrite_include_flag(tok: str, cfg: RewriteConfig) -> str:
    """处理粘连写法 -I/abs/path。返回改写后的 token。"""
    for f in _INCLUDE_FLAGS_GLUED:
        if tok.startswith(f) and len(tok) > len(f):
            path = tok[len(f) :]
            return f + prefix_chroot_path(path, cfg)
    # -D 里也可能内嵌 chroot 绝对路径(报告 D10: -DLIB_PATH=\"/.../usr/lib64\")
    if tok.startswith("-D") and "/" in tok:
        return _rewrite_define_embedded_path(tok, cfg)
    return tok


# -D 里内嵌的 chroot 路径。只匹配真正可能是 include/库根的前缀(不含 /etc)。
_DEFINE_PATH_RE = re.compile(r'(/(?:usr|lib64|lib|opt|home/abuild)(?:/[^"\\\s]*)?)')


def _rewrite_define_embedded_path(tok: str, cfg: RewriteConfig) -> str:
    """把 -DXXX="/usr/..." 里内嵌的 chroot 绝对路径加前缀。
    防双前缀:若匹配到的路径前面已经紧跟 buildroot,说明已前缀,跳过
    (PoC 发现 2:-DLIB_PATH="<root>/usr/lib64" 旧逻辑会再加一遍)。
    保守:只在加前缀后该路径在 sysroot 里真实存在时才改,避免误伤纯逻辑/运行期宏。"""
    br = cfg.buildroot.rstrip("/")

    def _sub(m: re.Match) -> str:
        p = m.group(1)
        start = m.start(1)
        # 匹配位置之前的文本若以 buildroot 结尾,说明这段 /usr/... 已经被前缀过
        preceding = tok[:start]
        if preceding.endswith(br):
            return p
        cand = br + p
        return cand if os.path.exists(cand) else p

    return _DEFINE_PATH_RE.sub(_sub, tok)


# ---------------------------------------------------------------------------
# triple 自动探测
# ---------------------------------------------------------------------------


def detect_triple(buildroot: str) -> Optional[str]:
    """从 <BUILDROOT>/usr/lib/gcc/<triple>/ 或 usr/lib64/gcc/<triple>/ 取 triple。"""
    for libdir in ("lib", "lib64"):
        gcc_dir = os.path.join(buildroot, "usr", libdir, "gcc")
        if os.path.isdir(gcc_dir):
            entries = [
                d
                for d in os.listdir(gcc_dir)
                if os.path.isdir(os.path.join(gcc_dir, d))
            ]
            if len(entries) == 1:
                return entries[0]
            # 多个时,优先含 tizen 的
            tizen = [e for e in entries if "tizen" in e]
            if len(tizen) == 1:
                return tizen[0]
    return None


# ---------------------------------------------------------------------------
# 单条 entry 改写
# ---------------------------------------------------------------------------


@dataclass
class RewriteStats:
    entries_in: int = 0
    entries_out: int = 0
    tokens_dropped: int = 0
    paths_prefixed: int = 0
    skipped_no_file: int = 0
    notes: list[str] = field(default_factory=list)


def _split_command(entry: dict) -> list[str]:
    """entry 可能用 'command'(字符串)或 'arguments'(数组)。统一成 token 列表。"""
    if "arguments" in entry and entry["arguments"]:
        return list(entry["arguments"])
    if "command" in entry and entry["command"]:
        return shlex.split(entry["command"])
    raise ValueError(f"entry has neither command nor arguments: {entry.get('file')}")


def rewrite_entry(entry: dict, cfg: RewriteConfig, stats: RewriteStats) -> dict:
    toks = _split_command(entry)
    out: list[str] = []
    i = 0
    # 第一个 token 是 driver,原样保留(clangd 不执行它)
    if toks:
        out.append(toks[0])
        i = 1

    while i < len(toks):
        tok = toks[i]

        # 丢弃: 带独立参数的 flag(如 -o foo.o)
        if tok in cfg.drop_with_arg:
            stats.tokens_dropped += 1
            i += 2  # 连同它的参数
            continue
        # 丢弃: 精确匹配
        if tok in cfg.drop_exact:
            stats.tokens_dropped += 1
            i += 1
            continue
        # 丢弃: 前缀匹配(-Wa, / -Wl, / -Wp, / -MF...)
        if any(tok.startswith(p) for p in cfg.drop_prefix):
            stats.tokens_dropped += 1
            i += 1
            continue
        # 丢弃: -MD/-MMD(依赖生成)
        if tok in ("-MD", "-MMD", "-MP", "-MG"):
            stats.tokens_dropped += 1
            i += 1
            continue

        # -isystem/-idirafter/-include/-isysroot <path> 空格分隔形式
        if tok in _INCLUDE_FLAGS_SPACED:
            out.append(tok)
            if i + 1 < len(toks):
                before = toks[i + 1]
                after = prefix_chroot_path(before, cfg)
                if after != before:
                    stats.paths_prefixed += 1
                out.append(after)
                i += 2
                continue
            i += 1
            continue

        # -I/path 粘连 / -iquote/path / -D...="/usr/..."
        new_tok = rewrite_include_flag(tok, cfg)
        if new_tok != tok:
            stats.paths_prefixed += 1
        out.append(new_tok)
        i += 1

    # 注入 sysroot / target / resource-dir(放在 driver 之后)
    inject = ["--sysroot=" + cfg.buildroot]
    if cfg.target:
        inject.append("--target=" + cfg.target)
    if cfg.inject_resource_dir:
        inject += ["-resource-dir", cfg.inject_resource_dir]
    # 避免 GBS clang.cfg 干扰(若 driver 恰好是 chroot clang)
    inject.append("--no-default-config")
    out = [out[0]] + inject + out[1:] if out else inject

    # directory 前缀
    new_dir = prefix_chroot_path(entry.get("directory", ""), cfg)
    if new_dir != entry.get("directory", ""):
        stats.paths_prefixed += 1

    # file: 解析为绝对路径(基于已前缀的 directory)
    f = entry.get("file", "")
    if f and not f.startswith("/"):
        f_abs = os.path.normpath(os.path.join(new_dir, f))
    else:
        f_abs = prefix_chroot_path(f, cfg)

    result = {
        "directory": new_dir,
        "file": f_abs,
        "arguments": out,
    }
    return result


def rewrite_cdb(
    cdb: list[dict], cfg: RewriteConfig, require_file_exists: bool = True
) -> tuple[list[dict], RewriteStats]:
    stats = RewriteStats()
    out: list[dict] = []
    for entry in cdb:
        stats.entries_in += 1
        try:
            r = rewrite_entry(entry, cfg, stats)
        except ValueError as e:
            stats.notes.append(str(e))
            continue
        if require_file_exists and not os.path.exists(r["file"]):
            stats.skipped_no_file += 1
            continue
        out.append(r)
        stats.entries_out += 1
    return out, stats


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Rewrite GBS chroot CDB for host clangd.")
    ap.add_argument("input", help="path to source compile_commands.json")
    ap.add_argument(
        "output",
        help="output path. If it ends with .json, written as that file. "
        "Otherwise treated as a DIRECTORY and written as "
        "<output>/compile_commands.json (required name for clangd's "
        "--compile-commands-dir).",
    )
    ap.add_argument(
        "--buildroot", required=True, help="<BUILDROOT> absolute path on host"
    )
    ap.add_argument(
        "--target",
        default=None,
        help="target triple; auto-detected from buildroot if omitted",
    )
    ap.add_argument(
        "--resource-dir",
        default=None,
        help="inject -resource-dir (only for direct-clang use; leave empty for clangd)",
    )
    ap.add_argument(
        "--keep-missing-files",
        action="store_true",
        help="keep entries whose file does not exist on host",
    )
    args = ap.parse_args(argv)

    if not os.path.isdir(args.buildroot):
        print(f"ERROR: buildroot not found: {args.buildroot}", file=sys.stderr)
        return 2

    target = args.target or detect_triple(args.buildroot)
    if not target:
        print(
            "WARNING: could not auto-detect triple; proceeding without --target",
            file=sys.stderr,
        )

    cfg = RewriteConfig(
        buildroot=os.path.abspath(args.buildroot),
        target=target,
        inject_resource_dir=args.resource_dir,
    )

    with open(args.input, encoding="utf-8") as fh:
        cdb = json.load(fh)

    out, stats = rewrite_cdb(cdb, cfg, require_file_exists=not args.keep_missing_files)

    # 输出布局:clangd 的 --compile-commands-dir 只读名为 compile_commands.json 的文件。
    # 若 output 不是 .json,当作目录,写成 <output>/compile_commands.json(PoC 发现 1)。
    if args.output.endswith(".json"):
        out_path = args.output
    else:
        os.makedirs(args.output, exist_ok=True)
        out_path = os.path.join(args.output, "compile_commands.json")

    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2, ensure_ascii=False)

    print(f"[cdb_rewriter] wrote           = {out_path}", file=sys.stderr)
    print(f"[cdb_rewriter] target          = {target}", file=sys.stderr)
    print(
        f"[cdb_rewriter] entries in/out  = {stats.entries_in} / {stats.entries_out}",
        file=sys.stderr,
    )
    print(f"[cdb_rewriter] paths prefixed  = {stats.paths_prefixed}", file=sys.stderr)
    print(f"[cdb_rewriter] tokens dropped  = {stats.tokens_dropped}", file=sys.stderr)
    print(f"[cdb_rewriter] skipped(no file)= {stats.skipped_no_file}", file=sys.stderr)
    for n in stats.notes[:10]:
        print(f"[cdb_rewriter] note: {n}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
