"""Phase 13: answer "why did X happen?" from the compiled causal graph.

    question -> event grounding -> causal subgraph -> path ranking -> explanation

Everything here reads the graph that `pipeline/40_build_graph.py` compiled and
never adds to it. Grounding is lexical (BM25 over each node's own words, its
evidence quotes and its articles' URL slugs), so it runs with the standard
library on the deployed function. The path score orders paths for reading; it
is not a probability, and its weights are fixed and illustrative, as the
Causal Evidence weights were. Prose is filled from edge records, so an
explanation can only state relations the graph holds.
"""

import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path

STOP = frozenset(
    "the a an of in on at to for and or by with from as its their his her this that these those "
    "who which was were is are be been has have had said says did does do why what how when where "
    "after over into against about news article html www com php".split()
)
QUALITY = {"explicit": 1.0, "implicit": 0.7}  # ponytail: fixed weights, ordering only
MAX_DEPTH = 3
CLARIFY_RATIO = 0.8  # a second cluster this close to the best one is ambiguous
CLARIFY_OPTIONS = 5


def tokens(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    return [w[:-1] if len(w) > 4 and w.endswith("s") else w
            for w in words if len(w) > 2 and w not in STOP]


class Graph:
    def __init__(self, data: dict):
        self.data = data
        self.version = data.get("version")
        self.nodes = {n["id"]: n for n in data["nodes"]}
        self.edges = {e["id"]: e for e in data["edges"]}
        self.parents: dict[str, list[dict]] = {}
        self.children: dict[str, list[dict]] = {}
        for e in data["edges"]:
            self.parents.setdefault(e["target"], []).append(e)
            self.children.setdefault(e["source"], []).append(e)
        self.seeds = sorted({e["target"] for e in data["edges"] if e["expansion_level"] == 1})
        self.component = self._components()
        self._index()

    @classmethod
    def load(cls, path: Path) -> "Graph":
        raw = path.read_bytes()
        return cls({**json.loads(raw), "version": hashlib.sha256(raw).hexdigest()})

    def _components(self) -> dict[str, int]:
        """Weakly connected clusters, numbered by their smallest node id."""
        seen: dict[str, int] = {}
        for start in sorted(self.nodes):
            if start in seen:
                continue
            stack, members = [start], set()
            while stack:
                n = stack.pop()
                if n in members:
                    continue
                members.add(n)
                stack += [e["source"] for e in self.parents.get(n, [])]
                stack += [e["target"] for e in self.children.get(n, [])]
            label = len(set(seen.values()))
            seen |= {m: label for m in members}
        return seen

    def _index(self) -> None:
        self.docs: dict[str, Counter] = {}
        for nid, n in self.nodes.items():
            text = [n["description"], *n.get("actors", []), *n.get("holders", []),
                    *n.get("locations", [])]
            urls = list(n.get("source_urls") or [])
            for e in self.parents.get(nid, []):
                text += [s["text"] for s in e["evidence"]]
                urls += e["source_urls"]
            text += [re.sub(r"[-_/]", " ", u.split("/", 3)[-1]) for u in urls]
            self.docs[nid] = Counter(tokens(" ".join(text)))
        self.avg_len = sum(sum(d.values()) for d in self.docs.values()) / max(len(self.docs), 1)
        df = Counter(t for d in self.docs.values() for t in d)
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def relevance(self, question: str) -> dict[str, float]:
        """BM25 score of every node for the question; zero scores are left out."""
        query = set(tokens(question))
        scores = {}
        for nid, doc in self.docs.items():
            length = sum(doc.values())
            score = sum(
                self.idf[t] * doc[t] * 2.2 / (doc[t] + 1.2 * (0.25 + 0.75 * length / self.avg_len))
                for t in query if t in doc)
            if score > 0:
                scores[nid] = round(score, 6)
        return scores


def ground(graph: Graph, question: str, cluster: int | None = None) -> dict:
    """The events a question is about: the best-matching nodes of one cluster.
    Several clusters matching about equally well is a question to ask back."""
    scores = graph.relevance(question)
    if not scores:
        return {"status": "no_match", "query_terms": sorted(set(tokens(question)))}
    best: dict[int, float] = {}
    for nid, s in scores.items():
        c = graph.component[nid]
        best[c] = max(best.get(c, 0.0), s)
    ranked = sorted(best, key=lambda c: (-best[c], c))
    options = [c for c in ranked if best[c] >= CLARIFY_RATIO * best[ranked[0]]]
    if cluster is None and len(options) > 1:
        return {"status": "clarify", "matching_clusters": len(options),
                "options": [cluster_card(graph, c, scores) for c in options[:CLARIFY_OPTIONS]]}
    chosen = ranked[0] if cluster is None else cluster
    if chosen not in best:
        return {"status": "no_match", "query_terms": sorted(set(tokens(question)))}
    top = best[chosen]
    targets = sorted((n for n, s in scores.items()
                      if graph.component[n] == chosen and s >= 0.5 * top),
                     key=lambda n: (-scores[n], n))
    return {"status": "ok", "cluster": chosen, "targets": targets, "scores": scores}


def cluster_card(graph: Graph, cluster: int, scores: dict) -> dict:
    members = [n for n, c in graph.component.items() if c == cluster]
    lead = max((n for n in members if n in scores), key=lambda n: (scores[n], n))
    dates = sorted(d for n in members if (d := node_date(graph.nodes[n])))
    return {"cluster": cluster, "label": label(graph.nodes[lead]),
            "lead_node": lead, "nodes": len(members), "score": round(scores[lead], 4),
            "date_range": [dates[0][:10], dates[-1][:10]] if dates else None}


def label(node: dict) -> str:
    """A readable name for display. Phase 8 describes an event as all its reports'
    actors followed by the action ("ED, the ED, the Enforcement Directorate (ED)
    arrested"); one actor reads better. The record itself is unchanged."""
    actors = node.get("actors") or []
    lead = ", ".join(actors)
    if node["kind"] == "event" and actors and node["description"].startswith(lead):
        action = node["description"][len(lead):].strip()
        return f"{min(actors, key=lambda a: (len(a), a))} {action}".strip()
    return node["description"]


def node_date(node: dict) -> str | None:
    return node.get("date") or (node.get("valid_from") if node.get("valid_from_stated") else None)


def paths_to(graph: Graph, target: str, depth: int = MAX_DEPTH) -> list[list[dict]]:
    """Every cause chain ending at `target`, up to `depth` edges, as edge lists
    ordered cause -> effect. The graph is acyclic, so this terminates."""
    found = []

    def walk(node: str, chain: list[dict]) -> None:
        for e in sorted(graph.parents.get(node, []), key=lambda e: e["id"]):
            path = [e, *chain]
            found.append(path)
            if len(path) < depth:
                walk(e["source"], path)

    walk(target, [])
    return found


def path_score(path: list[dict], relevance: dict[str, float], top: float) -> float:
    """Orders paths: weaker, implicit, single-source links and distance from the
    question all lower it. Not a probability."""
    score = 1.0
    for e in path:
        score *= (e["strength"] or 0) * QUALITY.get(e["evidence_quality"], 0.5)
        score *= 1 + 0.1 * max(0, e["corroboration_count"] - 1)
    nodes = {path[0]["source"], *(e["target"] for e in path)}
    fit = max(relevance.get(n, 0.0) for n in nodes) / top if top else 0.0
    return round(score * (0.5 + 0.5 * fit), 6)


def ancestors(graph: Graph, targets: list[str], depth: int = MAX_DEPTH) -> tuple[set, set]:
    """Nodes and edges within `depth` causal steps above the targets."""
    nodes, edges, level = set(targets), set(), set(targets)
    for _ in range(depth):
        nxt = set()
        for n in level:
            for e in graph.parents.get(n, []):
                edges.add(e["id"])
                if e["source"] not in nodes:
                    nxt.add(e["source"])
        nodes |= nxt
        level = nxt
    return nodes, edges


def explain(graph: Graph, question: str, cluster: int | None = None, k: int = 5,
            node: str | None = None) -> dict:
    """`node` skips grounding: the caller already picked the event (a topic list)."""
    if node is not None:
        if node not in graph.nodes:
            return {"status": "no_match", "question": question, "graph_version": graph.version}
        question = question or f"Why did this happen: {label(graph.nodes[node])}?"
        grounding: dict = {"status": "ok", "cluster": graph.component[node], "targets": [node],
                     "scores": {**graph.relevance(label(graph.nodes[node])), node: 1.0}}
    else:
        grounding = ground(graph, question, cluster)
    if grounding["status"] != "ok":
        return {**grounding, "question": question, "graph_version": graph.version}
    scores, targets = grounding["scores"], grounding["targets"]
    top = max(scores[t] for t in targets)
    candidates = [p for t in targets for p in paths_to(graph, t)]
    ranked = sorted(candidates, key=lambda p: (-path_score(p, scores, top),
                                              [e["id"] for e in p]))
    # Keep the best chain per root cause, so one cause does not fill every slot.
    chosen, roots = [], set()
    for p in ranked:
        if p[0]["source"] in roots:
            continue
        roots.add(p[0]["source"])
        chosen.append(p)
        if len(chosen) == k:
            break
    sub_nodes, sub_edges = ancestors(graph, targets)
    covered = {e["id"] for p in chosen for e in p}
    total = sum(graph.edges[e]["strength"] or 0 for e in sub_edges)
    direct = {e["id"] for t in targets for e in graph.parents.get(t, [])}
    unexplored = sorted(n for n in sub_nodes
                        if graph.nodes[n]["search_status"] not in
                        ("PARENTS_FOUND", "NO_SUPPORTED_PARENT_FOUND"))
    return {
        "status": "ok",
        "question": question,
        "graph_version": graph.version,
        "cluster": grounding["cluster"],
        "targets": [node_card(graph, t, scores) for t in targets],
        "paths": [{"score": path_score(p, scores, top),
                   "nodes": [node_card(graph, n, scores)
                             for n in [p[0]["source"], *(e["target"] for e in p)]],
                   "edges": [edge_card(e) for e in p],
                   "text": sentence(graph, p)} for p in chosen],
        "coverage": {
            # Share of the targets' causal support, by edge strength, that the
            # returned paths account for.
            "strength_share": round(
                sum(graph.edges[e]["strength"] or 0 for e in covered & sub_edges) / total, 4)
            if total else 0.0,
            "direct_causes_shown": len(covered & direct),
            "direct_causes": len(direct),
            "edges_in_subgraph": len(sub_edges),
            "nodes_in_subgraph": len(sub_nodes),
            "not_searched": [node_card(graph, n, scores) for n in unexplored],
        },
        "subgraph": {"nodes": sorted(sub_nodes), "edges": sorted(sub_edges)},
        "labels": {"edges": len(graph.edges),
                   "human_verified": sum(bool(e.get("human_verified"))
                                         for e in graph.edges.values())},
    }


def node_card(graph: Graph, nid: str, scores: dict) -> dict:
    n = graph.nodes[nid]
    return {"id": nid, "kind": n["kind"], "label": label(n), "description": n["description"],
            "date": (node_date(n) or "")[:10] or None, "search_status": n["search_status"],
            "relevance": scores.get(nid, 0.0), "merged_from": n.get("merged_from", [])}


def edge_card(e: dict) -> dict:
    return {**{k: e[k] for k in ("id", "source", "target", "relation", "strength",
                                 "evidence_quality", "corroboration_count", "temporal_gap_days",
                                 "evidence", "source_urls", "claim_ids")},
            "human_verified": bool(e.get("human_verified"))}


VERB = {"TRIGGERS": "triggered", "MOTIVATES": "motivated", "MOBILIZES": "mobilised",
        "ESCALATES": "escalated into", "PROMPTS_RESPONSE": "prompted"}


def sentence(graph: Graph, path: list[dict]) -> str:
    """One sentence per path, filled only from the path's own records."""
    parts = []
    for e in path:
        s, t = graph.nodes[e["source"]], graph.nodes[e["target"]]
        date = node_date(t)
        when = f" ({date[:10]})" if date else ""
        quote = e["evidence"][0]["text"]
        parts.append(
            f"“{label(s)}” {VERB.get(e['relation'], e['relation'].lower())} "
            f"“{label(t)}”{when} [{e['relation']}, strength "
            f"{round((e['strength'] or 0) * 3)}/3, {e['evidence_quality']}, "
            f"{e['corroboration_count']} outlet{'s' if e['corroboration_count'] != 1 else ''}; "
            f"evidence: “{quote}”]")
    return " Then ".join(parts) + "."
