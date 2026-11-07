"""Export the contracts as JSON Schema for the UI (TypeScript types) and for docs/contracts.md."""

import json
from pathlib import Path

from control_tower.schemas import Action, IncidentSpec, Trace

OUT = Path(__file__).resolve().parents[1] / "docs" / "schemas"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for model in (IncidentSpec, Action, Trace):
        path = OUT / f"{model.__name__}.schema.json"
        path.write_text(json.dumps(model.model_json_schema(by_alias=True), indent=2) + "\n")
        print("wrote", path.relative_to(OUT.parents[1]))


if __name__ == "__main__":
    main()
