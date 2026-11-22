"""Saved answers for the demo page's featured questions.

    .venv/bin/python pipeline/41_demo_snapshots.py

Runs the real query engine on the published graph (default view: unchecked implied links
hidden) and writes frontend/demo-featured.json. The page shows these only when a live call
fails. Rerun after every graph publish; a test checks the graph version matches.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from causal_query import Graph, explain  # noqa: E402

QUESTIONS = [
    ("Why were farmers protesting at the Punjab-Haryana border in February 2024?", "causes"),
    ("Why did doctors in Kolkata go on hunger strike?", "causes"),
    ("Why did Atishi go on a hunger strike over water?", "causes"),
    ("What did the killing of the trainee doctor in Kolkata lead to?", "effects"),
]


def main() -> None:
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args()
    graph = Graph.load(ROOT / "out" / "causal_graph.json", implied=False)
    out = {"graph_version": graph.version, "questions": []}
    for question, direction in QUESTIONS:
        answer = explain(graph, question, direction=direction)
        out["questions"].append({"q": question, "direction": direction, "answer": answer})
        print(f"{answer['status']:>8}  {len(answer.get('paths') or [])} paths  {question}")
    path = ROOT / "frontend" / "demo-featured.json"
    path.write_text(json.dumps(out, ensure_ascii=False, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
