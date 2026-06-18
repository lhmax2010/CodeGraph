from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from codegraph.credibility import IndexHealth
from codegraph.indexing import (
    BackgroundIndexConfig,
    compile_commands_path,
    evaluate_index_health,
    index_dir_for_compile_commands_dir,
    rewrite_cdb_for_index,
    run_background_index,
    scan_index_shards,
    summarize_compile_commands,
)


def write_cdb(directory: Path, files: list[Path]) -> Path:
    cdb = [
        {
            "directory": str(directory),
            "file": str(file),
            "arguments": ["cc", "--target=x86_64-tizen-linux-gnu", str(file)],
        }
        for file in files
    ]
    path = directory / "compile_commands.json"
    path.write_text(json.dumps(cdb), encoding="utf-8")
    return path


def touch_idx(index_dir: Path, count: int) -> None:
    index_dir.mkdir(parents=True, exist_ok=True)
    for idx in range(count):
        (index_dir / f"tu{idx}.idx").write_text("idx", encoding="utf-8")


def test_compile_commands_summary_deduplicates_unique_tu(tmp_path: Path):
    source = tmp_path / "a.c"
    source.write_text("int a;", encoding="utf-8")
    write_cdb(tmp_path, [source, source])

    summary = summarize_compile_commands(tmp_path)

    assert compile_commands_path(tmp_path) == tmp_path / "compile_commands.json"
    assert summary.entries == 2
    assert summary.unique_tu_count == 1
    assert summary.existing_files == 1
    assert summary.targets == ("--target=x86_64-tizen-linux-gnu",)


def test_compile_commands_summary_parses_command_string(tmp_path: Path):
    source = tmp_path / "a.c"
    source.write_text("int a;", encoding="utf-8")
    (tmp_path / "compile_commands.json").write_text(
        json.dumps(
            [
                {
                    "directory": str(tmp_path),
                    "file": str(source),
                    "command": (
                        "cc --target=armv7l-tizen-linux-gnueabi "
                        "--sysroot=/opt/tizen -c a.c"
                    ),
                }
            ]
        ),
        encoding="utf-8",
    )

    summary = summarize_compile_commands(tmp_path)

    assert summary.targets == ("--target=armv7l-tizen-linux-gnueabi",)
    assert summary.sysroots == ("--sysroot=/opt/tizen",)


def test_compile_commands_summary_resolves_relative_files_from_entry_directory(
    tmp_path: Path,
):
    left = tmp_path / "left"
    right = tmp_path / "right"
    left.mkdir()
    right.mkdir()
    (left / "main.c").write_text("int left;", encoding="utf-8")
    (right / "main.c").write_text("int right;", encoding="utf-8")
    (tmp_path / "compile_commands.json").write_text(
        json.dumps(
            [
                {"directory": str(left), "file": "main.c", "arguments": ["cc"]},
                {"directory": str(right), "file": "main.c", "arguments": ["cc"]},
                {"directory": str(right), "arguments": ["cc"]},
            ]
        ),
        encoding="utf-8",
    )

    summary = summarize_compile_commands(tmp_path)

    assert summary.entries == 3
    assert summary.unique_tu_count == 2
    assert summary.existing_files == 2


def test_compile_commands_summary_canonicalizes_symlink_and_parent_paths(
    tmp_path: Path,
):
    src = tmp_path / "src"
    nested = tmp_path / "nested"
    src.mkdir()
    nested.mkdir()
    source = src / "main.c"
    source.write_text("int main(void) { return 0; }", encoding="utf-8")
    link = tmp_path / "link-src"
    try:
        link.symlink_to(src, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink unavailable: {exc}")

    (tmp_path / "compile_commands.json").write_text(
        json.dumps(
            [
                {"directory": str(tmp_path), "file": "src/main.c", "arguments": ["cc"]},
                {
                    "directory": str(nested),
                    "file": "../src/./main.c",
                    "arguments": ["cc"],
                },
                {
                    "directory": str(tmp_path),
                    "file": "link-src/main.c",
                    "arguments": ["cc"],
                },
            ]
        ),
        encoding="utf-8",
    )

    summary = summarize_compile_commands(tmp_path)

    assert summary.entries == 3
    assert summary.unique_tu_count == 1
    assert summary.existing_files == 1


def test_index_health_lower_bound_complete_incomplete_and_unknown(tmp_path: Path):
    one = tmp_path / "one.c"
    two = tmp_path / "two.c"
    one.write_text("int one;", encoding="utf-8")
    two.write_text("int two;", encoding="utf-8")
    write_cdb(tmp_path, [one, two])
    cdb = summarize_compile_commands(tmp_path)
    index_dir = index_dir_for_compile_commands_dir(tmp_path)

    missing = evaluate_index_health(cdb, scan_index_shards(index_dir))
    assert missing.health == IndexHealth.UNKNOWN
    assert missing.reason == "index_dir_missing"

    index_dir.mkdir(parents=True)
    (index_dir / "not-an-index.txt").write_text("x", encoding="utf-8")
    no_idx = evaluate_index_health(cdb, scan_index_shards(index_dir))
    assert no_idx.health == IndexHealth.UNKNOWN
    assert no_idx.reason == "no_idx_files"

    (index_dir / "not-an-index.txt").unlink()
    touch_idx(index_dir, 1)
    incomplete = evaluate_index_health(cdb, scan_index_shards(index_dir))
    assert incomplete.health == IndexHealth.INCOMPLETE
    assert incomplete.reason == "shards_lt_unique_tu"

    touch_idx(index_dir, 2)
    complete = evaluate_index_health(cdb, scan_index_shards(index_dir))
    assert complete.health == IndexHealth.COMPLETE
    assert complete.reason == "shards_ge_unique_tu"


def test_index_health_no_translation_units_is_unknown(tmp_path: Path):
    (tmp_path / "compile_commands.json").write_text("[]", encoding="utf-8")
    cdb = summarize_compile_commands(tmp_path)
    index_dir = index_dir_for_compile_commands_dir(tmp_path)
    touch_idx(index_dir, 1)

    report = evaluate_index_health(cdb, scan_index_shards(index_dir))

    assert report.health == IndexHealth.UNKNOWN
    assert report.reason == "no_translation_units"


def test_rewrite_cdb_for_index_reuses_existing_rewriter(tmp_path: Path):
    buildroot = tmp_path / "buildroot"
    source_dir = buildroot / "home" / "abuild" / "project"
    source_dir.mkdir(parents=True)
    (source_dir / "a.c").write_text("int a;", encoding="utf-8")
    (buildroot / "usr" / "lib" / "gcc" / "armv7l-tizen-linux-gnueabi").mkdir(
        parents=True
    )
    (buildroot / "usr" / "include").mkdir(parents=True)
    input_cdb = tmp_path / "input.json"
    input_cdb.write_text(
        json.dumps(
            [
                {
                    "directory": "/home/abuild/project",
                    "file": "a.c",
                    "arguments": ["cc", "-I/usr/include", "-c", "a.c"],
                }
            ]
        ),
        encoding="utf-8",
    )

    result = rewrite_cdb_for_index(
        input_cdb, tmp_path / "rewritten", buildroot=buildroot
    )
    rewritten = json.loads(Path(result.output_cdb).read_text(encoding="utf-8"))

    assert result.entries_in == result.entries_out == 1
    assert result.target == "armv7l-tizen-linux-gnueabi"
    assert rewritten[0]["file"] == str(source_dir / "a.c")
    assert "--target=armv7l-tizen-linux-gnueabi" in rewritten[0]["arguments"]
    assert "--sysroot=" + str(buildroot) in rewritten[0]["arguments"]


def test_rewrite_cdb_for_index_finds_tools_without_pythonpath(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo_root = Path(__file__).resolve().parents[1]
    tools_dir = repo_root / "tools"
    monkeypatch.delitem(sys.modules, "cdb_rewriter", raising=False)
    monkeypatch.setattr(
        sys,
        "path",
        [
            entry
            for entry in sys.path
            if Path(entry or ".").resolve() != tools_dir.resolve()
        ],
    )
    buildroot = tmp_path / "buildroot"
    source_dir = buildroot / "home" / "abuild" / "project"
    source_dir.mkdir(parents=True)
    (source_dir / "a.c").write_text("int a;", encoding="utf-8")
    (buildroot / "usr" / "lib" / "gcc" / "armv7l-tizen-linux-gnueabi").mkdir(
        parents=True
    )
    input_cdb = tmp_path / "input.json"
    input_cdb.write_text(
        json.dumps(
            [
                {
                    "directory": "/home/abuild/project",
                    "file": "a.c",
                    "arguments": ["cc", "-c", "a.c"],
                }
            ]
        ),
        encoding="utf-8",
    )

    result = rewrite_cdb_for_index(
        input_cdb, tmp_path / "rewritten", buildroot=buildroot
    )

    assert result.entries_out == 1
    assert str(tools_dir) in sys.path


def test_background_index_smoke_builds_idx_shard(tmp_path: Path):
    if shutil.which("clangd") is None:
        pytest.skip("clangd is not installed")
    source = tmp_path / "main.c"
    source.write_text(
        "int helper(int x) { return x + 1; }\n"
        "int main(void) { return helper(41); }\n",
        encoding="utf-8",
    )
    write_cdb(tmp_path, [source])

    result = run_background_index(
        BackgroundIndexConfig(
            compile_commands_dir=str(tmp_path),
            jobs=2,
            max_wait_seconds=10,
            poll_interval_seconds=0.2,
            stable_rounds=2,
        )
    )

    assert result.exit_code == 0
    assert result.stable is True
    assert result.shard_report.idx_shards >= 1
    assert result.health_report.health == IndexHealth.COMPLETE


def test_background_index_missing_clangd_degrades_to_unknown(tmp_path: Path):
    source = tmp_path / "main.c"
    source.write_text("int main(void) { return 0; }\n", encoding="utf-8")
    write_cdb(tmp_path, [source])

    result = run_background_index(
        BackgroundIndexConfig(
            compile_commands_dir=str(tmp_path),
            clangd_path=str(tmp_path / "missing-clangd"),
            max_wait_seconds=0.1,
            poll_interval_seconds=0.01,
            stable_rounds=1,
        )
    )

    assert result.exit_code is None
    assert result.stable is False
    assert result.health_report.health == IndexHealth.UNKNOWN
    assert result.health_report.reason == "index_build_failed"
    assert "FileNotFoundError" in result.stderr_tail


def test_existing_real_arm_x86_indices_are_complete_when_available():
    roots = [
        Path("/home/linhao/Toolchain/codes/rw_arm"),
        Path("/home/linhao/Toolchain/codes/rw_x86"),
    ]
    if not all((root / "compile_commands.json").exists() for root in roots):
        pytest.skip("real ARM/x86 CDB fixtures are not available")

    reports = []
    for root in roots:
        cdb = summarize_compile_commands(root)
        shards = scan_index_shards(index_dir_for_compile_commands_dir(root))
        reports.append(evaluate_index_health(cdb, shards))

    assert [report.health for report in reports] == [
        IndexHealth.COMPLETE,
        IndexHealth.COMPLETE,
    ]


def test_build_index_cli_inspect_only(tmp_path: Path):
    source = tmp_path / "main.c"
    source.write_text("int main(void) { return 0; }\n", encoding="utf-8")
    write_cdb(tmp_path, [source])
    touch_idx(index_dir_for_compile_commands_dir(tmp_path), 1)

    completed = subprocess.run(
        [
            sys.executable,
            "tools/build_index.py",
            "--compile-commands-dir",
            str(tmp_path),
            "--inspect-only",
        ],
        cwd=Path(__file__).resolve().parents[1],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    payload = json.loads(completed.stdout)

    assert payload["health"]["health"] == IndexHealth.COMPLETE
    assert payload["health"]["idx_shards"] == 1


def test_build_index_cli_invalid_input_reports_json(tmp_path: Path):
    completed = subprocess.run(
        [
            sys.executable,
            "tools/build_index.py",
            "--compile-commands-dir",
            str(tmp_path / "missing"),
            "--inspect-only",
        ],
        cwd=Path(__file__).resolve().parents[1],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    payload = json.loads(completed.stdout)

    assert completed.returncode == 1
    assert payload["health"] == IndexHealth.UNKNOWN
    assert payload["reason"] == "invalid_input"
    assert "FileNotFoundError" in payload["error"]
    assert "Traceback" not in completed.stderr


def test_build_index_cli_malformed_json_reports_json(tmp_path: Path):
    (tmp_path / "compile_commands.json").write_text("{", encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            "tools/build_index.py",
            "--compile-commands-dir",
            str(tmp_path),
            "--inspect-only",
        ],
        cwd=Path(__file__).resolve().parents[1],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    payload = json.loads(completed.stdout)

    assert completed.returncode == 1
    assert payload["health"] == IndexHealth.UNKNOWN
    assert payload["reason"] == "invalid_input"
    assert "JSONDecodeError" in payload["error"]
    assert "Traceback" not in completed.stderr


def test_build_index_cli_rewrites_cdb_and_builds_shards(tmp_path: Path):
    if shutil.which("clangd") is None:
        pytest.skip("clangd is not installed")
    buildroot = tmp_path / "buildroot"
    source_dir = buildroot / "home" / "abuild" / "project"
    source_dir.mkdir(parents=True)
    (source_dir / "main.c").write_text("int main(void) { return 0; }\n")
    (buildroot / "usr" / "lib" / "gcc" / "x86_64-tizen-linux-gnu").mkdir(parents=True)
    (buildroot / "usr" / "include").mkdir(parents=True)
    input_cdb = tmp_path / "input.json"
    input_cdb.write_text(
        json.dumps(
            [
                {
                    "directory": "/home/abuild/project",
                    "file": "main.c",
                    "command": "cc -I/usr/include -c main.c",
                }
            ]
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            "tools/build_index.py",
            "--input-cdb",
            str(input_cdb),
            "--output-dir",
            str(tmp_path / "rewritten"),
            "--buildroot",
            str(buildroot),
            "--jobs",
            "2",
            "--max-wait",
            "10",
            "--poll-interval",
            "0.2",
            "--stable-rounds",
            "2",
        ],
        cwd=Path(__file__).resolve().parents[1],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    payload = json.loads(completed.stdout)

    assert payload["rewrite"]["entries_in"] == 1
    assert payload["rewrite"]["entries_out"] == 1
    assert payload["rewrite"]["target"] == "x86_64-tizen-linux-gnu"
    assert payload["build"]["exit_code"] == 0
    assert payload["build"]["stable"] is True
    assert payload["build"]["shard_report"]["idx_shards"] >= 1
    assert payload["build"]["health_report"]["health"] == IndexHealth.COMPLETE


def test_build_index_cli_reports_unknown_when_clangd_missing(tmp_path: Path):
    source = tmp_path / "main.c"
    source.write_text("int main(void) { return 0; }\n", encoding="utf-8")
    write_cdb(tmp_path, [source])

    completed = subprocess.run(
        [
            sys.executable,
            "tools/build_index.py",
            "--compile-commands-dir",
            str(tmp_path),
            "--clangd",
            str(tmp_path / "missing-clangd"),
            "--max-wait",
            "0.1",
            "--poll-interval",
            "0.01",
            "--stable-rounds",
            "1",
        ],
        cwd=Path(__file__).resolve().parents[1],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    payload = json.loads(completed.stdout)

    assert payload["build"]["exit_code"] is None
    assert payload["build"]["health_report"]["health"] == IndexHealth.UNKNOWN
    assert payload["build"]["health_report"]["reason"] == "index_build_failed"
