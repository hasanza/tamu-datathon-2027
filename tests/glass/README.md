Tests for GLASS-owned code (`src/control_tower/mcp/`, `api/`). Run with the rest via `uv run pytest`.
Must run offline: mock the enterprise server with `httpx.MockTransport` or a tiny in-process `Enterprise` instance.
