#!/usr/bin/env python3
"""Build clangd background-index shards and report CodeGraph index_health."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, replace
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from codegraph.indexing import (  # noqa: E402 - script bootstraps repo root first.
    BackgroundIndexConfig,
    acquire_index_cache_lock,
    evaluate_index_health,
    index_dir_for_compile_commands_dir,
    rewrite_cdb_for_index,
    run_background_index,
    scan_index_shards,
    stamp_existing_index,
    summarize_compile_commands,
)
from codegraph.engine_version import (  # noqa: E402 - same bootstrap.
    detect_clangd_version,
)
from codegraph.credibility import IndexHealth  # noqa: E402 - same bootstrap.

_INDEX_ENGINE_BLOCKING_REASONS = {
    "index_engine_build_in_progress",
    "index_engine_mismatch",
    "index_engine_stamp_invalid",
    "index_engine_stamp_write_failed",
    "index_engine_unavailable",
    "index_engine_version_inconsistent",
    "index_health_error",
}
_BUILD_INDEX_BLOCKING_REASONS = {
    *_INDEX_ENGINE_BLOCKING_REASONS,
    "index_engine_unverified",
}


def _dump_json(payload: object) -> None:
    json.dump(payload, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build a complete CodeGraph clangd background-index from zero and emit "
            "index_health. This command is not incremental."
        )
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--compile-commands-dir",
        help="Directory already containing a rewritten compile_commands.json.",
    )
    source.add_argument(
        "--input-cdb",
        help="Source GBS/chroot compile_commands.json to rewrite before indexing.",
    )
    parser.add_argument(
        "--output-dir",
        help="Output directory for rewritten CDB when --input-cdb is used.",
    )
    parser.add_argument("--buildroot", help="GBS buildroot for cdb_rewriter.")
    parser.add_argument("--target", help="Override target triple for cdb_rewriter.")
    parser.add_argument("--clangd", default="clangd", help="clangd binary path.")
    parser.add_argument("--jobs", type=int, default=4, help="clangd -j value.")
    parser.add_argument("--max-wait", type=float, default=60.0)
    parser.add_argument("--poll-interval", type=float, default=1.0)
    parser.add_argument("--stable-rounds", type=int, default=3)
    parser.add_argument(
        "--inspect-only",
        action="store_true",
        help="Only inspect existing shards; do not launch clangd.",
    )
    parser.add_argument(
        "--stamp-existing-index",
        action="store_true",
        help=(
            "Operator attestation that a healthy legacy cache was built by "
            "--clangd; provenance cannot be inferred. Requires --inspect-only. "
            "Never attest a cache touched by another clangd version."
        ),
    )
    args = parser.parse_args(argv)
    return_code = 0

    try:
        if args.input_cdb:
            if not args.output_dir or not args.buildroot:
                parser.error("--input-cdb requires --output-dir and --buildroot")
            rewrite = rewrite_cdb_for_index(
                args.input_cdb,
                args.output_dir,
                buildroot=args.buildroot,
                target=args.target,
            )
            compile_dir = str(Path(rewrite.output_cdb).parent)
        else:
            compile_dir = str(Path(args.compile_commands_dir).resolve())
            rewrite = None

        if args.stamp_existing_index and not args.inspect_only:
            raise ValueError("--stamp-existing-index requires --inspect-only")

        if args.inspect_only:
            if args.stamp_existing_index:
                try:
                    stamp_existing_index(compile_dir, args.clangd)
                except (OSError, ValueError) as exc:
                    reason = getattr(exc, "reason", "index_engine_stamp_write_failed")
                    _dump_json(
                        {
                            "error": f"{type(exc).__name__}: {exc}",
                            "health": "unknown",
                            "reason": reason,
                        }
                    )
                    return 1
            index_dir = index_dir_for_compile_commands_dir(compile_dir)
            inspect_lock = acquire_index_cache_lock(index_dir, exclusive=False)
            try:
                cdb = summarize_compile_commands(compile_dir)
                shards = scan_index_shards(index_dir)
                engine_version = detect_clangd_version(args.clangd)
                if engine_version is None:
                    health = evaluate_index_health(
                        cdb,
                        shards,
                        check_engine_ownership=True,
                    )
                    if health.reason != "index_engine_stamp_invalid":
                        health = replace(
                            health,
                            health=IndexHealth.UNKNOWN,
                            reason="index_engine_unavailable",
                        )
                    return_code = 1
                else:
                    health = evaluate_index_health(
                        cdb,
                        shards,
                        expected_engine_version=engine_version,
                        check_engine_ownership=True,
                    )
            finally:
                inspect_lock.release()
            if health.reason in _INDEX_ENGINE_BLOCKING_REASONS:
                return_code = 1
            payload = {
                "rewrite": asdict(rewrite) if rewrite is not None else None,
                "compile_commands": asdict(cdb),
                "shards": asdict(shards),
                "health": asdict(health),
                "engine_version": engine_version,
            }
        else:
            result = run_background_index(
                BackgroundIndexConfig(
                    compile_commands_dir=compile_dir,
                    clangd_path=args.clangd,
                    jobs=args.jobs,
                    max_wait_seconds=args.max_wait,
                    poll_interval_seconds=args.poll_interval,
                    stable_rounds=args.stable_rounds,
                )
            )
            payload = {
                "rewrite": asdict(rewrite) if rewrite is not None else None,
                "build": asdict(result),
            }
            if result.health_report.reason in _BUILD_INDEX_BLOCKING_REASONS:
                return_code = 1
    except (
        FileNotFoundError,
        NotADirectoryError,
        OSError,
        json.JSONDecodeError,
        ValueError,
    ) as exc:
        reason = getattr(exc, "reason", None)
        if not isinstance(reason, str):
            reason = (
                "index_health_error"
                if isinstance(exc, PermissionError)
                else "invalid_input"
            )
        _dump_json(
            {
                "error": f"{type(exc).__name__}: {exc}",
                "health": "unknown",
                "reason": reason,
            }
        )
        return 1

    _dump_json(payload)
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
