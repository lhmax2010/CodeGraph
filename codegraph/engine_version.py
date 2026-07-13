"""clangd version normalization and executable probing."""

from __future__ import annotations

import re
import subprocess
from typing import Any

_CLANGD_VERSION = re.compile(
    r"\bclangd(?:\s+version)?\s+(\d+(?:\.\d+){2})\b", re.IGNORECASE
)
_PLAIN_VERSION = re.compile(r"^\s*(\d+(?:\.\d+){2})\s*$")


def normalize_clangd_version(value: str | None) -> str | None:
    """Return a stable `clangd X.Y.Z` identity including the patch version."""

    if value is None:
        return None
    match = _CLANGD_VERSION.search(value) or _PLAIN_VERSION.match(value)
    return f"clangd {match.group(1)}" if match is not None else None


def clangd_version_from_initialize(result: Any) -> str | None:
    """Extract clangd's version from an LSP initialize result."""

    if not isinstance(result, dict):
        return None
    server_info = result.get("serverInfo")
    if not isinstance(server_info, dict):
        return None
    version = server_info.get("version")
    return normalize_clangd_version(version if isinstance(version, str) else None)


def detect_clangd_version(clangd_path: str, *, timeout: float = 5.0) -> str | None:
    """Probe a clangd executable without raising on an unavailable binary."""

    try:
        completed = subprocess.run(
            [clangd_path, "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return normalize_clangd_version(
        "\n".join(part for part in (completed.stdout, completed.stderr) if part)
    )
