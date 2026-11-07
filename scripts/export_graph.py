"""Export the ontology diagram (Mermaid) and the full knowledge graph (GraphML) for the submission and the UI."""

import sys
from pathlib import Path

from control_tower.data.loader import REPO_ROOT, load_world
from control_tower.graph.ontology import build_graph, ontology_mermaid, stats, to_graphml


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO_ROOT / "build"
    (REPO_ROOT / "docs").mkdir(exist_ok=True)
    (REPO_ROOT / "docs" / "ontology.mmd").write_text(ontology_mermaid())
    print("wrote docs/ontology.mmd")
    g = build_graph(load_world())
    to_graphml(g, out / "knowledge_graph.graphml")
    print("wrote", out / "knowledge_graph.graphml", stats(g))


if __name__ == "__main__":
    main()
