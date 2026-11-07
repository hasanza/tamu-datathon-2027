"""The only place that talks to a model provider.

complete_json(schema, system, user, purpose) -> (parsed dict validated against schema, LLMCall usage record)

- Providers: "gemini" (google-genai) and "anthropic" (anthropic SDK). Selected by LLM_PROVIDER or per call.
- Structured output: the provider is asked for JSON matching the schema; the result is validated with
  Pydantic. On validation failure we retry once with the error appended, then raise LLMValidationError.
- Cache: sha256(provider, model, system, user, schema) -> cache/llm/<hash>.json.
  LLM_REPLAY_ONLY=1 forbids network.
- Usage: every call appends an LLMCall to the module Ledger; `Ledger.write(path)` produces
  runs/<run>/models.json.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError

from control_tower.schemas.trace import LLMCall

REPO_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(REPO_ROOT / ".env")

DEFAULT_MODELS = {
    "gemini": os.environ.get("GEMINI_MODEL") or "gemini-3.8-flash",
    "anthropic": os.environ.get("ANTHROPIC_MODEL") or "claude-haiku-5-5",
}
# USD per 1M tokens (input, output). Gemini prices are filled in from the provider's pricing page before
# the final run; until then they are None and cost_usd is 0.0 while token counts stay exact.
PRICES: dict[str, tuple[float, float] | None] = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
    "gemini-3.8-flash": None,
    "gemini-3.5-flash-lite": None,
}


class LLMError(RuntimeError):
    pass


class LLMValidationError(LLMError):
    pass


class LLMReplayMiss(LLMError):
    pass


@dataclass
class RawResponse:
    text: str
    input_tokens: int
    output_tokens: int


class Backend(Protocol):
    name: str

    def generate_json(self, model: str, system: str, user: str, schema: dict[str, Any]) -> RawResponse: ...


class GeminiBackend:
    name = "gemini"

    def __init__(self) -> None:
        from google import genai

        key = os.environ.get("GEMINI_API_KEY")
        if not key:
            raise LLMError("GEMINI_API_KEY is not set (see .env.example)")
        self._client = genai.Client(api_key=key)

    def generate_json(self, model: str, system: str, user: str, schema: dict[str, Any]) -> RawResponse:
        from google.genai import types

        config = types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_json_schema=schema,
        )
        resp = self._client.models.generate_content(model=model, contents=user, config=config)
        usage = resp.usage_metadata
        return RawResponse(
            text=resp.text or "",
            input_tokens=int(getattr(usage, "prompt_token_count", 0) or 0),
            output_tokens=int(getattr(usage, "candidates_token_count", 0) or 0),
        )


class AnthropicBackend:
    name = "anthropic"

    def __init__(self) -> None:
        import anthropic

        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise LLMError("ANTHROPIC_API_KEY is not set (see .env.example)")
        self._client = anthropic.Anthropic()

    def generate_json(self, model: str, system: str, user: str, schema: dict[str, Any]) -> RawResponse:
        resp = self._client.messages.create(
            model=model,
            max_tokens=4096,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={"format": {"type": "json_schema", "schema": schema}},
        )
        text = "".join(block.text for block in resp.content if block.type == "text")
        return RawResponse(
            text=text,
            input_tokens=int(resp.usage.input_tokens),
            output_tokens=int(resp.usage.output_tokens),
        )


@dataclass
class Ledger:
    calls: list[LLMCall] = field(default_factory=list)

    @property
    def total_cost_usd(self) -> float:
        return round(sum(c.cost_usd for c in self.calls), 6)

    def write(self, path: Path) -> None:
        by_model: dict[str, dict[str, Any]] = {}
        for c in self.calls:
            m = by_model.setdefault(
                f"{c.provider}/{c.model}",
                {
                    "provider": c.provider,
                    "model": c.model,
                    "calls": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cost_usd": 0.0,
                },
            )
            m["calls"] += 1
            m["input_tokens"] += c.input_tokens
            m["output_tokens"] += c.output_tokens
            m["cost_usd"] = round(m["cost_usd"] + c.cost_usd, 6)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"models": list(by_model.values()), "total_cost_usd": self.total_cost_usd}, indent=2) + "\n"
        )


LEDGER = Ledger()
_BACKENDS: dict[str, Backend] = {}


def _backend(provider: str) -> Backend:
    if provider not in _BACKENDS:
        if provider == "gemini":
            _BACKENDS[provider] = GeminiBackend()
        elif provider == "anthropic":
            _BACKENDS[provider] = AnthropicBackend()
        else:
            raise LLMError(f"unknown LLM_PROVIDER {provider!r}")
    return _BACKENDS[provider]


def register_backend(provider: str, backend: Backend) -> None:
    """Tests inject fake backends here."""
    _BACKENDS[provider] = backend


def _cost(model: str, inp: int, out: int) -> float:
    price = PRICES.get(model)
    if not price:
        return 0.0
    return round(inp / 1e6 * price[0] + out / 1e6 * price[1], 6)


def _cache_dir() -> Path:
    return Path(os.environ.get("LLM_CACHE_DIR") or REPO_ROOT / "cache" / "llm")


def _cache_key(provider: str, model: str, system: str, user: str, schema: dict[str, Any]) -> str:
    blob = json.dumps([provider, model, system, user, schema], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode()).hexdigest()


def complete_json[T: BaseModel](
    schema: type[T],
    system: str,
    user: str,
    purpose: str,
    *,
    provider: str | None = None,
    model: str | None = None,
    use_cache: bool = True,
) -> tuple[T, LLMCall]:
    """Ask the model for an object matching `schema`; return the validated instance and the usage record."""
    provider = provider or os.environ.get("LLM_PROVIDER", "gemini")
    model = model or DEFAULT_MODELS[provider]
    json_schema = schema.model_json_schema()
    key = _cache_key(provider, model, system, user, json_schema)
    cache_path = _cache_dir() / f"{key}.json"

    if use_cache and cache_path.exists():
        cached = json.loads(cache_path.read_text())
        parsed = schema.model_validate(cached["parsed"])
        call = LLMCall(**cached["usage"], cached=True)
        LEDGER.calls.append(call)
        return parsed, call

    if os.environ.get("LLM_REPLAY_ONLY") == "1":
        raise LLMReplayMiss(f"no cached response for {purpose} ({key[:12]}) and LLM_REPLAY_ONLY=1")

    backend = _backend(provider)
    attempt_user, last_error = user, None
    total_in = total_out = 0
    for _attempt in range(2):
        t0 = time.perf_counter()
        raw = backend.generate_json(model, system, attempt_user, json_schema)
        total_in += raw.input_tokens
        total_out += raw.output_tokens
        try:
            parsed = schema.model_validate_json(raw.text)
        except ValidationError as e:
            last_error = e
            attempt_user = (
                f"{user}\n\nYour previous answer did not match the schema. Error:\n{e}\n"
                "Return only a JSON object that validates."
            )
            continue
        call = LLMCall(
            provider=provider,
            model=model,
            purpose=purpose,  # type: ignore[arg-type]
            input_tokens=total_in,
            output_tokens=total_out,
            cost_usd=_cost(model, total_in, total_out),
            cached=False,
        )
        LEDGER.calls.append(call)
        if use_cache:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(
                json.dumps(
                    {
                        "provider": provider,
                        "model": model,
                        "purpose": purpose,
                        "latency_s": round(time.perf_counter() - t0, 3),
                        "parsed": parsed.model_dump(mode="json"),
                        "usage": call.model_dump(exclude={"cached"}),
                    },
                    indent=2,
                )
                + "\n"
            )
        return parsed, call
    raise LLMValidationError(f"{provider}/{model} returned invalid {schema.__name__} twice: {last_error}")
