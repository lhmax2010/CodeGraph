"""Offline clangd background-index build helpers and index_health facts."""

from __future__ import annotations

import importlib
import fcntl
import json
import os
import shlex
import stat
import subprocess
import sys
import tempfile
import threading
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .credibility import IndexHealth
from .engine_version import (
    clangd_version_from_initialize,
    detect_clangd_version,
    normalize_clangd_version,
)

_ENGINE_STAMP_NAME = ".codegraph_engine"
_BUILDING_MARKER_NAME = ".codegraph_building"
_CACHE_LOCK_NAME = ".codegraph_index.lock"
_CONTROL_DIR_NAME = ".codegraph-control"
_MARKER_TEMP_PREFIX = ".codegraph-marker-"
_BUILD_INDEX_BLOCKING_REASONS = {
    "index_engine_build_in_progress",
    "index_engine_mismatch",
    "index_engine_stamp_invalid",
    "index_engine_stamp_write_failed",
    "index_engine_unavailable",
    "index_engine_unverified",
    "index_engine_version_inconsistent",
    "index_health_error",
}
_MAX_ENGINE_STAMP_BYTES = 4096


class _IndexEngineStampError(ValueError):
    def __init__(
        self,
        reason: str,
        message: str,
        *,
        existing_version: str | None = None,
    ):
        super().__init__(message)
        self.reason = reason
        self.existing_version = existing_version


@dataclass
class IndexCacheLock:
    path: Path
    fd: int
    exclusive: bool
    released: bool = False

    def release(self) -> None:
        if self.released:
            return
        try:
            fcntl.flock(self.fd, fcntl.LOCK_UN)
        finally:
            os.close(self.fd)
            self.released = True


@dataclass(frozen=True)
class CompileCommandsSummary:
    path: str
    entries: int
    unique_tu_count: int
    existing_files: int
    targets: tuple[str, ...] = ()
    sysroots: tuple[str, ...] = ()


@dataclass(frozen=True)
class IndexShardSummary:
    index_dir: str
    exists: bool
    idx_shards: int
    total_files: int
    extension_counts: tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True)
class IndexHealthReport:
    health: IndexHealth
    reason: str
    unique_tu_count: int
    idx_shards: int
    index_dir: str
    extension_counts: tuple[tuple[str, int], ...] = ()
    expected_engine_version: str | None = None
    index_engine_version: str | None = None


@dataclass(frozen=True)
class RewriteCdbResult:
    output_cdb: str
    entries_in: int
    entries_out: int
    skipped_no_file: int
    target: str | None
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class BackgroundIndexConfig:
    compile_commands_dir: str
    clangd_path: str = "clangd"
    jobs: int = 4
    max_wait_seconds: float = 60.0
    poll_interval_seconds: float = 1.0
    stable_rounds: int = 3
    trigger_files: tuple[str, ...] = ()


@dataclass(frozen=True)
class BackgroundIndexResult:
    compile_commands_dir: str
    index_dir: str
    elapsed_seconds: float
    exit_code: int | None
    stable: bool
    shard_report: IndexShardSummary
    health_report: IndexHealthReport
    stderr_tail: str = ""
    engine_version: str | None = None


def compile_commands_path(path_or_dir: str | Path) -> Path:
    path = Path(path_or_dir)
    return path / "compile_commands.json" if path.is_dir() else path


def summarize_compile_commands(path_or_dir: str | Path) -> CompileCommandsSummary:
    cdb_path = compile_commands_path(path_or_dir)
    with cdb_path.open(encoding="utf-8") as fh:
        entries = json.load(fh)
    if not isinstance(entries, list):
        raise ValueError(f"compile_commands must be a list: {cdb_path}")

    files = tuple(
        str(path)
        for entry in entries
        if (path := _entry_file_path(entry, cdb_path.parent)) is not None
    )
    unique_files = tuple(sorted(set(files)))
    existing = sum(1 for file in unique_files if Path(file).exists())
    targets: set[str] = set()
    sysroots: set[str] = set()
    for entry in entries:
        args = _entry_args(entry)
        targets.update(arg for arg in args if arg.startswith("--target="))
        sysroots.update(arg for arg in args if arg.startswith("--sysroot="))

    return CompileCommandsSummary(
        path=str(cdb_path.resolve()),
        entries=len(entries),
        unique_tu_count=len(unique_files),
        existing_files=existing,
        targets=tuple(sorted(targets)),
        sysroots=tuple(sorted(sysroots)),
    )


def scan_index_shards(index_dir: str | Path) -> IndexShardSummary:
    root = Path(index_dir)
    if not root.exists() or not root.is_dir():
        return IndexShardSummary(str(root.resolve()), False, 0, 0)
    directory_mode = root.stat().st_mode
    if (
        directory_mode & 0o444 == 0
        or directory_mode & 0o111 == 0
        or not os.access(root, os.R_OK | os.X_OK)
    ):
        raise PermissionError(f"index directory is not readable: {root}")

    files: list[Path] = []

    def raise_walk_error(error: OSError) -> None:
        raise error

    for current, _directories, names in os.walk(root, onerror=raise_walk_error):
        files.extend(path for name in names if (path := Path(current) / name).is_file())
    ext_counts = Counter(path.suffix or "<none>" for path in files)
    idx_count = ext_counts.get(".idx", 0)
    return IndexShardSummary(
        str(root.resolve()),
        True,
        idx_count,
        len(files),
        tuple(sorted(ext_counts.items())),
    )


def index_dir_for_compile_commands_dir(path_or_dir: str | Path) -> Path:
    cdb_path = compile_commands_path(path_or_dir)
    return cdb_path.parent / ".cache" / "clangd" / "index"


def index_engine_stamp_path(index_dir: str | Path) -> Path:
    return Path(index_dir) / _ENGINE_STAMP_NAME


def index_engine_building_path(index_dir: str | Path) -> Path:
    return Path(index_dir) / _BUILDING_MARKER_NAME


def index_cache_lock_path(index_dir: str | Path) -> Path:
    return Path(index_dir).parent / _CACHE_LOCK_NAME


def acquire_index_cache_lock(
    index_dir: str | Path, *, exclusive: bool
) -> IndexCacheLock:
    """Acquire the cache-wide lock used by builders, queries, and attestation."""

    path = index_cache_lock_path(index_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = (
        os.O_RDWR
        | os.O_CREAT
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        fd = os.open(path, flags, 0o644)
    except OSError as exc:
        raise _IndexEngineStampError(
            "index_health_error", f"index cache lock is unavailable: {path}"
        ) from exc
    try:
        opened = os.fstat(fd)
        current = os.lstat(path)
        if (
            not stat.S_ISREG(opened.st_mode)
            or not stat.S_ISREG(current.st_mode)
            or opened.st_dev != current.st_dev
            or opened.st_ino != current.st_ino
        ):
            raise ValueError(f"index cache lock must be a stable regular file: {path}")
        operation = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        try:
            fcntl.flock(fd, operation | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise _IndexEngineStampError(
                "index_engine_build_in_progress",
                f"index cache is locked by an active build: {path}",
            ) from exc
        return IndexCacheLock(path=path, fd=fd, exclusive=exclusive)
    except BaseException as exc:
        os.close(fd)
        if isinstance(exc, _IndexEngineStampError):
            raise
        if isinstance(exc, (OSError, ValueError)):
            raise _IndexEngineStampError(
                "index_health_error", f"index cache lock is invalid: {path}"
            ) from exc
        raise


def read_index_engine_version(index_dir: str | Path) -> str | None:
    """Read the committed engine version from a canonical regular-file stamp."""

    return _read_engine_marker(index_engine_stamp_path(index_dir))


def read_index_building_version(index_dir: str | Path) -> str | None:
    """Read the dirty build owner; its presence means the cache is uncommitted."""

    return _read_engine_marker(index_engine_building_path(index_dir))


def write_index_engine_version(index_dir: str | Path, engine_version: str) -> Path:
    """Explicitly publish a committed stamp without replacing another owner."""

    normalized = normalize_clangd_version(engine_version)
    if normalized is None:
        raise ValueError(f"invalid canonical clangd version: {engine_version!r}")
    lock = acquire_index_cache_lock(index_dir, exclusive=True)
    try:
        try:
            dirty = read_index_building_version(index_dir)
            existing = read_index_engine_version(index_dir)
        except (OSError, ValueError) as exc:
            raise _invalid_stamp_error(index_engine_stamp_path(index_dir)) from exc
        if dirty is not None:
            raise _IndexEngineStampError(
                "index_engine_build_in_progress",
                f"cannot publish committed stamp while dirty marker exists: {dirty}",
                existing_version=dirty,
            )
        if existing is not None and existing != normalized:
            raise _IndexEngineStampError(
                "index_engine_mismatch",
                f"conflicting index engine marker: {existing} != {normalized}",
                existing_version=existing,
            )
        try:
            return _publish_engine_marker(
                index_engine_stamp_path(index_dir), normalized
            )
        except OSError as exc:
            raise _IndexEngineStampError(
                "index_engine_stamp_write_failed",
                f"{type(exc).__name__}: cannot write index engine stamp: "
                f"{index_engine_stamp_path(index_dir)}: {exc}",
            ) from exc
    except _IndexEngineStampError:
        raise
    except ValueError as exc:
        raise _invalid_stamp_error(index_engine_stamp_path(index_dir)) from exc
    finally:
        lock.release()


def _publish_engine_marker(path: Path, engine_version: str) -> Path:
    normalized = normalize_clangd_version(engine_version)
    if normalized is None or engine_version.strip() != normalized:
        raise ValueError(f"invalid canonical clangd version: {engine_version!r}")
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = _read_engine_marker(path)
    if existing is not None:
        if existing != normalized:
            raise _IndexEngineStampError(
                "index_engine_mismatch",
                f"conflicting index engine marker: {existing} != {normalized}",
                existing_version=existing,
            )
        return path

    control_dir = path.parent.parent / _CONTROL_DIR_NAME
    control_dir.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=_MARKER_TEMP_PREFIX, suffix=".tmp", dir=control_dir
    )
    temporary = Path(temporary_name)
    published = False
    try:
        os.fchmod(fd, 0o644)
        os.write(fd, (normalized + "\n").encode("utf-8"))
        os.fsync(fd)
        try:
            os.link(temporary, path)
        except FileExistsError:
            existing = _read_engine_marker(path)
            if existing != normalized:
                raise _IndexEngineStampError(
                    "index_engine_mismatch",
                    f"conflicting index engine marker: {existing} != {normalized}",
                    existing_version=existing,
                )
            return path
        published = True
        _verify_marker_identity(path, os.fstat(fd))
        _fsync_directory(path.parent)
        return path
    except BaseException:
        if published:
            try:
                current = os.lstat(path)
            except FileNotFoundError:
                current = None
            if (
                current is not None
                and current.st_dev == os.fstat(fd).st_dev
                and current.st_ino == os.fstat(fd).st_ino
            ):
                path.unlink()
        raise
    finally:
        temporary.unlink(missing_ok=True)
        os.close(fd)


def _open_index_engine_stamp(path: Path) -> tuple[int, os.stat_result] | None:
    return _open_engine_marker(path)


def _open_engine_marker(path: Path) -> tuple[int, os.stat_result] | None:
    try:
        path_stat = os.lstat(path)
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(path_stat.st_mode):
        raise ValueError(f"index engine stamp must be a regular file: {path}")

    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        opened_stat = os.fstat(fd)
        if (
            not stat.S_ISREG(opened_stat.st_mode)
            or opened_stat.st_dev != path_stat.st_dev
            or opened_stat.st_ino != path_stat.st_ino
        ):
            raise ValueError(f"index engine stamp changed while opening: {path}")
        return fd, opened_stat
    except BaseException:
        os.close(fd)
        raise


def _read_index_engine_version_fd(fd: int, path: Path) -> str:
    return _read_engine_marker_fd(fd, path)


def _read_engine_marker_fd(fd: int, path: Path) -> str:
    os.lseek(fd, 0, os.SEEK_SET)
    encoded = os.read(fd, _MAX_ENGINE_STAMP_BYTES + 1)
    if len(encoded) > _MAX_ENGINE_STAMP_BYTES:
        raise ValueError(f"index engine stamp is too large: {path}")
    try:
        raw = encoded.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"invalid index engine stamp encoding: {path}") from exc
    stripped = raw.strip()
    normalized = normalize_clangd_version(stripped)
    if normalized is None or stripped != normalized:
        raise ValueError(f"invalid index engine stamp: {path}")
    return normalized


def _read_engine_marker(path: Path) -> str | None:
    opened = _open_engine_marker(path)
    if opened is None:
        return None
    fd, _ = opened
    try:
        return _read_engine_marker_fd(fd, path)
    finally:
        os.close(fd)


def _verify_stamp_identity(path: Path, expected: os.stat_result) -> None:
    _verify_marker_identity(path, expected)


def _verify_marker_identity(path: Path, expected: os.stat_result) -> None:
    current = os.lstat(path)
    if (
        not stat.S_ISREG(current.st_mode)
        or current.st_dev != expected.st_dev
        or current.st_ino != expected.st_ino
    ):
        raise ValueError(f"index engine stamp changed while claiming: {path}")


def _fsync_directory(path: Path) -> None:
    directory_fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _invalid_stamp_error(path: Path) -> _IndexEngineStampError:
    return _IndexEngineStampError(
        "index_engine_stamp_invalid",
        f"index engine stamp is invalid or unreadable: {path}",
    )


def evaluate_index_health(
    cdb: CompileCommandsSummary,
    shards: IndexShardSummary,
    *,
    expected_engine_version: str | None = None,
    check_engine_ownership: bool = False,
) -> IndexHealthReport:
    if not shards.exists:
        return _health(
            IndexHealth.UNKNOWN,
            "index_dir_missing",
            cdb,
            shards,
            expected_engine_version=expected_engine_version,
        )

    verify_ownership = check_engine_ownership or expected_engine_version is not None
    expected = normalize_clangd_version(expected_engine_version)
    actual: str | None = None
    dirty: str | None = None
    try:
        actual = read_index_engine_version(shards.index_dir)
        dirty = read_index_building_version(shards.index_dir)
    except (OSError, ValueError):
        return _health(
            IndexHealth.UNKNOWN,
            "index_engine_stamp_invalid",
            cdb,
            shards,
            expected_engine_version=expected,
        )
    if dirty is not None and actual is not None and dirty != actual:
        return _health(
            IndexHealth.UNKNOWN,
            "index_engine_version_inconsistent",
            cdb,
            shards,
            expected_engine_version=expected,
            index_engine_version=dirty,
        )
    if dirty is not None:
        if expected is not None and dirty != expected:
            return _health(
                IndexHealth.UNKNOWN,
                "index_engine_mismatch",
                cdb,
                shards,
                expected_engine_version=expected,
                index_engine_version=dirty,
            )
        return _health(
            IndexHealth.UNKNOWN,
            (
                "index_engine_unavailable"
                if verify_ownership and expected is None
                else "index_engine_build_in_progress"
            ),
            cdb,
            shards,
            expected_engine_version=expected,
            index_engine_version=dirty,
        )
    if verify_ownership:
        if actual is not None and expected is None:
            return _health(
                IndexHealth.UNKNOWN,
                "index_engine_unavailable",
                cdb,
                shards,
                index_engine_version=actual,
            )
        if actual is None and shards.total_files > 0:
            return _health(
                IndexHealth.UNKNOWN,
                "index_engine_unverified",
                cdb,
                shards,
                expected_engine_version=expected,
            )
        if actual is not None and actual != expected:
            return _health(
                IndexHealth.UNKNOWN,
                "index_engine_mismatch",
                cdb,
                shards,
                expected_engine_version=expected,
                index_engine_version=actual,
            )

    return _evaluate_structural_index_health(
        cdb,
        shards,
        expected_engine_version=expected,
        index_engine_version=actual,
    )


def _evaluate_structural_index_health(
    cdb: CompileCommandsSummary,
    shards: IndexShardSummary,
    *,
    expected_engine_version: str | None = None,
    index_engine_version: str | None = None,
) -> IndexHealthReport:
    if cdb.unique_tu_count <= 0:
        return _health(
            IndexHealth.UNKNOWN,
            "no_translation_units",
            cdb,
            shards,
            expected_engine_version=expected_engine_version,
            index_engine_version=index_engine_version,
        )
    if shards.idx_shards == 0 and shards.total_files > 0:
        return _health(
            IndexHealth.UNKNOWN,
            "no_idx_files",
            cdb,
            shards,
            expected_engine_version=expected_engine_version,
            index_engine_version=index_engine_version,
        )
    if shards.idx_shards < cdb.unique_tu_count:
        return _health(
            IndexHealth.INCOMPLETE,
            "shards_lt_unique_tu",
            cdb,
            shards,
            expected_engine_version=expected_engine_version,
            index_engine_version=index_engine_version,
        )
    return _health(
        IndexHealth.COMPLETE,
        "shards_ge_unique_tu",
        cdb,
        shards,
        expected_engine_version=expected_engine_version,
        index_engine_version=index_engine_version,
    )


def stamp_existing_index(
    compile_commands_dir: str | Path, clangd_path: str
) -> IndexHealthReport:
    """Explicitly attest a healthy legacy cache with the selected clangd version."""

    cdb = summarize_compile_commands(compile_commands_dir)
    index_dir = index_dir_for_compile_commands_dir(compile_commands_dir)
    lock = acquire_index_cache_lock(index_dir, exclusive=True)
    try:
        shards = scan_index_shards(index_dir)
        try:
            dirty = read_index_building_version(index_dir)
            existing = read_index_engine_version(index_dir)
        except (OSError, ValueError) as exc:
            raise _IndexEngineStampError(
                "index_engine_stamp_invalid",
                f"index engine marker is invalid or unreadable: {index_dir}",
            ) from exc
        if dirty is not None:
            raise _IndexEngineStampError(
                "index_engine_build_in_progress",
                f"cannot attest an index with a dirty build marker: {dirty}",
                existing_version=dirty,
            )
        structural = _evaluate_structural_index_health(cdb, shards)
        if structural.health != IndexHealth.COMPLETE:
            raise ValueError(
                f"cannot stamp index with health={structural.health.value}: "
                f"{structural.reason}"
            )
        engine_version = detect_clangd_version(clangd_path)
        if engine_version is None:
            raise ValueError(f"cannot detect clangd version: {clangd_path}")
        if existing is not None and existing != engine_version:
            raise ValueError(
                f"conflicting index engine stamp: {existing} != {engine_version}"
            )
        try:
            _publish_engine_marker(index_engine_stamp_path(index_dir), engine_version)
        except OSError as exc:
            raise _IndexEngineStampError(
                "index_engine_stamp_write_failed",
                f"{type(exc).__name__}: cannot write index engine stamp: "
                f"{index_engine_stamp_path(index_dir)}",
            ) from exc
        return evaluate_index_health(
            cdb, scan_index_shards(index_dir), expected_engine_version=engine_version
        )
    finally:
        lock.release()


def rewrite_cdb_for_index(
    input_cdb: str | Path,
    output_dir: str | Path,
    *,
    buildroot: str | Path,
    target: str | None = None,
    resource_dir: str | None = None,
    keep_missing_files: bool = False,
) -> RewriteCdbResult:
    """Rewrite a GBS CDB by delegating to the existing tools/cdb_rewriter asset."""

    rewriter = _load_cdb_rewriter()
    buildroot_path = str(Path(buildroot).resolve())
    detected_target = target or rewriter.detect_triple(buildroot_path)
    cfg = rewriter.RewriteConfig(
        buildroot=buildroot_path,
        target=detected_target,
        inject_resource_dir=resource_dir,
    )
    with Path(input_cdb).open(encoding="utf-8") as fh:
        cdb = json.load(fh)
    rewritten, stats = rewriter.rewrite_cdb(
        cdb, cfg, require_file_exists=not keep_missing_files
    )

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    output_cdb = out_dir / "compile_commands.json"
    with output_cdb.open("w", encoding="utf-8") as fh:
        json.dump(rewritten, fh, indent=2, ensure_ascii=False)

    return RewriteCdbResult(
        output_cdb=str(output_cdb.resolve()),
        entries_in=stats.entries_in,
        entries_out=stats.entries_out,
        skipped_no_file=stats.skipped_no_file,
        target=detected_target,
        notes=tuple(stats.notes),
    )


def run_background_index(config: BackgroundIndexConfig) -> BackgroundIndexResult:
    """Build a complete background index from zero; this is not incremental."""

    compile_dir = Path(config.compile_commands_dir).resolve()
    cdb = summarize_compile_commands(compile_dir)
    index_dir = index_dir_for_compile_commands_dir(compile_dir)
    engine_version = detect_clangd_version(config.clangd_path)
    try:
        cache_lock = acquire_index_cache_lock(index_dir, exclusive=True)
    except _IndexEngineStampError as exc:
        initial_shards = _best_effort_shard_summary(index_dir)
        health = _health(
            IndexHealth.UNKNOWN,
            exc.reason,
            cdb,
            initial_shards,
            expected_engine_version=engine_version,
            index_engine_version=exc.existing_version,
        )
        return BackgroundIndexResult(
            compile_commands_dir=str(compile_dir),
            index_dir=initial_shards.index_dir,
            elapsed_seconds=0.0,
            exit_code=None,
            stable=False,
            shard_report=initial_shards,
            health_report=health,
            stderr_tail=str(exc),
            engine_version=engine_version,
        )

    try:
        return _run_background_index_locked(
            config, compile_dir, cdb, index_dir, engine_version
        )
    finally:
        cache_lock.release()


def _run_background_index_locked(
    config: BackgroundIndexConfig,
    compile_dir: Path,
    cdb: CompileCommandsSummary,
    index_dir: Path,
    engine_version: str | None,
) -> BackgroundIndexResult:
    try:
        _cleanup_control_temps(index_dir)
        initial_shards = scan_index_shards(index_dir)
    except (OSError, ValueError) as exc:
        initial_shards = IndexShardSummary(
            str(index_dir.resolve()), index_dir.exists(), 0, 0
        )
        health = _health(IndexHealth.UNKNOWN, "index_health_error", cdb, initial_shards)
        return BackgroundIndexResult(
            compile_commands_dir=str(compile_dir),
            index_dir=initial_shards.index_dir,
            elapsed_seconds=0.0,
            exit_code=None,
            stable=False,
            shard_report=initial_shards,
            health_report=health,
            stderr_tail=f"{type(exc).__name__}: {exc}",
        )
    probed_engine_version = engine_version
    preflight = _build_preflight_health(cdb, initial_shards, engine_version)
    if preflight is not None:
        return BackgroundIndexResult(
            compile_commands_dir=str(compile_dir),
            index_dir=initial_shards.index_dir,
            elapsed_seconds=0.0,
            exit_code=None,
            stable=False,
            shard_report=initial_shards,
            health_report=preflight,
            stderr_tail=preflight.reason,
            engine_version=engine_version,
        )
    start = time.monotonic()
    client: _IndexLspClient | None = None
    stable = False
    stderr_tail = ""
    exit_code: int | None = None
    error_reason: str | None = None
    error_tail = ""
    ownership_health: IndexHealthReport | None = None
    dirty_published = False
    try:
        trigger_files = config.trigger_files or _default_trigger_files(compile_dir, cdb)
        client = _IndexLspClient(config)
        client.initialize()
        engine_version = client.engine_version
        ownership_health = _post_initialize_preflight_health(
            cdb,
            scan_index_shards(index_dir),
            engine_version,
            probed_engine_version,
        )
        if ownership_health is not None:
            client.shutdown()
        else:
            if engine_version is None:
                raise RuntimeError("clangd version missing after ownership preflight")
            try:
                _publish_dirty_marker(index_dir, engine_version)
                dirty_published = True
            except _IndexEngineStampError as exc:
                ownership_health = _health(
                    IndexHealth.UNKNOWN,
                    exc.reason,
                    cdb,
                    scan_index_shards(index_dir),
                    expected_engine_version=engine_version,
                    index_engine_version=exc.existing_version,
                )
                client.shutdown()
            except (OSError, ValueError) as exc:
                ownership_health = _health(
                    IndexHealth.UNKNOWN,
                    "index_engine_stamp_write_failed",
                    cdb,
                    scan_index_shards(index_dir),
                    expected_engine_version=engine_version,
                )
                error_tail = f"{type(exc).__name__}: {exc}"
                client.shutdown()
            else:
                try:
                    _clear_index_shards(index_dir)
                except (OSError, ValueError) as exc:
                    ownership_health = _health(
                        IndexHealth.UNKNOWN,
                        "index_health_error",
                        cdb,
                        _best_effort_shard_summary(index_dir),
                        expected_engine_version=engine_version,
                    )
                    error_tail = f"{type(exc).__name__}: {exc}"
                    client.shutdown()
                else:
                    client.notify_initialized()
                    for file in trigger_files:
                        client.open_file(file)
                    client.request_document_symbols(trigger_files[0])
                    stable = _wait_for_stable_shards(
                        index_dir,
                        stable_rounds=config.stable_rounds,
                        max_wait_seconds=config.max_wait_seconds,
                        poll_interval_seconds=config.poll_interval_seconds,
                    )
                    client.shutdown()
    except Exception as exc:
        error_reason = "index_build_failed"
        error_tail = f"{type(exc).__name__}: {exc}"
    finally:
        if client is not None:
            exit_code, stderr_tail = client.close()
        if error_tail:
            stderr_tail = "\n".join(part for part in (stderr_tail, error_tail) if part)

    elapsed = time.monotonic() - start
    try:
        shard_report = scan_index_shards(index_dir)
    except (OSError, ValueError) as exc:
        shard_report = IndexShardSummary(
            str(index_dir.resolve()), index_dir.exists(), 0, 0
        )
        error_reason = "index_health_error"
        stderr_tail = "\n".join(
            part for part in (stderr_tail, f"{type(exc).__name__}: {exc}") if part
        )
    if ownership_health is not None:
        health = ownership_health
    elif error_reason is not None:
        health = _health(IndexHealth.UNKNOWN, error_reason, cdb, shard_report)
    elif stable and exit_code == 0:
        structural = _evaluate_structural_index_health(cdb, shard_report)
        if not dirty_published:
            health = _health(
                IndexHealth.UNKNOWN,
                "index_engine_unverified",
                cdb,
                shard_report,
            )
        elif structural.health != IndexHealth.COMPLETE:
            health = structural
        else:
            try:
                _commit_index_build(index_dir, engine_version)
                health = evaluate_index_health(
                    cdb,
                    scan_index_shards(index_dir),
                    expected_engine_version=engine_version,
                    check_engine_ownership=True,
                )
            except _IndexEngineStampError as exc:
                health = _health(
                    IndexHealth.UNKNOWN,
                    exc.reason,
                    cdb,
                    shard_report,
                    expected_engine_version=engine_version,
                    index_engine_version=exc.existing_version,
                )
                stderr_tail = "\n".join(
                    part for part in (stderr_tail, str(exc)) if part
                )
            except (OSError, ValueError) as exc:
                health = _health(
                    IndexHealth.UNKNOWN,
                    "index_engine_stamp_write_failed",
                    cdb,
                    shard_report,
                    expected_engine_version=engine_version,
                )
                stderr_tail = "\n".join(
                    part
                    for part in (stderr_tail, f"{type(exc).__name__}: {exc}")
                    if part
                )
    else:
        health = _health(
            IndexHealth.UNKNOWN, "index_build_not_stable", cdb, shard_report
        )
    return BackgroundIndexResult(
        compile_commands_dir=str(compile_dir),
        index_dir=shard_report.index_dir,
        elapsed_seconds=elapsed,
        exit_code=exit_code,
        stable=stable,
        shard_report=shard_report,
        health_report=health,
        stderr_tail=stderr_tail,
        engine_version=engine_version,
    )


def _best_effort_shard_summary(index_dir: Path) -> IndexShardSummary:
    try:
        return scan_index_shards(index_dir)
    except (OSError, ValueError):
        return IndexShardSummary(str(index_dir.resolve()), index_dir.exists(), 0, 0)


def _publish_dirty_marker(index_dir: Path, engine_version: str) -> None:
    committed = read_index_engine_version(index_dir)
    dirty = read_index_building_version(index_dir)
    if committed is not None and dirty is not None and committed != dirty:
        raise _IndexEngineStampError(
            "index_engine_version_inconsistent",
            f"dirty and committed engine versions disagree: {dirty} != {committed}",
            existing_version=dirty,
        )
    for existing in (committed, dirty):
        if existing is not None and existing != engine_version:
            raise _IndexEngineStampError(
                "index_engine_mismatch",
                f"index cache belongs to {existing}, not {engine_version}",
                existing_version=existing,
            )
    _publish_engine_marker(index_engine_building_path(index_dir), engine_version)


def _commit_index_build(index_dir: Path, engine_version: str | None) -> None:
    if engine_version is None:
        raise _IndexEngineStampError(
            "index_engine_unavailable", "cannot commit index without engine version"
        )
    dirty = read_index_building_version(index_dir)
    if dirty != engine_version:
        raise _IndexEngineStampError(
            "index_engine_version_inconsistent",
            f"dirty marker changed before commit: {dirty!r} != {engine_version!r}",
            existing_version=dirty,
        )
    _publish_engine_marker(index_engine_stamp_path(index_dir), engine_version)
    _fsync_directory(index_dir)
    building = index_engine_building_path(index_dir)
    current = read_index_building_version(index_dir)
    if current != engine_version:
        raise _IndexEngineStampError(
            "index_engine_version_inconsistent",
            f"dirty marker changed during commit: {current!r}",
            existing_version=current,
        )
    building.unlink()
    _fsync_directory(index_dir)


def _clear_index_shards(index_dir: Path) -> None:
    """Remove all old clangd shards before a complete from-zero rebuild."""

    if not index_dir.exists():
        return
    for current, _directories, names in os.walk(index_dir):
        for name in names:
            if not name.endswith(".idx"):
                continue
            (Path(current) / name).unlink()


def _cleanup_control_temps(index_dir: Path) -> None:
    control_dir = index_dir.parent / _CONTROL_DIR_NAME
    if control_dir.exists():
        control_stat = os.lstat(control_dir)
        if not stat.S_ISDIR(control_stat.st_mode):
            raise ValueError(f"index control path must be a directory: {control_dir}")
    else:
        control_dir.mkdir(parents=True)
    for temporary in control_dir.glob(_MARKER_TEMP_PREFIX + "*.tmp"):
        temporary.unlink()


def _health(
    health: IndexHealth,
    reason: str,
    cdb: CompileCommandsSummary,
    shards: IndexShardSummary,
    *,
    expected_engine_version: str | None = None,
    index_engine_version: str | None = None,
) -> IndexHealthReport:
    return IndexHealthReport(
        health=health,
        reason=reason,
        unique_tu_count=cdb.unique_tu_count,
        idx_shards=shards.idx_shards,
        index_dir=shards.index_dir,
        extension_counts=shards.extension_counts,
        expected_engine_version=expected_engine_version,
        index_engine_version=index_engine_version,
    )


def _build_preflight_health(
    cdb: CompileCommandsSummary,
    shards: IndexShardSummary,
    engine_version: str | None,
) -> IndexHealthReport | None:
    report = evaluate_index_health(
        cdb,
        shards,
        expected_engine_version=engine_version,
        check_engine_ownership=True,
    )
    if (
        report.reason == "index_engine_build_in_progress"
        and engine_version is not None
        and report.index_engine_version == engine_version
    ):
        # The cache-wide exclusive lock proves this is a stale same-version dirty
        # marker, not an active peer. A full rebuild may safely take it over.
        return None
    if report.reason in _BUILD_INDEX_BLOCKING_REASONS:
        return report
    return None


def _post_initialize_preflight_health(
    cdb: CompileCommandsSummary,
    shards: IndexShardSummary,
    engine_version: str | None,
    probed_engine_version: str | None,
) -> IndexHealthReport | None:
    report = evaluate_index_health(
        cdb,
        shards,
        expected_engine_version=engine_version,
        check_engine_ownership=True,
    )
    if report.reason == "index_engine_stamp_invalid":
        return report
    if engine_version is None:
        return _health(
            IndexHealth.UNKNOWN,
            "index_engine_unavailable",
            cdb,
            shards,
            index_engine_version=report.index_engine_version,
        )
    if (
        report.reason == "index_engine_build_in_progress"
        and report.index_engine_version == engine_version
    ):
        report = _evaluate_structural_index_health(cdb, shards)
    if report.reason in _BUILD_INDEX_BLOCKING_REASONS:
        return report
    if probed_engine_version is not None and engine_version != probed_engine_version:
        return _health(
            IndexHealth.UNKNOWN,
            "index_engine_version_inconsistent",
            cdb,
            shards,
            expected_engine_version=probed_engine_version,
            index_engine_version=engine_version,
        )
    return None


def _entry_args(entry: dict[str, Any]) -> tuple[str, ...]:
    args = entry.get("arguments")
    if isinstance(args, list):
        return tuple(str(arg) for arg in args)
    command = entry.get("command")
    return tuple(shlex.split(str(command))) if command else ()


def _load_cdb_rewriter() -> Any:
    tools_dir = Path(__file__).resolve().parents[1] / "tools"
    if str(tools_dir) not in sys.path:
        sys.path.insert(0, str(tools_dir))
    return importlib.import_module("cdb_rewriter")


def _entry_file_path(entry: dict[str, Any], cdb_dir: Path) -> Path | None:
    raw_file = str(entry.get("file", ""))
    if not raw_file:
        return None
    file_path = Path(raw_file)
    if file_path.is_absolute():
        return file_path.resolve()

    raw_directory = str(entry.get("directory", ""))
    directory = Path(raw_directory) if raw_directory else cdb_dir
    if not directory.is_absolute():
        directory = cdb_dir / directory
    return (directory / file_path).resolve()


def _default_trigger_files(
    compile_dir: Path, cdb: CompileCommandsSummary
) -> tuple[str, ...]:
    del cdb
    with (compile_dir / "compile_commands.json").open(encoding="utf-8") as fh:
        entries = json.load(fh)
    for entry in entries:
        file = _entry_file_path(entry, compile_dir)
        if file is not None and file.exists():
            return (str(file),)
    raise ValueError(f"no existing files in compile_commands: {compile_dir}")


def _wait_for_stable_shards(
    index_dir: Path,
    *,
    stable_rounds: int,
    max_wait_seconds: float,
    poll_interval_seconds: float,
) -> bool:
    deadline = time.monotonic() + max_wait_seconds
    last_count = -1
    same_count_rounds = 0
    while time.monotonic() < deadline:
        count = scan_index_shards(index_dir).idx_shards
        if count > 0 and count == last_count:
            same_count_rounds += 1
            if same_count_rounds >= stable_rounds:
                return True
        else:
            same_count_rounds = 0
            last_count = count
        time.sleep(poll_interval_seconds)
    return False


class _IndexLspClient:
    def __init__(self, config: BackgroundIndexConfig):
        self._config = config
        self._id = 0
        self._responses: dict[int, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._stderr_lines: list[str] = []
        self.engine_version: str | None = None
        args = [
            config.clangd_path,
            "--background-index=true",
            "--pch-storage=memory",
            "--log=error",
            f"--compile-commands-dir={Path(config.compile_commands_dir).resolve()}",
            f"-j={config.jobs}",
        ]
        self._proc = subprocess.Popen(
            args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(Path(config.compile_commands_dir).resolve()),
            bufsize=0,
        )
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        self._errreader = threading.Thread(target=self._read_stderr, daemon=True)
        self._errreader.start()

    def initialize(self) -> None:
        root = str(Path(self._config.compile_commands_dir).resolve())
        result = self.request(
            "initialize",
            {"processId": os.getpid(), "rootUri": "file://" + root, "capabilities": {}},
            timeout=20,
        )
        self.engine_version = clangd_version_from_initialize(result)

    def notify_initialized(self) -> None:
        self.notify("initialized", {})

    def open_file(self, file: str) -> None:
        path = Path(file).resolve()
        self.notify(
            "textDocument/didOpen",
            {
                "textDocument": {
                    "uri": "file://" + str(path),
                    "languageId": _language_id(path),
                    "version": 1,
                    "text": path.read_text(encoding="utf-8", errors="replace"),
                }
            },
        )

    def request_document_symbols(self, file: str) -> Any:
        return self.request(
            "textDocument/documentSymbol",
            {"textDocument": {"uri": "file://" + str(Path(file).resolve())}},
            timeout=30,
        )

    def request(
        self, method: str, params: dict[str, Any], timeout: float = 30.0
    ) -> Any:
        self._id += 1
        rid = self._id
        self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                response = self._responses.pop(rid, None)
            if response is None:
                time.sleep(0.02)
                continue
            if "error" in response:
                raise RuntimeError(f"{method} error: {response['error']}")
            return response.get("result")
        raise TimeoutError(f"{method} timed out after {timeout}s")

    def notify(self, method: str, params: dict[str, Any]) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def shutdown(self) -> None:
        try:
            self.request("shutdown", {}, timeout=5)
            self.notify("exit", {})
        except Exception:
            pass

    def close(self) -> tuple[int | None, str]:
        try:
            self._proc.wait(timeout=5)
        except Exception:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=5)
            except Exception:
                self._proc.kill()
                self._proc.wait(timeout=5)
        return self._proc.returncode, "\n".join(self._stderr_lines[-40:])

    def _send(self, payload: dict[str, Any]) -> None:
        if self._proc.stdin is None:
            raise RuntimeError("clangd stdin closed")
        data = json.dumps(payload).encode("utf-8")
        self._proc.stdin.write(f"Content-Length: {len(data)}\r\n\r\n".encode("ascii"))
        self._proc.stdin.write(data)
        self._proc.stdin.flush()

    def _read_loop(self) -> None:
        stream = self._proc.stdout
        if stream is None:
            return
        while True:
            header = b""
            while b"\r\n\r\n" not in header:
                chunk = stream.read(1)
                if not chunk:
                    return
                header += chunk
            length = 0
            for line in header.decode("ascii", "replace").split("\r\n"):
                if line.lower().startswith("content-length:"):
                    length = int(line.split(":", 1)[1].strip())
            body = stream.read(length)
            try:
                message = json.loads(body.decode("utf-8"))
            except Exception:
                continue
            if "id" in message:
                with self._lock:
                    self._responses[int(message["id"])] = message

    def _read_stderr(self) -> None:
        stream = self._proc.stderr
        if stream is None:
            return
        for line in iter(stream.readline, b""):
            self._stderr_lines.append(line.decode("utf-8", "replace").rstrip())


def _language_id(path: Path) -> str:
    return "cpp" if path.suffix in {".cc", ".cpp", ".cxx", ".hpp", ".hh"} else "c"
