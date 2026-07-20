# CodeGraph MCP Server

Phase 9 provides a stdio-only MCP adapter over the five public CodeGraph query APIs. It does not
contain routing, filtering, credibility, or fallback logic.

## Install

Install the optional MCP dependency into the project environment:

```bash
uv pip install --python .venv/bin/python -r requirements-mcp.txt
```

## Configure

The server receives one operator-owned build configuration at startup. `build_config_id` is injected
from this file and is not exposed as a tool parameter.

```json
{
  "build_config": {
    "build_config_id": "rw-arm-clangd18",
    "compile_commands_dir": "/path/to/version-specific-cdb",
    "source_roots": ["/path/to/source"],
    "clangd_path": "/path/to/clangd",
    "background_index": true,
    "index_ready_probe_symbol": "known_cross_tu_symbol",
    "index_ready_probe_path_suffix": "implementation.c",
    "active_config": "target",
    "index_scope": "indexed_project"
  },
  "allowed_read_roots": ["/path/to/source"]
}
```

`allowed_read_roots` applies only to file paths supplied by the agent. CodeGraph result paths are
serialized unchanged, including legitimate system-header and sysroot locations outside those roots.
Use a version-owned, committed index cache as described by the index builder; an unverified cache is
handled conservatively by the core library.

## Run

Configure the MCP client to launch:

```bash
.venv/bin/python -m codegraph.mcp_server --config /path/to/mcp-config.json
```

The process uses stdout exclusively for MCP stdio frames and sends logs to stderr. It does not open a
network listener. The registered tools are `search`, `definition`, `references`, `callers`, and
`callees`; `impact` is intentionally absent from the MVP.

Each tool schema is closed. Unknown parameters, hidden-configuration attempts such as a forged
`build_config_id`, and missing required parameters are rejected as structured `invalid_params`
results before SDK type conversion or any CodeGraph API call.

Every tool returns the complete `QueryResult` JSON, including credibility, candidates, notes, and
engine version. `syntactic_candidates` are heuristic only, carry
`consumer_warning=not_evidence`, and must not be used as deterministic evidence.
