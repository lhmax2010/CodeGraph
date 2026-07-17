from __future__ import annotations

import fcntl
import json
import os
import shlex
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import codegraph.indexing as indexing_module
from codegraph.credibility import IndexHealth
from codegraph.indexing import (
    BackgroundIndexConfig,
    acquire_index_cache_lock,
    compile_commands_path,
    evaluate_index_health,
    index_dir_for_compile_commands_dir,
    index_engine_building_path,
    index_engine_stamp_path,
    read_index_engine_version,
    rewrite_cdb_for_index,
    run_background_index,
    scan_index_shards,
    stamp_existing_index,
    summarize_compile_commands,
    write_index_engine_version,
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


def fake_clangd(tmp_path: Path, version: str = "18.1.3") -> Path:
    executable = tmp_path / f"clangd-{version}"
    executable.write_text(
        f"#!/bin/sh\necho 'clangd version {version}'\n", encoding="utf-8"
    )
    executable.chmod(0o755)
    return executable


def install_barrier_index_client(
    monkeypatch: pytest.MonkeyPatch,
    barrier: threading.Barrier,
    opened_versions: list[str],
    opened_lock: threading.Lock,
    *,
    fail_after_open: bool = False,
    wait_for_blocked_peer: threading.Event | None = None,
) -> None:
    del barrier

    class BarrierIndexClient:
        def __init__(self, config: BackgroundIndexConfig):
            self.config = config
            version = Path(config.clangd_path).name.removeprefix("clangd-")
            self.engine_version = f"clangd {version}"
            self.opened = False

        def initialize(self) -> None:
            return None

        def notify_initialized(self) -> None:
            return None

        def open_file(self, _file: str) -> None:
            self.opened = True
            with opened_lock:
                opened_versions.append(self.engine_version)
            index_dir = index_dir_for_compile_commands_dir(
                self.config.compile_commands_dir
            )
            index_dir.mkdir(parents=True, exist_ok=True)
            safe_version = self.engine_version.replace(" ", "-")
            (index_dir / f"{safe_version}.idx").write_text(
                self.engine_version, encoding="utf-8"
            )
            if fail_after_open:
                if wait_for_blocked_peer is not None:
                    assert wait_for_blocked_peer.wait(timeout=5)
                raise RuntimeError("synthetic build failure")

        def request_document_symbols(self, _file: str) -> None:
            return None

        def shutdown(self) -> None:
            if not self.opened and wait_for_blocked_peer is not None:
                wait_for_blocked_peer.set()
            return None

        def close(self) -> tuple[int, str]:
            return 0, ""

    monkeypatch.setattr("codegraph.indexing._IndexLspClient", BarrierIndexClient)


def install_probe_barrier(
    monkeypatch: pytest.MonkeyPatch, barrier: threading.Barrier
) -> None:
    def synchronized_probe(path: str) -> str:
        version = Path(path).name.removeprefix("clangd-")
        barrier.wait(timeout=5)
        return f"clangd {version}"

    monkeypatch.setattr("codegraph.indexing.detect_clangd_version", synchronized_probe)


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


def test_index_engine_stamp_has_verified_unverified_and_mismatch_states(
    tmp_path: Path,
):
    source = tmp_path / "main.c"
    source.write_text("int main(void) { return 0; }\n", encoding="utf-8")
    write_cdb(tmp_path, [source])
    index_dir = index_dir_for_compile_commands_dir(tmp_path)
    touch_idx(index_dir, 1)
    cdb = summarize_compile_commands(tmp_path)

    unverified = evaluate_index_health(
        cdb,
        scan_index_shards(index_dir),
        expected_engine_version="clangd 21.1.1",
    )
    assert unverified.health == IndexHealth.UNKNOWN
    assert unverified.reason == "index_engine_unverified"

    write_index_engine_version(index_dir, "clangd version 21.1.1")
    verified = evaluate_index_health(
        cdb,
        scan_index_shards(index_dir),
        expected_engine_version="clangd 21.1.1",
    )
    assert verified.health == IndexHealth.COMPLETE
    assert verified.index_engine_version == "clangd 21.1.1"

    mismatch = evaluate_index_health(
        cdb,
        scan_index_shards(index_dir),
        expected_engine_version="clangd 21.1.2",
    )
    assert mismatch.health == IndexHealth.UNKNOWN
    assert mismatch.reason == "index_engine_mismatch"
    assert mismatch.expected_engine_version == "clangd 21.1.2"
    assert mismatch.index_engine_version == "clangd 21.1.1"


def test_dirty_marker_reports_mismatch_before_build_finishes(tmp_path: Path):
    source = tmp_path / "main.c"
    source.write_text("int main(void) { return 0; }\n", encoding="utf-8")
    write_cdb(tmp_path, [source])
    index_dir = index_dir_for_compile_commands_dir(tmp_path)
    touch_idx(index_dir, 1)
    index_engine_building_path(index_dir).write_text(
        "clangd 21.1.1\n", encoding="utf-8"
    )
    report = evaluate_index_health(
        summarize_compile_commands(tmp_path),
        scan_index_shards(index_dir),
        expected_engine_version="clangd 22.1.8",
    )

    assert report.reason == "index_engine_mismatch"
    assert report.index_engine_version == "clangd 21.1.1"


def test_index_engine_stamp_write_is_create_only_idempotent_and_conflict_safe(
    tmp_path: Path,
):
    index_dir = tmp_path / "index"

    stamp = write_index_engine_version(index_dir, "clangd 21.1.1")
    initial_stat = stamp.stat()

    assert read_index_engine_version(index_dir) == "clangd 21.1.1"
    assert write_index_engine_version(index_dir, "clangd 21.1.1") == stamp
    assert stamp.stat().st_ino == initial_stat.st_ino
    assert stamp.stat().st_mtime_ns == initial_stat.st_mtime_ns

    with pytest.raises(ValueError, match="conflicting index engine"):
        write_index_engine_version(index_dir, "clangd 22.1.8")
    assert read_index_engine_version(index_dir) == "clangd 21.1.1"


@pytest.mark.parametrize("stamp_state", ["invalid", "directory"])
def test_index_engine_stamp_write_rejects_invalid_existing_ownership(
    tmp_path: Path, stamp_state: str
):
    index_dir = tmp_path / "index"
    stamp = index_engine_stamp_path(index_dir)
    stamp.parent.mkdir(parents=True)
    if stamp_state == "invalid":
        stamp.write_text("not-a-clangd-version\n", encoding="utf-8")
    else:
        stamp.mkdir()

    with pytest.raises(ValueError, match="invalid or unreadable"):
        write_index_engine_version(index_dir, "clangd 21.1.1")

    if stamp_state == "invalid":
        assert stamp.read_text(encoding="utf-8") == "not-a-clangd-version\n"
    else:
        assert stamp.is_dir()


def test_index_engine_stamp_concurrent_creation_is_exclusive(tmp_path: Path):
    index_dir = tmp_path / "index"
    versions = ("clangd 21.1.1", "clangd 22.1.8")

    def attempt(version: str) -> tuple[str, str]:
        try:
            write_index_engine_version(index_dir, version)
        except ValueError as exc:
            return "rejected", str(exc)
        return "created", version

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = tuple(pool.map(attempt, versions))

    assert [state for state, _ in outcomes].count("created") == 1
    assert [state for state, _ in outcomes].count("rejected") == 1
    assert read_index_engine_version(index_dir) in versions
    assert not tuple(index_dir.glob("*.tmp"))


def test_index_cache_lock_is_exclusive(tmp_path: Path):
    index_dir = tmp_path / "index"
    lock = acquire_index_cache_lock(index_dir, exclusive=True)
    try:
        with pytest.raises(ValueError, match="locked by an active build"):
            acquire_index_cache_lock(index_dir, exclusive=False)
    finally:
        lock.release()

    peer = acquire_index_cache_lock(index_dir, exclusive=False)
    peer.release()


def test_index_cache_lock_rejects_symlink_path(tmp_path: Path):
    index_dir = tmp_path / ".cache" / "clangd" / "index"
    index_dir.mkdir(parents=True)
    target = tmp_path / "outside-lock"
    target.write_text("outside", encoding="utf-8")
    indexing_module.index_cache_lock_path(index_dir).symlink_to(target)

    with pytest.raises(ValueError, match="lock is unavailable"):
        acquire_index_cache_lock(index_dir, exclusive=True)

    assert target.read_text(encoding="utf-8") == "outside"


def test_index_cache_lock_retries_when_path_changes_after_flock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    index_dir = tmp_path / ".cache" / "clangd" / "index"
    original = indexing_module._require_same_regular_file
    checks = 0

    def fail_first_post_flock_check(
        opened: os.stat_result, current: os.stat_result, path: Path
    ) -> None:
        nonlocal checks
        checks += 1
        if checks == 2:
            raise ValueError("synthetic pathname replacement")
        original(opened, current, path)

    monkeypatch.setattr(
        indexing_module, "_require_same_regular_file", fail_first_post_flock_check
    )
    lock = acquire_index_cache_lock(index_dir, exclusive=True)
    try:
        assert checks >= 4
    finally:
        lock.release()


def test_unlinked_lock_path_cannot_split_brain_between_builders(tmp_path: Path):
    index_dir = tmp_path / ".cache" / "clangd" / "index"
    old_cache_lock = acquire_index_cache_lock(index_dir, exclusive=True)
    dirty_lease = indexing_module._publish_dirty_marker(index_dir, "clangd 21.1.1")
    old_cache_lock.path.unlink()
    replacement_cache_lock = acquire_index_cache_lock(index_dir, exclusive=True)
    try:
        with pytest.raises(
            ValueError, match="leased by an active user|build in progress"
        ):
            indexing_module._publish_dirty_marker(index_dir, "clangd 21.1.1")
    finally:
        replacement_cache_lock.release()
        dirty_lease.release()
        old_cache_lock.release()


def test_unlinked_lock_path_cannot_split_api_and_builder(tmp_path: Path):
    index_dir = tmp_path / ".cache" / "clangd" / "index"
    write_index_engine_version(index_dir, "clangd 21.1.1")
    api_cache_lock = acquire_index_cache_lock(index_dir, exclusive=False)
    api_committed_lease = indexing_module.acquire_index_engine_lease(
        index_dir, exclusive=False
    )
    assert api_committed_lease is not None
    api_cache_lock.path.unlink()
    builder_cache_lock = acquire_index_cache_lock(index_dir, exclusive=True)
    try:
        with pytest.raises(ValueError, match="leased by an active user"):
            indexing_module.acquire_index_engine_lease(index_dir, exclusive=True)
    finally:
        builder_cache_lock.release()
        api_committed_lease.release()
        api_cache_lock.release()


def test_unlinked_lock_path_cannot_bypass_dirty_via_explicit_attestation(
    tmp_path: Path,
):
    source = tmp_path / "main.c"
    source.write_text("int main(void) { return 0; }\n", encoding="utf-8")
    write_cdb(tmp_path, [source])
    index_dir = index_dir_for_compile_commands_dir(tmp_path)
    touch_idx(index_dir, 1)
    old_cache_lock = acquire_index_cache_lock(index_dir, exclusive=True)
    dirty_lease = indexing_module._publish_dirty_marker(index_dir, "clangd 21.1.1")
    old_cache_lock.path.unlink()
    clangd = fake_clangd(tmp_path, "21.1.1")
    try:
        with pytest.raises(ValueError, match="dirty build marker"):
            write_index_engine_version(index_dir, "clangd 21.1.1")
        with pytest.raises(ValueError, match="dirty build marker"):
            stamp_existing_index(tmp_path, str(clangd))
        assert read_index_engine_version(index_dir) is None
    finally:
        dirty_lease.release()
        old_cache_lock.release()


def test_published_marker_keeps_lease_after_temp_name_cleanup(tmp_path: Path):
    index_dir = tmp_path / ".cache" / "clangd" / "index"
    lease = indexing_module._publish_dirty_marker(index_dir, "clangd 21.1.1")
    control_dir = index_dir.parent / ".codegraph-control"
    assert not tuple(control_dir.glob(".codegraph-marker-*.tmp"))
    try:
        with pytest.raises(ValueError, match="leased by an active user"):
            indexing_module._acquire_engine_marker_lease(
                index_engine_building_path(index_dir),
                exclusive=True,
                expected_version="clangd 21.1.1",
            )
    finally:
        lease.release()


def test_marker_lease_rejects_expected_version_mismatch(tmp_path: Path):
    index_dir = tmp_path / ".cache" / "clangd" / "index"
    write_index_engine_version(index_dir, "clangd 21.1.1")

    with pytest.raises(ValueError, match="belongs to clangd 21.1.1"):
        indexing_module._acquire_engine_marker_lease(
            index_engine_stamp_path(index_dir),
            exclusive=False,
            expected_version="clangd 22.1.8",
        )


def test_marker_publish_recovers_from_same_version_link_race(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    index_dir = tmp_path / ".cache" / "clangd" / "index"
    marker = index_engine_building_path(index_dir)
    raced = False

    def race_link(*args: object, **kwargs: object) -> None:
        nonlocal raced
        if not raced:
            raced = True
            marker.write_text("clangd 21.1.1\n", encoding="utf-8")
            raise FileExistsError(marker)
        raise AssertionError(f"unexpected second link call: {args!r} {kwargs!r}")

    monkeypatch.setattr(os, "link", race_link)
    lease = indexing_module._publish_dirty_marker(index_dir, "clangd 21.1.1")
    try:
        assert lease.version == "clangd 21.1.1"
    finally:
        lease.release()


def test_attestation_fails_if_dirty_appears_after_committed_lease(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    index_dir = tmp_path / "index"
    index_dir.mkdir()
    write_index_engine_version(index_dir, "clangd 21.1.1")
    reads = 0

    def appear_after_lease(_index_dir: str | Path) -> str | None:
        nonlocal reads
        reads += 1
        return None if reads == 1 else "clangd 21.1.1"

    monkeypatch.setattr(
        indexing_module, "read_index_building_version", appear_after_lease
    )
    with pytest.raises(ValueError, match="dirty marker appeared"):
        indexing_module._claim_index_attestation(index_dir, "clangd 21.1.1")

    lease = indexing_module.acquire_index_engine_lease(index_dir, exclusive=True)
    assert lease is not None
    lease.release()


def test_attestation_rolls_back_if_committed_appears_after_dirty_publish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    index_dir = tmp_path / "index"
    index_dir.mkdir()
    versions = iter((None, None, "clangd 21.1.1"))
    monkeypatch.setattr(
        indexing_module,
        "read_index_engine_version",
        lambda _index_dir: next(versions),
    )

    with pytest.raises(ValueError, match="committed marker appeared"):
        indexing_module._claim_index_attestation(index_dir, "clangd 21.1.1")

    assert not index_engine_building_path(index_dir).exists()


def test_attestation_rollback_never_removes_replaced_dirty_marker(tmp_path: Path):
    index_dir = tmp_path / "index"
    index_dir.mkdir()
    lease = indexing_module._publish_dirty_marker(index_dir, "clangd 21.1.1")
    marker = index_engine_building_path(index_dir)
    marker.unlink()
    marker.write_text("clangd 22.1.8\n", encoding="utf-8")
    try:
        indexing_module._rollback_attestation_dirty(lease)
        assert marker.read_text(encoding="utf-8") == "clangd 22.1.8\n"
    finally:
        lease.release()


def test_explicit_stamp_commit_io_failure_is_structured_and_rolls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    index_dir = tmp_path / "index"
    index_dir.mkdir()

    def fail_commit(*_args: object, **_kwargs: object) -> None:
        raise OSError("synthetic attestation commit failure")

    monkeypatch.setattr(indexing_module, "_commit_index_build", fail_commit)
    with pytest.raises(ValueError, match="cannot write index engine stamp") as exc_info:
        write_index_engine_version(index_dir, "clangd 21.1.1")

    assert exc_info.value.reason == "index_engine_stamp_write_failed"
    assert read_index_engine_version(index_dir) is None
    assert indexing_module.read_index_building_version(index_dir) is None


def test_verified_directory_detects_path_replacement(tmp_path: Path):
    directory = tmp_path / "cache"
    directory.mkdir()
    opened = indexing_module._open_verified_directory(directory)
    old_directory = tmp_path / "old-cache"
    directory.rename(old_directory)
    directory.mkdir()
    try:
        with pytest.raises(ValueError, match="pathname changed"):
            indexing_module._verify_directory_identity(opened)
    finally:
        opened.release()


def test_index_dir_verifier_allows_absent_path_only_without_creation(
    tmp_path: Path,
):
    indexing_module._verify_index_dir_is_real(tmp_path / "plain-index", create=False)
    (tmp_path / "managed").mkdir()
    indexing_module._verify_index_dir_is_real(
        tmp_path / "managed" / ".cache" / "clangd" / "index",
        create=False,
    )


def test_flock_survives_unlinked_temporary_name(tmp_path: Path):
    index_dir = tmp_path / "index"
    temporary = index_dir.parent / ".codegraph-control" / "lock-test.tmp"
    temporary.parent.mkdir(exist_ok=True)
    temporary.write_text("temporary", encoding="utf-8")
    owner_fd = os.open(temporary, os.O_RDONLY | os.O_NOFOLLOW)
    peer_fd = os.open(temporary, os.O_RDONLY | os.O_NOFOLLOW)
    fcntl.flock(owner_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    temporary.unlink()
    try:
        with pytest.raises(BlockingIOError):
            fcntl.flock(peer_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(owner_fd, fcntl.LOCK_UN)
        fcntl.flock(peer_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        fcntl.flock(peer_fd, fcntl.LOCK_UN)
        os.close(peer_fd)
        os.close(owner_fd)


def test_index_engine_stamp_rejects_invalid_version(tmp_path: Path):
    with pytest.raises(ValueError, match="invalid canonical clangd version"):
        write_index_engine_version(tmp_path / "index", "not-a-version")


@pytest.mark.parametrize(
    "content",
    [
        b"\xff\n",
        b"x" * 4097,
        b"CORRUPT prefix clangd 21.1.1 trailing clangd 22.1.8\n",
    ],
    ids=["invalid-utf8", "oversized", "noncanonical"],
)
@pytest.mark.parametrize("marker_kind", ["committed", "dirty"])
def test_index_engine_stamp_rejects_malformed_bytes(
    tmp_path: Path, content: bytes, marker_kind: str
):
    index_dir = tmp_path / "index"
    index_dir.mkdir()
    marker = (
        index_engine_stamp_path(index_dir)
        if marker_kind == "committed"
        else index_engine_building_path(index_dir)
    )
    marker.write_bytes(content)

    with pytest.raises(ValueError, match="invalid|too large"):
        (
            read_index_engine_version(index_dir)
            if marker_kind == "committed"
            else indexing_module.read_index_building_version(index_dir)
        )


def test_index_engine_stamp_publish_failure_cleans_stamp_and_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    index_dir = tmp_path / "index"

    def fail_identity_check(_path: Path, _expected: os.stat_result) -> None:
        raise OSError("synthetic post-link identity failure")

    monkeypatch.setattr(indexing_module, "_verify_marker_identity", fail_identity_check)

    with pytest.raises(ValueError, match="post-link identity failure"):
        write_index_engine_version(index_dir, "clangd 21.1.1")

    assert not index_engine_stamp_path(index_dir).exists()
    assert not tuple((index_dir.parent / ".codegraph-control").glob("*.tmp"))


def test_index_cache_lock_release_is_idempotent(tmp_path: Path):
    index_dir = tmp_path / "index"
    lock = acquire_index_cache_lock(index_dir, exclusive=True)

    lock.release()
    lock.release()

    assert lock.released is True


@pytest.mark.parametrize("marker_kind", ["committed", "dirty"])
@pytest.mark.parametrize("target_state", ["valid", "dangling"])
def test_index_engine_stamp_write_rejects_symlink(
    tmp_path: Path, target_state: str, marker_kind: str
):
    index_dir = tmp_path / "index"
    index_dir.mkdir()
    target = tmp_path / "outside-stamp"
    if target_state == "valid":
        target.write_text("clangd 21.1.1\n", encoding="utf-8")
    stamp = (
        index_engine_stamp_path(index_dir)
        if marker_kind == "committed"
        else index_engine_building_path(index_dir)
    )
    stamp.symlink_to(target)

    with pytest.raises(ValueError, match="invalid or unreadable"):
        write_index_engine_version(index_dir, "clangd 21.1.1")

    assert stamp.is_symlink()
    if target_state == "valid":
        assert target.read_text(encoding="utf-8") == "clangd 21.1.1\n"


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
    assert result.engine_version is not None
    assert read_index_engine_version(result.index_dir) == result.engine_version


def test_dirty_marker_prevents_complete_and_same_version_retry_commits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    source = tmp_path / "main.c"
    source.write_text("int main(void) { return 0; }\n", encoding="utf-8")
    write_cdb(tmp_path, [source])
    index_dir = index_dir_for_compile_commands_dir(tmp_path)
    attempts = 0

    class RetryClient:
        engine_version = "clangd 21.1.1"

        def __init__(self, _config: BackgroundIndexConfig):
            self.attempt = 0

        def initialize(self) -> None:
            return None

        def notify_initialized(self) -> None:
            return None

        def open_file(self, _file: str) -> None:
            nonlocal attempts
            attempts += 1
            self.attempt = attempts
            index_dir.mkdir(parents=True, exist_ok=True)
            (index_dir / f"attempt-{attempts}.idx").write_text(
                str(attempts), encoding="utf-8"
            )
            if attempts == 1:
                raise RuntimeError("synthetic graceful failure")

        def request_document_symbols(self, _file: str) -> None:
            return None

        def shutdown(self) -> None:
            return None

        def close(self) -> tuple[int, str]:
            return 0, ""

    monkeypatch.setattr("codegraph.indexing._IndexLspClient", RetryClient)
    config = BackgroundIndexConfig(
        compile_commands_dir=str(tmp_path),
        clangd_path=str(fake_clangd(tmp_path, "21.1.1")),
        max_wait_seconds=0.2,
        poll_interval_seconds=0.01,
        stable_rounds=1,
    )

    failed = run_background_index(config)
    dirty_health = evaluate_index_health(
        summarize_compile_commands(tmp_path),
        scan_index_shards(index_dir),
        expected_engine_version="clangd 21.1.1",
    )

    assert failed.health_report.reason == "index_build_failed"
    assert read_index_engine_version(index_dir) is None
    assert indexing_module.read_index_building_version(index_dir) == "clangd 21.1.1"
    assert dirty_health.health == IndexHealth.UNKNOWN
    assert dirty_health.reason == "index_engine_build_in_progress"

    succeeded = run_background_index(config)

    assert succeeded.health_report.health == IndexHealth.COMPLETE
    assert read_index_engine_version(index_dir) == "clangd 21.1.1"
    assert indexing_module.read_index_building_version(index_dir) is None
    assert {path.name for path in index_dir.glob("*.idx")} == {"attempt-2.idx"}


def test_committed_plus_dirty_same_version_is_not_complete_until_rebuilt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    source = tmp_path / "main.c"
    source.write_text("int main(void) { return 0; }\n", encoding="utf-8")
    write_cdb(tmp_path, [source])
    index_dir = index_dir_for_compile_commands_dir(tmp_path)
    touch_idx(index_dir, 1)
    index_engine_stamp_path(index_dir).write_text("clangd 21.1.1\n", encoding="utf-8")
    index_engine_building_path(index_dir).write_text(
        "clangd 21.1.1\n", encoding="utf-8"
    )
    before = evaluate_index_health(
        summarize_compile_commands(tmp_path),
        scan_index_shards(index_dir),
        expected_engine_version="clangd 21.1.1",
    )
    opened: list[str] = []
    install_barrier_index_client(
        monkeypatch, threading.Barrier(1), opened, threading.Lock()
    )

    result = run_background_index(
        BackgroundIndexConfig(
            compile_commands_dir=str(tmp_path),
            clangd_path=str(fake_clangd(tmp_path, "21.1.1")),
            max_wait_seconds=0.2,
            poll_interval_seconds=0.01,
            stable_rounds=1,
        )
    )

    assert before.health == IndexHealth.UNKNOWN
    assert before.reason == "index_engine_build_in_progress"
    assert result.health_report.health == IndexHealth.COMPLETE
    assert indexing_module.read_index_building_version(index_dir) is None
    assert opened == ["clangd 21.1.1"]


def test_sigkill_during_build_leaves_dirty_and_same_version_can_rebuild(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    source = tmp_path / "main.c"
    source.write_text("int main(void) { return 0; }\n", encoding="utf-8")
    write_cdb(tmp_path, [source])
    clangd = fake_clangd(tmp_path, "21.1.1")
    index_dir = index_dir_for_compile_commands_dir(tmp_path)
    child_code = f"""
import time
from pathlib import Path
import codegraph.indexing as indexing

index_dir = Path({str(index_dir)!r})

class SlowClient:
    engine_version = "clangd 21.1.1"
    def __init__(self, _config): pass
    def initialize(self): pass
    def notify_initialized(self): pass
    def open_file(self, _file):
        index_dir.mkdir(parents=True, exist_ok=True)
        (index_dir / "partial.idx").write_text("partial", encoding="utf-8")
        time.sleep(60)
    def request_document_symbols(self, _file): pass
    def shutdown(self): pass
    def close(self): return (0, "")

indexing._IndexLspClient = SlowClient
indexing.run_background_index(indexing.BackgroundIndexConfig(
    compile_commands_dir={str(tmp_path)!r},
    clangd_path={str(clangd)!r},
    max_wait_seconds=60,
))
"""
    proc = subprocess.Popen(
        [sys.executable, "-c", child_code],
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "PYTHONPATH": ".:tools"},
    )
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if (
            index_engine_building_path(index_dir).is_file()
            and (index_dir / "partial.idx").is_file()
        ):
            break
        time.sleep(0.02)
    else:
        proc.kill()
        proc.wait(timeout=5)
        pytest.fail("child did not reach dirty build state")
    proc.kill()
    proc.wait(timeout=5)

    after_kill = evaluate_index_health(
        summarize_compile_commands(tmp_path),
        scan_index_shards(index_dir),
        expected_engine_version="clangd 21.1.1",
    )

    assert proc.returncode == -9
    assert after_kill.health == IndexHealth.UNKNOWN
    assert after_kill.reason == "index_engine_build_in_progress"
    assert read_index_engine_version(index_dir) is None

    opened: list[str] = []
    install_barrier_index_client(
        monkeypatch, threading.Barrier(1), opened, threading.Lock()
    )
    rebuilt = run_background_index(
        BackgroundIndexConfig(
            compile_commands_dir=str(tmp_path),
            clangd_path=str(clangd),
            max_wait_seconds=0.2,
            poll_interval_seconds=0.01,
            stable_rounds=1,
        )
    )

    assert rebuilt.health_report.health == IndexHealth.COMPLETE
    assert read_index_engine_version(index_dir) == "clangd 21.1.1"
    assert indexing_module.read_index_building_version(index_dir) is None
    assert not (index_dir / "partial.idx").exists()


def test_dirty_publish_failure_does_not_send_initialized_notification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    source = tmp_path / "main.c"
    source.write_text("int main(void) { return 0; }\n", encoding="utf-8")
    write_cdb(tmp_path, [source])
    events: list[str] = []

    class OrderedClient:
        engine_version = "clangd 21.1.1"

        def __init__(self, _config: BackgroundIndexConfig):
            return None

        def initialize(self) -> None:
            events.append("initialize")

        def notify_initialized(self) -> None:
            events.append("initialized")

        def open_file(self, _file: str) -> None:
            events.append("open")

        def shutdown(self) -> None:
            events.append("shutdown")

        def close(self) -> tuple[int, str]:
            return 0, ""

    def reject_dirty(_index_dir: Path, _engine_version: str) -> None:
        raise indexing_module._IndexEngineStampError(
            "index_engine_mismatch", "synthetic ownership rejection"
        )

    monkeypatch.setattr("codegraph.indexing._IndexLspClient", OrderedClient)
    monkeypatch.setattr("codegraph.indexing._publish_dirty_marker", reject_dirty)

    result = run_background_index(
        BackgroundIndexConfig(
            compile_commands_dir=str(tmp_path),
            clangd_path=str(fake_clangd(tmp_path, "21.1.1")),
        )
    )

    assert result.health_report.reason == "index_engine_mismatch"
    assert events == ["initialize", "shutdown"]


def test_shard_cleanup_failure_retains_dirty_and_skips_initialized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    source = tmp_path / "main.c"
    source.write_text("int main(void) { return 0; }\n", encoding="utf-8")
    write_cdb(tmp_path, [source])
    events: list[str] = []

    class OrderedClient:
        engine_version = "clangd 21.1.1"

        def __init__(self, _config: BackgroundIndexConfig):
            return None

        def initialize(self) -> None:
            events.append("initialize")

        def notify_initialized(self) -> None:
            events.append("initialized")

        def open_file(self, _file: str) -> None:
            events.append("open")

        def shutdown(self) -> None:
            events.append("shutdown")

        def close(self) -> tuple[int, str]:
            return 0, ""

    def reject_cleanup(_index_dir: Path) -> None:
        raise PermissionError("cannot clear")

    monkeypatch.setattr("codegraph.indexing._IndexLspClient", OrderedClient)
    monkeypatch.setattr("codegraph.indexing._clear_index_shards", reject_cleanup)

    result = run_background_index(
        BackgroundIndexConfig(
            compile_commands_dir=str(tmp_path),
            clangd_path=str(fake_clangd(tmp_path, "21.1.1")),
        )
    )

    index_dir = index_dir_for_compile_commands_dir(tmp_path)
    assert result.health_report.reason == "index_health_error"
    assert indexing_module.read_index_building_version(index_dir) == "clangd 21.1.1"
    assert events == ["initialize", "shutdown"]


def test_commit_failure_keeps_dirty_marker_and_never_reports_complete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    source = tmp_path / "main.c"
    source.write_text("int main(void) { return 0; }\n", encoding="utf-8")
    write_cdb(tmp_path, [source])
    opened: list[str] = []
    install_barrier_index_client(
        monkeypatch, threading.Barrier(1), opened, threading.Lock()
    )

    def reject_commit(
        _index_dir: Path, _engine_version: str | None, **_kwargs: object
    ) -> None:
        raise indexing_module._IndexEngineStampError(
            "index_engine_version_inconsistent", "synthetic commit failure"
        )

    monkeypatch.setattr("codegraph.indexing._commit_index_build", reject_commit)

    result = run_background_index(
        BackgroundIndexConfig(
            compile_commands_dir=str(tmp_path),
            clangd_path=str(fake_clangd(tmp_path, "21.1.1")),
            max_wait_seconds=0.2,
            poll_interval_seconds=0.01,
            stable_rounds=1,
        )
    )

    index_dir = index_dir_for_compile_commands_dir(tmp_path)
    assert result.health_report.health == IndexHealth.UNKNOWN
    assert result.health_report.reason == "index_engine_version_inconsistent"
    assert read_index_engine_version(index_dir) is None
    assert indexing_module.read_index_building_version(index_dir) == "clangd 21.1.1"


def test_commit_io_failure_is_structured_and_keeps_dirty_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    source = tmp_path / "main.c"
    source.write_text("int main(void) { return 0; }\n", encoding="utf-8")
    write_cdb(tmp_path, [source])
    opened: list[str] = []
    install_barrier_index_client(
        monkeypatch, threading.Barrier(1), opened, threading.Lock()
    )

    def reject_commit(
        _index_dir: Path, _engine_version: str | None, **_kwargs: object
    ) -> None:
        raise OSError("synthetic commit I/O failure")

    monkeypatch.setattr("codegraph.indexing._commit_index_build", reject_commit)

    result = run_background_index(
        BackgroundIndexConfig(
            compile_commands_dir=str(tmp_path),
            clangd_path=str(fake_clangd(tmp_path, "21.1.1")),
            max_wait_seconds=0.2,
            poll_interval_seconds=0.01,
            stable_rounds=1,
        )
    )

    index_dir = index_dir_for_compile_commands_dir(tmp_path)
    assert result.health_report.health == IndexHealth.UNKNOWN
    assert result.health_report.reason == "index_engine_stamp_write_failed"
    assert "synthetic commit I/O failure" in result.stderr_tail
    assert read_index_engine_version(index_dir) is None
    assert indexing_module.read_index_building_version(index_dir) == "clangd 21.1.1"


def test_dirty_and_commit_helpers_fail_closed_on_impossible_states(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    index_dir = tmp_path / "index"
    index_dir.mkdir()

    with pytest.raises(ValueError, match="without engine version"):
        indexing_module._commit_index_build(index_dir, None)
    with pytest.raises(ValueError, match="dirty marker missing before commit"):
        indexing_module._commit_index_build(index_dir, "clangd 21.1.1")

    index_engine_stamp_path(index_dir).write_text("clangd 21.1.1\n", encoding="utf-8")
    index_engine_building_path(index_dir).write_text(
        "clangd 22.1.8\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="dirty and committed.*disagree"):
        indexing_module._publish_dirty_marker(index_dir, "clangd 21.1.1")

    index_engine_stamp_path(index_dir).unlink()
    with pytest.raises(ValueError, match="belongs to clangd 22.1.8"):
        indexing_module._publish_dirty_marker(index_dir, "clangd 21.1.1")

    index_engine_building_path(index_dir).write_text(
        "clangd 21.1.1\n", encoding="utf-8"
    )
    dirty_lease = indexing_module._publish_dirty_marker(index_dir, "clangd 21.1.1")
    index_engine_building_path(index_dir).unlink()
    index_engine_building_path(index_dir).write_text(
        "clangd 21.1.1\n", encoding="utf-8"
    )
    try:
        with pytest.raises(ValueError, match="dirty marker changed during commit"):
            indexing_module._commit_index_build(
                index_dir, "clangd 21.1.1", dirty_lease=dirty_lease
            )
    finally:
        dirty_lease.release()

    indexing_module._clear_index_shards(tmp_path / "missing-index")


def test_invalid_control_directory_blocks_before_client_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    source = tmp_path / "main.c"
    source.write_text("int main(void) { return 0; }\n", encoding="utf-8")
    write_cdb(tmp_path, [source])
    index_dir = index_dir_for_compile_commands_dir(tmp_path)
    control = index_dir.parent / ".codegraph-control"
    control.parent.mkdir(parents=True)
    control.write_text("not a directory", encoding="utf-8")
    started = False

    def reject_start(_config: object) -> object:
        nonlocal started
        started = True
        raise AssertionError("invalid control path must block before clangd starts")

    monkeypatch.setattr("codegraph.indexing._IndexLspClient", reject_start)

    result = run_background_index(
        BackgroundIndexConfig(
            compile_commands_dir=str(tmp_path),
            clangd_path=str(fake_clangd(tmp_path, "21.1.1")),
        )
    )

    assert result.health_report.reason == "index_health_error"
    assert started is False


@pytest.mark.parametrize("dangling", [False, True])
def test_control_directory_symlink_blocks_marker_publish(
    tmp_path: Path, dangling: bool
):
    index_dir = tmp_path / ".cache" / "clangd" / "index"
    index_dir.mkdir(parents=True)
    control = index_dir.parent / ".codegraph-control"
    target = tmp_path / "outside-control"
    if not dangling:
        target.mkdir()
    control.symlink_to(target, target_is_directory=True)
    outside_before = tuple(target.iterdir()) if target.exists() else ()

    with pytest.raises(ValueError):
        write_index_engine_version(index_dir, "clangd 21.1.1")

    assert (tuple(target.iterdir()) if target.exists() else ()) == outside_before
    assert read_index_engine_version(index_dir) is None


def test_index_directory_symlink_blocks_before_client_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    source = tmp_path / "main.c"
    source.write_text("int main(void) { return 0; }\n", encoding="utf-8")
    write_cdb(tmp_path, [source])
    external = tmp_path / "outside-index"
    external.mkdir()
    clangd_cache = tmp_path / ".cache" / "clangd"
    clangd_cache.mkdir(parents=True)
    (clangd_cache / "index").symlink_to(external, target_is_directory=True)
    before = tuple(external.iterdir())
    started = False

    def reject_start(_config: object) -> object:
        nonlocal started
        started = True
        raise AssertionError("index symlink must block before clangd starts")

    monkeypatch.setattr("codegraph.indexing._IndexLspClient", reject_start)
    result = run_background_index(
        BackgroundIndexConfig(
            compile_commands_dir=str(tmp_path),
            clangd_path=str(fake_clangd(tmp_path, "21.1.1")),
        )
    )

    assert started is False
    assert result.health_report.reason == "index_health_error"
    assert tuple(external.iterdir()) == before


def test_index_directory_symlink_blocks_explicit_attestation(tmp_path: Path):
    source = tmp_path / "main.c"
    source.write_text("int main(void) { return 0; }\n", encoding="utf-8")
    write_cdb(tmp_path, [source])
    external = tmp_path / "outside-index"
    touch_idx(external, 1)
    clangd_cache = tmp_path / ".cache" / "clangd"
    clangd_cache.mkdir(parents=True)
    (clangd_cache / "index").symlink_to(external, target_is_directory=True)
    before = {path.name: path.read_bytes() for path in external.iterdir()}

    with pytest.raises(ValueError, match="cache directory is invalid"):
        stamp_existing_index(tmp_path, str(fake_clangd(tmp_path, "21.1.1")))

    assert {path.name: path.read_bytes() for path in external.iterdir()} == before


def test_stale_control_temp_is_outside_shard_scan_and_cleaned_before_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    source = tmp_path / "main.c"
    source.write_text("int main(void) { return 0; }\n", encoding="utf-8")
    write_cdb(tmp_path, [source])
    index_dir = index_dir_for_compile_commands_dir(tmp_path)
    control_dir = index_dir.parent / ".codegraph-control"
    control_dir.mkdir(parents=True)
    stale = control_dir / ".codegraph-marker-stale.tmp"
    stale.write_text("stale", encoding="utf-8")
    before = scan_index_shards(index_dir)
    opened: list[str] = []
    install_barrier_index_client(
        monkeypatch, threading.Barrier(1), opened, threading.Lock()
    )

    result = run_background_index(
        BackgroundIndexConfig(
            compile_commands_dir=str(tmp_path),
            clangd_path=str(fake_clangd(tmp_path, "21.1.1")),
            max_wait_seconds=0.2,
            poll_interval_seconds=0.01,
            stable_rounds=1,
        )
    )

    assert before.total_files == 0
    assert not stale.exists()
    assert result.health_report.health == IndexHealth.COMPLETE


def test_different_version_builders_claim_before_any_index_side_effect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    source = tmp_path / "main.c"
    source.write_text("int main(void) { return 0; }\n", encoding="utf-8")
    write_cdb(tmp_path, [source])
    barrier = threading.Barrier(2)
    opened_versions: list[str] = []
    opened_lock = threading.Lock()
    install_probe_barrier(monkeypatch, barrier)
    install_barrier_index_client(monkeypatch, barrier, opened_versions, opened_lock)
    configs = tuple(
        BackgroundIndexConfig(
            compile_commands_dir=str(tmp_path),
            clangd_path=str(fake_clangd(tmp_path, version)),
            max_wait_seconds=1,
            poll_interval_seconds=0.01,
            stable_rounds=1,
        )
        for version in ("21.1.1", "22.1.8")
    )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(run_background_index, configs))

    reasons = {result.health_report.reason for result in results}
    assert reasons == {"shards_ge_unique_tu", "index_engine_build_in_progress"}
    assert len(opened_versions) == 1
    index_dir = index_dir_for_compile_commands_dir(tmp_path)
    assert read_index_engine_version(index_dir) == opened_versions[0]
    shard_versions = {
        path.read_text(encoding="utf-8") for path in index_dir.glob("*.idx")
    }
    assert shard_versions == {opened_versions[0]}


def test_same_version_builders_are_serialized_by_cache_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    source = tmp_path / "main.c"
    source.write_text("int main(void) { return 0; }\n", encoding="utf-8")
    write_cdb(tmp_path, [source])
    barrier = threading.Barrier(2)
    opened_versions: list[str] = []
    opened_lock = threading.Lock()
    install_probe_barrier(monkeypatch, barrier)
    install_barrier_index_client(monkeypatch, barrier, opened_versions, opened_lock)
    clangd = fake_clangd(tmp_path, "21.1.1")
    configs = tuple(
        BackgroundIndexConfig(
            compile_commands_dir=str(tmp_path),
            clangd_path=str(clangd),
            max_wait_seconds=1,
            poll_interval_seconds=0.01,
            stable_rounds=1,
        )
        for _ in range(2)
    )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(run_background_index, configs))

    reasons = {result.health_report.reason for result in results}
    assert reasons == {"shards_ge_unique_tu", "index_engine_build_in_progress"}
    assert opened_versions == ["clangd 21.1.1"]
    assert (
        read_index_engine_version(index_dir_for_compile_commands_dir(tmp_path))
        == "clangd 21.1.1"
    )


def test_failed_builder_retains_dirty_and_blocks_other_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    source = tmp_path / "main.c"
    source.write_text("int main(void) { return 0; }\n", encoding="utf-8")
    write_cdb(tmp_path, [source])
    barrier = threading.Barrier(2)
    opened_versions: list[str] = []
    opened_lock = threading.Lock()
    install_probe_barrier(monkeypatch, barrier)
    install_barrier_index_client(
        monkeypatch,
        barrier,
        opened_versions,
        opened_lock,
        fail_after_open=True,
    )
    configs = tuple(
        BackgroundIndexConfig(
            compile_commands_dir=str(tmp_path),
            clangd_path=str(fake_clangd(tmp_path, version)),
            max_wait_seconds=0.1,
            poll_interval_seconds=0.01,
            stable_rounds=1,
        )
        for version in ("21.1.1", "22.1.8")
    )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(run_background_index, configs))

    reasons = {result.health_report.reason for result in results}
    assert reasons == {"index_build_failed", "index_engine_build_in_progress"}
    assert len(opened_versions) == 1
    index_dir = index_dir_for_compile_commands_dir(tmp_path)
    assert read_index_engine_version(index_dir) is None
    assert indexing_module.read_index_building_version(index_dir) == opened_versions[0]
    assert {path.read_text(encoding="utf-8") for path in index_dir.glob("*.idx")} == {
        opened_versions[0]
    }


def test_dirty_and_committed_version_disagreement_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    source = tmp_path / "main.c"
    source.write_text("int main(void) { return 0; }\n", encoding="utf-8")
    write_cdb(tmp_path, [source])
    index_dir = index_dir_for_compile_commands_dir(tmp_path)
    touch_idx(index_dir, 1)
    index_engine_stamp_path(index_dir).write_text("clangd 21.1.1\n", encoding="utf-8")
    index_engine_building_path(index_dir).write_text(
        "clangd 22.1.8\n", encoding="utf-8"
    )

    report = evaluate_index_health(
        summarize_compile_commands(tmp_path),
        scan_index_shards(index_dir),
        expected_engine_version="clangd 21.1.1",
    )
    started = False

    def reject_start(_config: object) -> object:
        nonlocal started
        started = True
        raise AssertionError("inconsistent ownership must block before clangd starts")

    monkeypatch.setattr("codegraph.indexing._IndexLspClient", reject_start)
    build = run_background_index(
        BackgroundIndexConfig(
            compile_commands_dir=str(tmp_path),
            clangd_path=str(fake_clangd(tmp_path, "21.1.1")),
        )
    )

    assert report.health == IndexHealth.UNKNOWN
    assert report.reason == "index_engine_version_inconsistent"
    assert build.health_report.reason == "index_engine_version_inconsistent"
    assert started is False


def test_stamp_identity_check_rejects_replaced_path(tmp_path: Path):
    index_dir = tmp_path / "index"
    stamp = write_index_engine_version(index_dir, "clangd 21.1.1")
    original_stat = os.lstat(stamp)
    replacement = index_dir / "replacement"
    replacement.write_text("clangd 21.1.1\n", encoding="utf-8")
    os.replace(replacement, stamp)

    with pytest.raises(ValueError, match="changed while claiming"):
        indexing_module._verify_stamp_identity(stamp, original_stat)


@pytest.mark.parametrize(
    ("existing_stamp", "expected_reason"),
    [
        (True, "index_engine_mismatch"),
        (False, "index_engine_version_inconsistent"),
    ],
)
def test_background_index_rechecks_lsp_version_before_opening_tu(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    existing_stamp: bool,
    expected_reason: str,
):
    real_clangd = shutil.which("clangd")
    if real_clangd is None:
        pytest.skip("clangd is not installed")
    source = tmp_path / "main.c"
    source.write_text("int main(void) { return 0; }\n", encoding="utf-8")
    write_cdb(tmp_path, [source])
    index_dir = index_dir_for_compile_commands_dir(tmp_path)
    stamp = index_engine_stamp_path(index_dir)
    if existing_stamp:
        write_index_engine_version(index_dir, "clangd 99.99.99")
    stamp_before = stamp.read_bytes() if stamp.is_file() else None
    wrapper = tmp_path / "clangd-version-liar"
    wrapper.write_text(
        "#!/bin/sh\n"
        'if [ "$#" -eq 1 ] && [ "$1" = "--version" ]; then\n'
        "  echo 'clangd version 99.99.99'\n"
        "  exit 0\n"
        "fi\n"
        f'exec {shlex.quote(real_clangd)} "$@"\n',
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    opened_files: list[str] = []

    def reject_open(_client: object, file: str) -> None:
        opened_files.append(file)
        raise AssertionError("ownership must be checked before opening a TU")

    monkeypatch.setattr("codegraph.indexing._IndexLspClient.open_file", reject_open)

    result = run_background_index(
        BackgroundIndexConfig(
            compile_commands_dir=str(tmp_path),
            clangd_path=str(wrapper),
            max_wait_seconds=0.1,
            poll_interval_seconds=0.01,
            stable_rounds=1,
        )
    )
    stamp_after = stamp.read_bytes() if stamp.is_file() else None
    ownership_overwritten = stamp_before != stamp_after

    assert result.stable is False
    assert result.health_report.reason == expected_reason
    if existing_stamp:
        assert result.health_report.index_engine_version == "clangd 99.99.99"
    assert result.engine_version != "clangd 99.99.99"
    assert opened_files == []
    assert ownership_overwritten is False


def test_background_index_dirty_publish_failure_is_structured_before_opening_tu(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    source = tmp_path / "main.c"
    source.write_text("int main(void) { return 0; }\n", encoding="utf-8")
    write_cdb(tmp_path, [source])
    opened_files: list[str] = []

    class FakeClient:
        engine_version = "clangd 21.1.1"

        def __init__(self, _config: BackgroundIndexConfig):
            return None

        def initialize(self) -> None:
            return None

        def notify_initialized(self) -> None:
            return None

        def open_file(self, file: str) -> None:
            opened_files.append(file)

        def shutdown(self) -> None:
            return None

        def close(self) -> tuple[int, str]:
            return 0, ""

    def fail_claim(_index_dir: object, _engine_version: str) -> object:
        raise PermissionError("stamp parent is not writable")

    monkeypatch.setattr("codegraph.indexing._IndexLspClient", FakeClient)
    monkeypatch.setattr("codegraph.indexing._publish_dirty_marker", fail_claim)

    result = run_background_index(
        BackgroundIndexConfig(
            compile_commands_dir=str(tmp_path),
            clangd_path=str(fake_clangd(tmp_path, "21.1.1")),
        )
    )

    assert result.health_report.health == IndexHealth.UNKNOWN
    assert result.health_report.reason == "index_engine_stamp_write_failed"
    assert opened_files == []
    assert "PermissionError" in result.stderr_tail


def test_background_index_does_not_auto_claim_unstamped_existing_cache(
    tmp_path: Path,
):
    source = tmp_path / "main.c"
    source.write_text("int main(void) { return 0; }\n", encoding="utf-8")
    write_cdb(tmp_path, [source])
    touch_idx(index_dir_for_compile_commands_dir(tmp_path), 1)

    result = run_background_index(
        BackgroundIndexConfig(
            compile_commands_dir=str(tmp_path),
            clangd_path=str(fake_clangd(tmp_path)),
        )
    )

    assert result.exit_code is None
    assert result.stable is False
    assert result.health_report.health == IndexHealth.UNKNOWN
    assert result.health_report.reason == "index_engine_unverified"
    assert read_index_engine_version(result.index_dir) is None


def test_mismatched_stamp_blocks_with_zero_idx(tmp_path: Path):
    source = tmp_path / "main.c"
    source.write_text("int main(void) { return 0; }\n", encoding="utf-8")
    write_cdb(tmp_path, [source])
    index_dir = index_dir_for_compile_commands_dir(tmp_path)
    write_index_engine_version(index_dir, "clangd 18.1.3")

    result = run_background_index(
        BackgroundIndexConfig(
            compile_commands_dir=str(tmp_path),
            clangd_path=str(fake_clangd(tmp_path, "21.1.1")),
        )
    )

    assert result.exit_code is None
    assert result.stable is False
    assert result.health_report.health == IndexHealth.UNKNOWN
    assert result.health_report.reason == "index_engine_mismatch"
    assert result.shard_report.idx_shards == 0
    assert read_index_engine_version(index_dir) == "clangd 18.1.3"


def test_unstamped_non_idx_cache_is_not_auto_claimed(tmp_path: Path):
    source = tmp_path / "main.c"
    source.write_text("int main(void) { return 0; }\n", encoding="utf-8")
    write_cdb(tmp_path, [source])
    index_dir = index_dir_for_compile_commands_dir(tmp_path)
    index_dir.mkdir(parents=True)
    marker = index_dir / "partial.tmp"
    marker.write_text("partial", encoding="utf-8")

    result = run_background_index(
        BackgroundIndexConfig(
            compile_commands_dir=str(tmp_path),
            clangd_path=str(fake_clangd(tmp_path, "21.1.1")),
        )
    )

    assert result.exit_code is None
    assert result.stable is False
    assert result.health_report.health == IndexHealth.UNKNOWN
    assert result.health_report.reason == "index_engine_unverified"
    assert marker.read_text(encoding="utf-8") == "partial"
    assert read_index_engine_version(index_dir) is None


@pytest.mark.parametrize(
    "stamp_state",
    ["invalid", "directory", "unreadable", "valid_symlink", "dangling_symlink"],
)
@pytest.mark.parametrize("marker_kind", ["committed", "dirty"])
def test_invalid_engine_stamp_blocks_background_index_start(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stamp_state: str,
    marker_kind: str,
):
    source = tmp_path / "main.c"
    source.write_text("int main(void) { return 0; }\n", encoding="utf-8")
    write_cdb(tmp_path, [source])
    index_dir = index_dir_for_compile_commands_dir(tmp_path)
    index_dir.mkdir(parents=True)
    stamp = (
        index_engine_stamp_path(index_dir)
        if marker_kind == "committed"
        else index_engine_building_path(index_dir)
    )
    if stamp_state == "directory":
        stamp.mkdir()
    elif stamp_state in {"valid_symlink", "dangling_symlink"}:
        target = tmp_path / "outside-stamp"
        if stamp_state == "valid_symlink":
            target.write_text("clangd 21.1.1\n", encoding="utf-8")
        stamp.symlink_to(target)
    else:
        stamp.write_text("not-a-clangd-version\n", encoding="utf-8")
    if stamp_state == "unreadable":
        original_open_stamp = indexing_module._open_engine_marker

        def deny_stamp_read(path: Path) -> tuple[int, os.stat_result] | None:
            if path == stamp:
                raise PermissionError(f"permission denied: {path}")
            return original_open_stamp(path)

        monkeypatch.setattr(indexing_module, "_open_engine_marker", deny_stamp_read)
    client_started = False

    def fail_if_started(_config: object) -> object:
        nonlocal client_started
        client_started = True
        raise AssertionError("invalid stamp must block before clangd starts")

    monkeypatch.setattr("codegraph.indexing._IndexLspClient", fail_if_started)

    result = run_background_index(
        BackgroundIndexConfig(
            compile_commands_dir=str(tmp_path),
            clangd_path=str(fake_clangd(tmp_path, "21.1.1")),
        )
    )

    assert client_started is False
    assert result.exit_code is None
    assert result.stable is False
    assert result.health_report.health == IndexHealth.UNKNOWN
    assert result.health_report.reason == "index_engine_stamp_invalid"


def test_unreadable_index_directory_blocks_background_index_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    source = tmp_path / "main.c"
    source.write_text("int main(void) { return 0; }\n", encoding="utf-8")
    write_cdb(tmp_path, [source])
    index_dir = index_dir_for_compile_commands_dir(tmp_path)
    index_dir.mkdir(parents=True)
    (index_dir / "partial.idx").write_text("partial", encoding="utf-8")
    index_dir.chmod(0)
    client_started = False

    def fail_if_started(_config: object) -> object:
        nonlocal client_started
        client_started = True
        raise AssertionError("unreadable index directory must block client startup")

    monkeypatch.setattr("codegraph.indexing._IndexLspClient", fail_if_started)
    try:
        result = run_background_index(
            BackgroundIndexConfig(
                compile_commands_dir=str(tmp_path),
                clangd_path=str(fake_clangd(tmp_path, "21.1.1")),
            )
        )
    finally:
        index_dir.chmod(0o700)

    assert client_started is False
    assert result.health_report.health == IndexHealth.UNKNOWN
    assert result.health_report.reason == "index_health_error"
    assert "PermissionError" in result.stderr_tail


def test_stamp_existing_index_requires_health_and_rejects_conflicts(tmp_path: Path):
    source = tmp_path / "main.c"
    source.write_text("int main(void) { return 0; }\n", encoding="utf-8")
    write_cdb(tmp_path, [source])
    index_dir = index_dir_for_compile_commands_dir(tmp_path)
    touch_idx(index_dir, 1)
    clangd_21 = fake_clangd(tmp_path, "21.1.1")

    report = stamp_existing_index(tmp_path, str(clangd_21))

    assert report.health == IndexHealth.COMPLETE
    assert read_index_engine_version(index_dir) == "clangd 21.1.1"
    clangd_22 = fake_clangd(tmp_path, "22.1.8")
    with pytest.raises(ValueError, match="conflicting index engine"):
        stamp_existing_index(tmp_path, str(clangd_22))


def test_stamp_existing_index_rejects_dirty_cache(tmp_path: Path):
    source = tmp_path / "main.c"
    source.write_text("int main(void) { return 0; }\n", encoding="utf-8")
    write_cdb(tmp_path, [source])
    index_dir = index_dir_for_compile_commands_dir(tmp_path)
    touch_idx(index_dir, 1)
    index_engine_building_path(index_dir).write_text(
        "clangd 21.1.1\n", encoding="utf-8"
    )

    with pytest.raises(ValueError, match="dirty build marker"):
        stamp_existing_index(tmp_path, str(fake_clangd(tmp_path, "21.1.1")))

    assert read_index_engine_version(index_dir) is None


def test_stamp_existing_index_rejects_incomplete_cache_and_unknown_engine(
    tmp_path: Path,
):
    source = tmp_path / "main.c"
    source.write_text("int main(void) { return 0; }\n", encoding="utf-8")
    write_cdb(tmp_path, [source])

    with pytest.raises(ValueError, match="cannot stamp index"):
        stamp_existing_index(tmp_path, str(fake_clangd(tmp_path, "21.1.1")))

    touch_idx(index_dir_for_compile_commands_dir(tmp_path), 1)
    with pytest.raises(ValueError, match="cannot detect clangd version"):
        stamp_existing_index(tmp_path, str(tmp_path / "missing-clangd"))


def test_stamp_existing_index_rejects_symlink_stamp(tmp_path: Path):
    source = tmp_path / "main.c"
    source.write_text("int main(void) { return 0; }\n", encoding="utf-8")
    write_cdb(tmp_path, [source])
    index_dir = index_dir_for_compile_commands_dir(tmp_path)
    touch_idx(index_dir, 1)
    target = tmp_path / "outside-stamp"
    target.write_text("clangd 21.1.1\n", encoding="utf-8")
    index_engine_stamp_path(index_dir).symlink_to(target)

    with pytest.raises(ValueError, match="invalid or unreadable"):
        stamp_existing_index(tmp_path, str(fake_clangd(tmp_path, "21.1.1")))


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
    index_dir = index_dir_for_compile_commands_dir(tmp_path)
    touch_idx(index_dir, 1)
    clangd = fake_clangd(tmp_path)
    write_index_engine_version(index_dir, "clangd 18.1.3")

    completed = subprocess.run(
        [
            sys.executable,
            "tools/build_index.py",
            "--compile-commands-dir",
            str(tmp_path),
            "--inspect-only",
            "--clangd",
            str(clangd),
        ],
        cwd=Path(__file__).resolve().parents[1],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    payload = json.loads(completed.stdout)

    assert payload["health"]["health"] == IndexHealth.COMPLETE
    assert payload["health"]["idx_shards"] == 1


def test_build_index_cli_inspect_missing_clangd_reports_engine_unavailable(
    tmp_path: Path,
):
    source = tmp_path / "main.c"
    source.write_text("int main(void) { return 0; }\n", encoding="utf-8")
    write_cdb(tmp_path, [source])
    index_dir = index_dir_for_compile_commands_dir(tmp_path)
    touch_idx(index_dir, 1)
    write_index_engine_version(index_dir, "clangd 18.1.3")

    completed = subprocess.run(
        [
            sys.executable,
            "tools/build_index.py",
            "--compile-commands-dir",
            str(tmp_path),
            "--inspect-only",
            "--clangd",
            str(tmp_path / "missing-clangd"),
        ],
        cwd=Path(__file__).resolve().parents[1],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    payload = json.loads(completed.stdout)

    assert completed.returncode == 1
    assert payload["health"]["health"] == IndexHealth.UNKNOWN
    assert payload["health"]["reason"] == "index_engine_unavailable"
    assert payload["health"]["index_engine_version"] == "clangd 18.1.3"
    assert "error" not in payload
    assert "Traceback" not in completed.stderr


@pytest.mark.parametrize("stamp_existing", [False, True])
def test_build_index_cli_invalid_stamp_reports_structured_block(
    tmp_path: Path, stamp_existing: bool
):
    source = tmp_path / "main.c"
    source.write_text("int main(void) { return 0; }\n", encoding="utf-8")
    write_cdb(tmp_path, [source])
    index_dir = index_dir_for_compile_commands_dir(tmp_path)
    touch_idx(index_dir, 1)
    index_engine_stamp_path(index_dir).write_text(
        "not-a-clangd-version\n", encoding="utf-8"
    )

    command = [
        sys.executable,
        "tools/build_index.py",
        "--compile-commands-dir",
        str(tmp_path),
        "--inspect-only",
        "--clangd",
        str(fake_clangd(tmp_path, "21.1.1")),
    ]
    if stamp_existing:
        command.append("--stamp-existing-index")
    completed = subprocess.run(
        command,
        cwd=Path(__file__).resolve().parents[1],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    payload = json.loads(completed.stdout)

    assert completed.returncode == 1
    if stamp_existing:
        assert payload["health"] == IndexHealth.UNKNOWN
        assert payload["reason"] == "index_engine_stamp_invalid"
    else:
        assert payload["health"]["health"] == IndexHealth.UNKNOWN
        assert payload["health"]["reason"] == "index_engine_stamp_invalid"
    assert "Traceback" not in completed.stderr


@pytest.mark.parametrize("target_state", ["valid", "dangling"])
@pytest.mark.parametrize("marker_kind", ["committed", "dirty"])
def test_build_index_cli_rejects_symlink_engine_stamp(
    tmp_path: Path, target_state: str, marker_kind: str
):
    source = tmp_path / "main.c"
    source.write_text("int main(void) { return 0; }\n", encoding="utf-8")
    write_cdb(tmp_path, [source])
    index_dir = index_dir_for_compile_commands_dir(tmp_path)
    touch_idx(index_dir, 1)
    target = tmp_path / "outside-stamp"
    if target_state == "valid":
        target.write_text("clangd 21.1.1\n", encoding="utf-8")
    marker = (
        index_engine_stamp_path(index_dir)
        if marker_kind == "committed"
        else index_engine_building_path(index_dir)
    )
    marker.symlink_to(target)

    completed = subprocess.run(
        [
            sys.executable,
            "tools/build_index.py",
            "--compile-commands-dir",
            str(tmp_path),
            "--inspect-only",
            "--clangd",
            str(fake_clangd(tmp_path, "21.1.1")),
        ],
        cwd=Path(__file__).resolve().parents[1],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    payload = json.loads(completed.stdout)

    assert completed.returncode == 1
    assert payload["health"]["reason"] == "index_engine_stamp_invalid"
    assert "Traceback" not in completed.stderr


def test_build_index_cli_stamp_write_permission_error_is_structured(tmp_path: Path):
    source = tmp_path / "main.c"
    source.write_text("int main(void) { return 0; }\n", encoding="utf-8")
    write_cdb(tmp_path, [source])
    index_dir = index_dir_for_compile_commands_dir(tmp_path)
    touch_idx(index_dir, 1)
    index_dir.chmod(0o555)
    try:
        completed = subprocess.run(
            [
                sys.executable,
                "tools/build_index.py",
                "--compile-commands-dir",
                str(tmp_path),
                "--inspect-only",
                "--stamp-existing-index",
                "--clangd",
                str(fake_clangd(tmp_path, "21.1.1")),
            ],
            cwd=Path(__file__).resolve().parents[1],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    finally:
        index_dir.chmod(0o700)
    payload = json.loads(completed.stdout)

    assert completed.returncode == 1
    assert payload["health"] == IndexHealth.UNKNOWN
    assert payload["reason"] == "index_engine_stamp_write_failed"
    assert "PermissionError" in payload["error"]
    assert "Traceback" not in completed.stderr


def test_build_index_cli_unreadable_index_is_structured(tmp_path: Path):
    source = tmp_path / "main.c"
    source.write_text("int main(void) { return 0; }\n", encoding="utf-8")
    write_cdb(tmp_path, [source])
    index_dir = index_dir_for_compile_commands_dir(tmp_path)
    touch_idx(index_dir, 1)
    index_dir.chmod(0)
    try:
        completed = subprocess.run(
            [
                sys.executable,
                "tools/build_index.py",
                "--compile-commands-dir",
                str(tmp_path),
                "--inspect-only",
                "--clangd",
                str(fake_clangd(tmp_path, "21.1.1")),
            ],
            cwd=Path(__file__).resolve().parents[1],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    finally:
        index_dir.chmod(0o700)
    payload = json.loads(completed.stdout)

    assert completed.returncode == 1
    assert payload["health"] == IndexHealth.UNKNOWN
    assert payload["reason"] == "index_health_error"
    assert "PermissionError" in payload["error"]
    assert "Traceback" not in completed.stderr


def test_build_index_cli_reports_unverified_then_explicitly_stamps_legacy_cache(
    tmp_path: Path,
):
    source = tmp_path / "main.c"
    source.write_text("int main(void) { return 0; }\n", encoding="utf-8")
    write_cdb(tmp_path, [source])
    touch_idx(index_dir_for_compile_commands_dir(tmp_path), 1)
    clangd = fake_clangd(tmp_path, "21.1.1")
    command = [
        sys.executable,
        "tools/build_index.py",
        "--compile-commands-dir",
        str(tmp_path),
        "--inspect-only",
        "--clangd",
        str(clangd),
    ]

    before = subprocess.run(
        command,
        cwd=Path(__file__).resolve().parents[1],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    before_payload = json.loads(before.stdout)
    assert before_payload["health"]["health"] == IndexHealth.UNKNOWN
    assert before_payload["health"]["reason"] == "index_engine_unverified"

    stamped = subprocess.run(
        [*command, "--stamp-existing-index"],
        cwd=Path(__file__).resolve().parents[1],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    stamped_payload = json.loads(stamped.stdout)
    assert stamped_payload["health"]["health"] == IndexHealth.COMPLETE
    assert stamped_payload["engine_version"] == "clangd 21.1.1"


def test_build_index_cli_build_rejects_unverified_existing_cache(tmp_path: Path):
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
            "--clangd",
            str(fake_clangd(tmp_path, "21.1.1")),
        ],
        cwd=Path(__file__).resolve().parents[1],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    payload = json.loads(completed.stdout)

    assert completed.returncode == 1
    assert payload["build"]["health_report"]["reason"] == "index_engine_unverified"
    assert (
        read_index_engine_version(index_dir_for_compile_commands_dir(tmp_path)) is None
    )


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
