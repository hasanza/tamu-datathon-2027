---
paths:
  - "src/control_tower/understanding/**"
  - "src/control_tower/llm/**"
---
# LLM zone rules

- All model calls go through `control_tower.llm.adapter` (`complete_json(schema, system, user, purpose)`); never call a provider SDK directly elsewhere.
- Structured output only: the response must validate against a Pydantic model; on failure retry once with the validation error, then mark low confidence.
- The LLM proposes; code disposes. Extracted ids and dates are re-resolved and re-validated by `understanding/resolve.py` against the data.
- Log every call: provider, model id, purpose, input/output tokens, cost. The run writes `runs/<run>/models.json`.
- Cache responses by SHA-256 of (model, system, user) under `cache/llm/`; `--replay-llm` must reproduce a run with no network.
- Keep the stable prompt prefix (handbook summary, alias table, schema) first and byte-identical across calls so provider caching works.
- Never include the expected category of a known event in a prompt or fixture. Few-shot examples must be synthetic, not the 15 events.
