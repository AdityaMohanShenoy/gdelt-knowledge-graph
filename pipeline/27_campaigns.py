"""Campaign layer, prototype: fold episodes of one continuing protest into a campaign.

    .venv/bin/python pipeline/27_campaigns.py candidates --out-dir <dir>
    .venv/bin/python pipeline/27_campaigns.py build --decisions <dir>/decisions.jsonl \\
      --key <dir>/key.json --ranges <dir>/ranges.json

Reads the published graph (`out/causal_graph.json`) and never writes it or the
store. `candidates` reads each protest event's stated duration and pairs protest
events within each story (weakly connected cluster) for judging. `build` turns
judged-same pairs into campaign nodes and writes a prototype graph beside the
evidence, with a before/after report. Prototype scope: the clusters named in
`CLUSTERS`.
"""

import argparse
import datetime as dt
import itertools
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from campaigns import duration, fold_campaigns  # noqa: E402
from canonical_events import anchor_date  # noqa: E402

from causal_query import Graph, label  # noqa: E402

E = ROOT / "data/evidence/events/protest-review-300"
OUT = ROOT / "data/evidence/graph"
# ponytail: prototype on four stories chosen by hand (farmers, RG Kar doctors,
# Haryana doctors, Ladakh); a full run would take every cluster.
CLUSTERS = ("ce:db65f54bc509bb1f", "ce:1c9714262caaa706", "ce:695b49317dcd0683",
            "ce:ca089a8797b52d87")


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def context():
    graph = Graph.load(ROOT / "out/causal_graph.json")
    gold = ROOT / "data/evidence/focal_events/protest-review-300.weak.v3.annotations.jsonl"
    articles = {a["article_id"]: a for a in rows(gold)}
    events = {e["canonical_event_id"]: e for e in rows(Path(f"{E}.canonical.v4.jsonl"))}
    mentions = {m["event_mention_id"]: m for m in rows(Path(f"{E}.conditions.v1.mentions.jsonl"))}
    return graph, articles, events, mentions


def node_reports(node: dict, events: dict, mentions: dict, articles: dict) -> list[dict]:
    """The mentions behind a graph node, including the nodes merged into it."""
    out = []
    for eid in [node["id"], *node.get("merged_from", [])]:
        for mid in events.get(eid, {}).get("mentions", []):
            m = mentions[mid]
            a = articles[m["source_article_id"]]
            out.append({"sentence": a["article_text"][m["evidence_start"]:m["evidence_end"]],
                        "headline": a["headline"], "report": anchor_date(a)})
    return out


def candidates(args: argparse.Namespace) -> dict:
    graph, articles, events, mentions = context()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    clusters = {graph.component[n] for n in CLUSTERS}
    protest = sorted(n for n, c in graph.component.items()
                     if c in clusters and n in events and events[n]["event_type"] == "14")
    ranges, cards = {}, {}
    for n in protest:
        reports = node_reports(graph.nodes[n], events, mentions, articles)
        best = dt.date.fromisoformat(events[n]["best_time"])
        report = max(r["report"] for r in reports)
        ranges[n] = duration([r["sentence"] for r in reports], best, report)
        cards[n] = {"label": label(graph.nodes[n]), "date": events[n]["best_time"],
                    "date_confidence": events[n]["time_confidence"],
                    "stated_range": ranges[n] if ranges[n]["stated"] else None,
                    "actors": events[n]["actors"], "locations": events[n]["locations"],
                    "sentences": sorted({r["sentence"] for r in reports})[:4],
                    "headlines": sorted({r["headline"] for r in reports})[:3]}
    pairs, key = [], {}
    for i, (a, b) in enumerate(
            (p for p in itertools.combinations(protest, 2)
             if graph.component[p[0]] == graph.component[p[1]]), 1):
        pid = f"c{i:03d}"
        key[pid] = {"a": a, "b": b}
        pairs.append({"pair_id": pid, "event_1": cards[a], "event_2": cards[b]})
    with (args.out_dir / "pairs.jsonl").open("x") as h:
        for p in pairs:
            h.write(json.dumps(p, ensure_ascii=False) + "\n")
    (args.out_dir / "key.json").write_text(json.dumps(key, indent=1))
    (args.out_dir / "ranges.json").write_text(json.dumps(ranges, indent=1))
    return {"protest_events": len(protest), "pairs": len(pairs),
            "stated_ranges": sum(r["stated"] for r in ranges.values()),
            "ongoing_wording": sum(r["basis"] == "ongoing wording" for r in ranges.values())}


def fold_edges(edges: list[dict], alias: dict) -> tuple[list[dict], list[str]]:
    """Edges after episodes fold into campaigns: parallel edges join, a link
    between two episodes of one campaign disappears into it."""
    groups: dict[tuple, list[dict]] = {}
    inside = []
    for e in edges:
        s, t = alias.get(e["source"], e["source"]), alias.get(e["target"], e["target"])
        if s == t:
            inside.append(e["id"])
            continue
        groups.setdefault((s, t), []).append(e)
    out = []
    for (s, t), group in sorted(groups.items()):
        lead = min(group, key=lambda e: (-(e["strength"] or 0), e["id"]))
        out.append({**lead, "source": s, "target": t,
                    "claim_ids": sorted({c for e in group for c in e["claim_ids"]}),
                    "evidence": [x for e in group for x in e["evidence"]],
                    "source_urls": sorted({u for e in group for u in e["source_urls"]}),
                    "review_history": [h for e in group for h in e["review_history"]],
                    "human_verified": all(e.get("human_verified") for e in group),
                    "folded_edges": sorted(e["id"] for e in group)})
    return out, sorted(inside)


def build(args: argparse.Namespace) -> dict:
    graph = Graph.load(ROOT / "out/causal_graph.json")
    key = json.loads(args.key.read_text())
    ranges = json.loads(args.ranges.read_text())
    judged = [key[d["pair_id"]] for d in map(json.loads, args.decisions.read_text().splitlines())
              if d["decision"] == "same_campaign"]
    # A verified link saying one caused, organised or prompted the other already says
    # they are two things; only "escalates into" (an earlier stage of the same
    # action) can sit inside a campaign.
    distinct = {frozenset((e["source"], e["target"])) for e in graph.data["edges"]
                if e["relation"] != "ESCALATES"}
    blocked = [p for p in judged if frozenset((p["a"], p["b"])) in distinct]
    same = [p for p in judged if p not in blocked]
    parent = {n: n for p in same for n in (p["a"], p["b"])}

    def find(n: str) -> str:
        while parent[n] != n:
            parent[n] = parent[parent[n]]
            n = parent[n]
        return n

    members: dict[str, set] = {n: {n} for n in parent}
    refused = []
    for p in same:
        ra, rb = find(p["a"]), find(p["b"])
        if ra == rb:
            continue
        # Never join two groups if that would put a distinct pair in one campaign.
        if any(frozenset((x, y)) in distinct for x in members[ra] for y in members[rb]):
            refused.append(p)
            continue
        parent[ra] = rb
        members[rb] |= members.pop(ra)
    groups: dict[str, list[str]] = {}
    for n in parent:
        groups.setdefault(find(n), []).append(n)
    groups = {k: v for k, v in groups.items() if len(v) > 1}
    camps = fold_campaigns(list(groups.values()), graph.nodes, ranges,
                           {n: label(graph.nodes[n]) for n in parent})
    alias = {m: cid for cid, c in camps.items() for m in c["episodes"]}
    edges, inside = fold_edges(graph.data["edges"], alias)
    used = {e["source"] for e in edges} | {e["target"] for e in edges}
    nodes = [n for nid, n in graph.nodes.items() if nid in used and nid not in alias]
    nodes += [c for cid, c in camps.items() if cid in used]
    proto = {**{k: v for k, v in graph.data.items() if k not in ("nodes", "edges", "version")},
             "graph_schema": "causal-graph.v1+campaigns-prototype",
             "based_on": graph.version,
             "nodes": sorted(nodes, key=lambda n: n["id"]),
             "edges": sorted(edges, key=lambda e: e["id"])}
    path = OUT / "causal-graph.campaigns-prototype.json"
    path.write_text(json.dumps(proto, ensure_ascii=False, sort_keys=True, indent=None) + "\n")
    campaigns_out = OUT / "campaigns.prototype.jsonl"
    campaigns_out.write_text("".join(json.dumps(c, ensure_ascii=False) + "\n"
                                     for c in sorted(camps.values(), key=lambda c: c["id"])))
    name = lambda n: label(graph.nodes[n])  # noqa: E731
    return {"judged_same": len(judged),
            "blocked_by_verified_link": [[name(p["a"]), name(p["b"])] for p in blocked],
            "refused_transitive": [[name(p["a"]), name(p["b"])] for p in refused],
            "campaigns": len(camps), "episodes_folded": len(alias),
            "edges_before": len(graph.edges), "edges_after": len(edges),
            "nodes_before": len(graph.nodes), "nodes_after": len(nodes),
            "links_inside_campaigns": inside,
            "campaign_nodes": [{"id": c["id"], "label": c["description"],
                                "range": c["date_range"], "stated": c["range_stated"],
                                "episodes": [label(graph.nodes[m]) for m in c["episodes"]]}
                               for c in camps.values()],
            "graph": str(path)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    c = commands.add_parser("candidates")
    c.add_argument("--out-dir", type=Path, required=True)
    b = commands.add_parser("build")
    for name in ("decisions", "key", "ranges"):
        b.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    result = candidates(args) if args.command == "candidates" else build(args)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
