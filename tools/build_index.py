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


def _dump_json(payload: object) -> None:
    json.dump(payload, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build CodeGraph clangd background-index and emit index_health."
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
            "Explicitly attest a healthy legacy cache with --clangd; requires "
            "--inspect-only and never launches clangd for indexing."
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
            cdb = summarize_compile_commands(compile_dir)
            shards = scan_index_shards(index_dir_for_compile_commands_dir(compile_dir))
            engine_version = detect_clangd_version(args.clangd)
            if engine_version is None:
                health = replace(
                    evaluate_index_health(
                        cdb,
                        shards,
                        check_engine_ownership=True,
                    ),
                    health=IndexHealth.UNKNOWN,
                    reason="index_engine_unavailable",
                )
                return_code = 1
            else:
                health = (
                    stamp_existing_index(compile_dir, args.clangd)
                    if args.stamp_existing_index
                    else evaluate_index_health(
                        cdb,
                        shards,
                        expected_engine_version=engine_version,
                        check_engine_ownership=True,
                    )
                )
                if args.stamp_existing_index:
                    shards = scan_index_shards(
                        index_dir_for_compile_commands_dir(compile_dir)
                    )
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
    except (
        FileNotFoundError,
        NotADirectoryError,
        json.JSONDecodeError,
        ValueError,
    ) as exc:
        _dump_json(
            {
                "error": f"{type(exc).__name__}: {exc}",
                "health": "unknown",
                "reason": "invalid_input",
            }
        )
        return 1

    _dump_json(payload)
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
