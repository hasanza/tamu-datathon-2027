"""Nobody edits the organizers' world. Hashes were recorded at scaffold time (2026-11-07)."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXPECTED = json.loads((ROOT / "tests" / "fixtures" / "data_hashes.json").read_text())


def test_organizer_files_unchanged() -> None:
    mismatches = []
    for rel, expected in EXPECTED.items():
        actual = hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()
        if actual != expected:
            mismatches.append(rel)
    assert not mismatches, f"organizer files modified: {mismatches}"
