"""Saved data for the demo page: featured answers and the journey.

    .venv/bin/python pipeline/41_demo_snapshots.py            # both files
    .venv/bin/python pipeline/41_demo_snapshots.py --only featured

frontend/demo-featured.json: the real query engine's answers to the featured questions on the
published graph (default view: unchecked implied links hidden); the page shows them only when
a live call fails.

frontend/demo-journey.json: one real story (the farmers' 'Delhi Chalo' march, Feb 2024) followed
from its GDELT records to the graph, plus a compact copy of the whole graph for the animation.
The journey needs the local GDELT universe (data/working/india-2024), the article store
($ARTICLE_DATABASE_URL) and the extraction review records, so it only runs where those exist.

Rerun after every graph publish; tests check both files carry the published graph's version.
"""

import argparse
import asyncio
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from causal_query import Graph, explain, label  # noqa: E402

QUESTIONS = [
    ("Why were farmers protesting at the Punjab-Haryana border in February 2024?", "causes"),
    ("Why did doctors in Kolkata go on hunger strike?", "causes"),
    ("Why did Atishi go on a hunger strike over water?", "causes"),
    ("What did the killing of the trainee doctor in Kolkata lead to?", "effects"),
]

# The story the journey follows.
STORY_URL = ("https://indiapost.com/delhi-chalo-march-police-fire-tear-gas-on-protesting-farmers-"
             "at-punjab-haryana-shambhu-border/")
STORY_DOC = 107618                     # article_documents.document_id of STORY_URL
STORY_MENTIONS = ("107618:2:5", "107618:2:15")   # the march, the tear gas (first sentence)
STORY_EVENT = "ce:030fc1806bae137e"    # graph node: farmer leaders 'Delhi Chalo' march
CAMEO = {"14": "Protest", "17": "Coerce", "141": "Demonstrate or rally",
         "175": "Use tactics of violent repression"}

UNIVERSE = ROOT / "data" / "working" / "india-2024"
MENTION_REVIEW = ROOT / "data" / "evidence" / "scale" / "ext-1700.mentions.review.jsonl"

# Counts measured by the pipeline runs, as reported in docs/measurements/scale_2000.md and the
# paper's tables (funnel, gate, repair, audit). Graph-derived counts are computed below.
MEASURED = {
    "articles": 2000, "kept": 915, "mentions": 7083, "events": 6152, "conditions": 810,
    "claims": 20129, "gate_links": 1352, "gate_removed": 143, "decoys": 1352, "decoys_passed": 44,
    "same_decisions": 151, "merges_blocked": 5, "cycle_links": 11,
    "audit_correct": 89, "audit_decided": 99, "stated_correct": 69, "stated_checked": 69,
}


def featured() -> None:
    graph = Graph.load(ROOT / "out" / "causal_graph.json", implied=False)
    out = {"graph_version": graph.version, "questions": []}
    for question, direction in QUESTIONS:
        answer = explain(graph, question, direction=direction)
        out["questions"].append({"q": question, "direction": direction, "answer": answer})
        print(f"{answer['status']:>8}  {len(answer.get('paths') or [])} paths  {question}")
    path = ROOT / "frontend" / "demo-featured.json"
    path.write_text(json.dumps(out, ensure_ascii=False, sort_keys=True) + "\n")


def gdelt_block() -> dict:
    import duckdb
    manifest = json.loads((UNIVERSE / "manifest.json").read_text())
    con = duckdb.connect()
    events = str(UNIVERSE / "events.parquet")
    protests = con.execute(f"select count(*) from '{events}' where EventRootCode = '14'").fetchone()[0]
    rows = con.execute(
        f"select GlobalEventID, day, EventCode, Actor1Name, Actor2Name from '{events}' "
        "where SOURCEURL = ? order by GlobalEventID", [STORY_URL]).fetchall()
    return {
        "world_2024": manifest["input_rows"], "india_2024": manifest["output_rows"],
        "india_protest_2024": protests,
        "records": [{"id": r[0], "day": str(r[1]), "code": r[2], "code_name": CAMEO.get(r[2], ""),
                     "actor1": r[3], "actor2": r[4]} for r in rows],
    }


async def fetch_article() -> tuple[str, str]:
    import asyncpg
    con = await asyncpg.connect(os.environ["ARTICLE_DATABASE_URL"])
    try:
        row = await con.fetchrow(
            "select title, cleaned_text from article_documents where document_id = $1", STORY_DOC)
    finally:
        await con.close()
    return row["title"], row["cleaned_text"]


def article_block() -> dict:
    title, full = asyncio.run(fetch_article())
    paragraphs = [p.strip() for p in full.split("\n\n") if p.strip()]
    text = "\n\n".join(paragraphs[:2])
    first = paragraphs[0]
    # Token indices in mention ids count from the sentence, after a dateline such as "AMBALA:".
    dateline = re.match(r"^[A-Z][A-Z .]+:\s*", first)
    offset = dateline.end() if dateline else 0
    tokens = [(m.group(), offset + m.start()) for m in re.finditer(r"\w+|[^\w\s]", first[offset:])]
    reviewed = next(json.loads(line) for line in MENTION_REVIEW.open()
                    if json.loads(line)["article_id"] == str(STORY_DOC))
    by_id = {m["mention_id"]: m for m in reviewed["mentions"]}
    spans, events = [], []
    for n, mention_id in enumerate(STORY_MENTIONS):
        m = by_id[mention_id]
        assert m["verdict"] == "accept", mention_id
        word, at = tokens[int(mention_id.split(":")[2])]
        found = [("action", word, at)]
        for role, key in (("actor", "actors"), ("target", "targets"), ("place", "locations")):
            found += [(role, t, first.find(t)) for t in m[key]]
        if m["event_time"]:
            found.append(("time", m["event_time"], first.find(m["event_time"])))
        for role, t, start in found:
            assert start >= 0 and first[start:start + len(t)] == t, (mention_id, t)
            spans.append({"event": n, "role": role, "text": t, "start": start})
        events.append({"code": m["event_type"], "code_name": CAMEO.get(m["event_type"], ""),
                       "actors": m["actors"], "targets": m["targets"], "places": m["locations"],
                       "time": m["event_time"], "action": word})
    return {"url": STORY_URL, "host": "indiapost.com", "title": title.split(" » ")[0],
            "text": text, "spans": sorted(spans, key=lambda s: (s["start"], s["event"])),
            "events": events}


def story_block(graph: Graph) -> dict:
    """The march and the direct causes the live query engine ranks first for it."""
    node = graph.nodes[STORY_EVENT]
    answer = explain(Graph.load(ROOT / "out" / "causal_graph.json", implied=False), "", node=STORY_EVENT)
    causes = []
    for path in answer["paths"]:
        e = graph.edges[path["edges"][-1]["id"]]
        if len(causes) == 3 or any(c["edge_id"] == e["id"] for c in causes):
            continue
        url = e["source_urls"][0]
        causes.append({"edge_id": e["id"], "relation": e["relation"],
                       "cause": label(graph.nodes[e["source"]]), "quote": e["evidence"][0]["text"],
                       "host": re.sub(r"^www\.", "", url.split("/")[2]),
                       "outlets": e["corroboration_count"]})
    # merged_from lists the records folded into this node; the surviving record makes one more.
    return {"event": STORY_EVENT, "label": label(node),
            "records": len(node.get("merged_from") or []) + 1, "causes": causes}


def graph_block(graph: Graph) -> dict:
    ids = sorted(graph.nodes)
    index = {n: i for i, n in enumerate(ids)}
    parent = list(range(len(ids)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    edges = []
    for e in sorted(graph.edges.values(), key=lambda e: e["id"]):
        s, t = index[e["source"]], index[e["target"]]
        parent[find(s)] = find(t)
        edges.append([s, t, 1 if e["evidence_quality"] == "explicit" else 0])
    story = find(index[STORY_EVENT])
    nodes = [[1 if graph.nodes[n].get("kind") == "condition" else 0,
              1 if find(i) == story else 0] for i, n in enumerate(ids)]
    return {"nodes": nodes, "edges": edges, "story_size": sum(n[1] for n in nodes),
            "focus": index[STORY_EVENT]}


def journey() -> None:
    graph = Graph.load(ROOT / "out" / "causal_graph.json", implied=True)
    counts = json.loads((ROOT / "out" / "causal_graph.json").read_text())["counts"]
    measured = {**MEASURED, "merged_away": counts["nodes_merged_away"],
                "self_loops_dropped": len(counts["self_loops_dropped"])}
    out = {"graph_version": graph.version, "measured": measured, "gdelt": gdelt_block(),
           "article": article_block(), "story": story_block(graph), "graph": graph_block(graph),
           "protests_explained": len(graph.seeds)}
    path = ROOT / "frontend" / "demo-journey.json"
    path.write_text(json.dumps(out, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
    print(f"journey: {len(out['gdelt']['records'])} GDELT records, {len(out['article']['spans'])} spans, "
          f"{len(out['story']['causes'])} causes, story of {out['graph']['story_size']} nodes, "
          f"{path.stat().st_size // 1024} KB")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--only", choices=["featured", "journey"])
    args = parser.parse_args()
    if args.only != "journey":
        featured()
    if args.only != "featured":
        journey()


if __name__ == "__main__":
    main()
