"""Per-agent model configuration from `agents.toml` (repo root) with a `CT_MODEL_<AGENT_ID>` env override."""

from __future__ import annotations

import os
import tomllib
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel

CONFIG_PATH = Path(__file__).resolve().parents[3] / "agents.toml"


class AgentConfig(BaseModel):
    provider: str
    model: str
    max_turns: int


@lru_cache(maxsize=1)
def _load(path: str) -> dict[str, dict]:
    with open(path, "rb") as f:
        return tomllib.load(f)


def agent_config(agent_id: str, path: Path | None = None) -> AgentConfig:
    """Config for one agent. `CT_MODEL_<AGENT_ID_UPPER>=provider/model` overrides provider and model
    (a bare `model` keeps the configured provider)."""
    table = _load(str(path or CONFIG_PATH))
    if agent_id not in table:
        raise KeyError(f"agent {agent_id!r} is not configured in agents.toml (known: {sorted(table)})")
    section = table[agent_id]
    provider, model = section["provider"], section["model"]
    override = os.environ.get(f"CT_MODEL_{agent_id.upper()}")
    if override:
        if "/" in override:
            provider, model = override.split("/", 1)
        else:
            model = override
    return AgentConfig(provider=provider, model=model, max_turns=int(section.get("max_turns", 12)))
