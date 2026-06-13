#!/usr/bin/env python3
"""test_cdb_rewriter.py — 用合成数据钉死改写规则(不依赖真机)。"""

import os
import pytest

from cdb_rewriter import (
    RewriteConfig,
    RewriteStats,
    prefix_chroot_path,
    rewrite_include_flag,
    rewrite_entry,
    _split_command,
    detect_triple,
)

BR = "/home/u/GBS-ROOT/local/BUILD-ROOTS/scratch.armv7l.0"


def cfg(**kw):
    base = dict(buildroot=BR, target="armv7l-tizen-linux-gnueabi")
    base.update(kw)
    return RewriteConfig(**base)


# ---- prefix_chroot_path ----


def test_prefix_usr_abs():
    assert (
        prefix_chroot_path("/usr/include/glib-2.0", cfg())
        == BR + "/usr/include/glib-2.0"
    )


def test_prefix_lib_abs():
    assert prefix_chroot_path("/lib/foo", cfg()) == BR + "/lib/foo"


def test_prefix_home_abuild():
    assert (
        prefix_chroot_path("/home/abuild/rpmbuild/BUILD/x", cfg())
        == BR + "/home/abuild/rpmbuild/BUILD/x"
    )


def test_relative_untouched():
    assert prefix_chroot_path("subdir/include", cfg()) == "subdir/include"


def test_already_prefixed_not_doubled():
    p = BR + "/usr/include"
    assert prefix_chroot_path(p, cfg()) == p


def test_host_source_tree_untouched():
    # 不在 chroot 根下的绝对路径(宿主机工程源码)不动
    p = "/home/u/Toolchain/codes/pkgmgr-info/include"
    assert prefix_chroot_path(p, cfg()) == p


# ---- include flags ----


def test_glued_I_flag():
    assert (
        rewrite_include_flag("-I/usr/include/dlog", cfg())
        == "-I" + BR + "/usr/include/dlog"
    )


def test_glued_I_relative_untouched():
    assert rewrite_include_flag("-Isubprojects/gst", cfg()) == "-Isubprojects/gst"


def test_glued_I_host_tree_untouched():
    src = "-I/home/u/Toolchain/codes/pkgmgr-info/include"
    assert rewrite_include_flag(src, cfg()) == src


# ---- entry: 完整改写(meson ARM 风格,command 字符串) ----


def make_meson_entry():
    return {
        "directory": "/home/abuild/rpmbuild/BUILD/gstreamer-1.24.11/build",
        "file": "../subprojects/gstreamer/gst/gstelement.c",
        "command": (
            "cc -Isubprojects/gstreamer/gst -I../subprojects/gstreamer/gst "
            "-I/usr/include/glib-2.0 -I/usr/lib/glib-2.0/include "
            "-march=armv7-a -mfpu=neon -mfloat-abi=softfp -mthumb "
            "-Wa,-mimplicit-it=thumb -frecord-gcc-switches "
            "-DHAVE_CONFIG_H -O2 -g -MD -MQ x.o -MF x.o.d "
            "-o gstelement.c.o -c ../subprojects/gstreamer/gst/gstelement.c"
        ),
    }


def test_meson_entry_full_rewrite():
    stats = RewriteStats()
    r = rewrite_entry(make_meson_entry(), cfg(), stats)
    args = r["arguments"]

    # driver 保留
    assert args[0] == "cc"
    # 注入了 sysroot + target + no-default-config
    assert "--sysroot=" + BR in args
    assert "--target=armv7l-tizen-linux-gnueabi" in args
    assert "--no-default-config" in args
    # chroot 绝对 -I 被前缀
    assert "-I" + BR + "/usr/include/glib-2.0" in args
    assert "-I" + BR + "/usr/lib/glib-2.0/include" in args
    # 相对 -I 保留
    assert "-Isubprojects/gstreamer/gst" in args
    # ARM codegen flag 保留
    for m in ("-march=armv7-a", "-mfpu=neon", "-mfloat-abi=softfp", "-mthumb"):
        assert m in args
    # 语法无关 flag 被丢
    assert not any(a.startswith("-Wa,") for a in args)
    assert "-frecord-gcc-switches" not in args
    assert "-c" not in args
    assert "-MD" not in args
    # -o 及其参数都被丢
    assert "-o" not in args
    assert "gstelement.c.o" not in args
    # -MQ x.o / -MF x.o.d 的参数也不残留
    assert "x.o" not in args
    assert "x.o.d" not in args
    # -D 逻辑宏保留
    assert "-DHAVE_CONFIG_H" in args

    # directory 被前缀
    assert r["directory"] == BR + "/home/abuild/rpmbuild/BUILD/gstreamer-1.24.11/build"
    # file 解析成基于前缀 directory 的绝对路径
    assert r["file"] == os.path.normpath(
        BR + "/home/abuild/rpmbuild/BUILD/gstreamer-1.24.11/build/"
        "../subprojects/gstreamer/gst/gstelement.c"
    )


# ---- entry: clang driver + arguments 数组 + 内嵌 -D 路径 ----


def test_define_embedded_path(tmp_path):
    # 造一个真实存在的 sysroot 路径,验证 -DLIB_PATH 会被前缀
    br = str(tmp_path)
    os.makedirs(os.path.join(br, "usr", "lib64"))
    c = RewriteConfig(buildroot=br, target="x86_64-tizen-linux-gnu")
    tok = '-DLIB_PATH="/usr/lib64"'
    out = rewrite_include_flag(tok, c)
    assert br + "/usr/lib64" in out


def test_define_pure_logic_macro_untouched():
    # 不含真实路径的 -D 不应被乱改
    assert rewrite_include_flag("-DHAVE_CONFIG_H", cfg()) == "-DHAVE_CONFIG_H"
    assert (
        rewrite_include_flag("-D_FILE_OFFSET_BITS=64", cfg())
        == "-D_FILE_OFFSET_BITS=64"
    )


# ---- PoC 发现 2 的两个回归 ----


def test_define_already_prefixed_no_double(tmp_path):
    # -DLIB_PATH="<root>/usr/lib64" 已带前缀,不应再加(双前缀 bug)
    br = str(tmp_path)
    os.makedirs(os.path.join(br, "usr", "lib64"))
    c = RewriteConfig(buildroot=br, target="x86_64-tizen-linux-gnu")
    tok = f'-DLIB_PATH="{br}/usr/lib64"'
    out = rewrite_include_flag(tok, c)
    assert out.count(br) == 1, f"double prefix: {out}"
    assert out == tok


def test_define_sysconfdir_etc_untouched():
    # -DSYSCONFDIR="/etc" 是运行期路径,绝不能前缀
    tok = '-DSYSCONFDIR="/etc"'
    assert rewrite_include_flag(tok, cfg()) == tok


def test_etc_not_in_chroot_roots():
    # /etc 不应被当作 chroot include 根
    assert prefix_chroot_path("/etc/foo", cfg()) == "/etc/foo"


# ---- arguments vs command 都支持 ----


def test_arguments_array_input():
    e = {
        "directory": "/usr/src",
        "file": "a.c",
        "arguments": ["clang", "-I/usr/include", "-c", "a.c", "-o", "a.o"],
    }
    toks = _split_command(e)
    assert toks[0] == "clang"
    stats = RewriteStats()
    r = rewrite_entry(e, cfg(), stats)
    assert "-I" + BR + "/usr/include" in r["arguments"]
    assert "-o" not in r["arguments"]


# ---- triple 自动探测 ----


def test_detect_triple_single(tmp_path):
    gccdir = tmp_path / "usr" / "lib" / "gcc" / "armv7l-tizen-linux-gnueabi" / "14.2.0"
    gccdir.mkdir(parents=True)
    assert detect_triple(str(tmp_path)) == "armv7l-tizen-linux-gnueabi"


def test_detect_triple_lib64(tmp_path):
    gccdir = tmp_path / "usr" / "lib64" / "gcc" / "x86_64-tizen-linux-gnu" / "14.2.0"
    gccdir.mkdir(parents=True)
    assert detect_triple(str(tmp_path)) == "x86_64-tizen-linux-gnu"


def test_detect_triple_none(tmp_path):
    assert detect_triple(str(tmp_path)) is None


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
