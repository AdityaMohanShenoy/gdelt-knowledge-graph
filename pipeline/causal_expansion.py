"""Phase 11: recursive expansion. An accepted cause becomes the next target.

Each node the expansion reaches gets a search status, so "we looked and found
nothing" never reads like "nobody looked":

- PARENTS_FOUND: judged, and at least one cause was accepted.
- NO_SUPPORTED_PARENT_FOUND: candidates were judged and all rejected, or the
  corpus held no candidate at all.
- NOT_YET_REVIEWED: reached, but its candidates are not judged yet.
- UNVERIFIABLE: an announced or otherwise unasserted event; nothing that has
  not happened can be shown to have causes.
- OUT_OF_SCOPE: before 2024-01-01, where the plan stops a branch. Not one of the
  plan's four statuses; folding it into NOT_YET_REVIEWED would say someone
  still means to look.

Nodes are canonical events and conditions, so branches that reach the same
cause converge on one node instead of duplicating it.
"""

import datetime as dt
from collections import Counter

START = dt.date(2024, 1, 1)
STATUSES = (
    "PARENTS_FOUND",
    "NO_SUPPORTED_PARENT_FOUND",
    "NOT_YET_REVIEWED",
    "UNVERIFIABLE",
    "OUT_OF_SCOPE",
)


def node_day(node: dict) -> dt.date:
    """An event's best date; a condition's start where the text states one,
    else the day it was first reported (its fallback start is a guess)."""
    if "canonical_condition_id" in node:
        text = node["valid_from"] if node["valid_from_stated"] else node["observed"][0]
    else:
        text = node["best_time"]
    return dt.date.fromisoformat(text)


def stop_reason(node: dict) -> str | None:
    """Why a reached node is not expanded, or None when it should be."""
    if node_day(node) < START:
        return "OUT_OF_SCOPE"
    if "canonical_event_id" in node and node["status"] != "asserted":
        return "UNVERIFIABLE"
    return None


def frontier(edges: list[dict], expanded: set[str], nodes: dict) -> tuple[list[str], dict]:
    """Accepted causes not yet expanded: the ones to expand next, and the ones
    stopped with their reason."""
    reached = sorted(
        {e["source_event_id"] for e in edges if e["review_status"] == "ACCEPTED"} - expanded
    )
    stopped = {n: r for n in reached if (r := stop_reason(nodes[n]))}
    return [n for n in reached if n not in stopped], stopped


def statuses(nodes_reached: set[str], targets: set[str], claims: list[dict],
             edges: list[dict], stopped: dict) -> dict[str, str]:
    """The search status of every reached node."""
    judged = {e["claim_id"] for e in edges}
    accepted = {e["target_event_id"] for e in edges if e["review_status"] == "ACCEPTED"}
    pending = {c["effect_event_id"] for c in claims if c["claim_id"] not in judged}
    out = {}
    for node in sorted(nodes_reached):
        if node in stopped:
            out[node] = stopped[node]
        elif node in accepted:
            out[node] = "PARENTS_FOUND"
        elif node in pending or node not in targets:
            out[node] = "NOT_YET_REVIEWED"
        else:
            out[node] = "NO_SUPPORTED_PARENT_FOUND"
    return out


def find_cycle(edges: list[dict]) -> list[str] | None:
    """A cycle among accepted edges (cause -> effect), or None. Causes are never
    dated after their effects, but same-day edges could still loop."""
    graph: dict[str, list[str]] = {}
    for e in edges:
        if e["review_status"] == "ACCEPTED":
            graph.setdefault(e["source_event_id"], []).append(e["target_event_id"])
    colour: dict[str, int] = {}
    for root in sorted(graph):
        if colour.get(root):
            continue
        stack = [(root, iter(graph.get(root, [])))]
        path = [root]
        colour[root] = 1
        while stack:
            node, children = stack[-1]
            child = next(children, None)
            if child is None:
                colour[node] = 2
                stack.pop()
                path.pop()
            elif colour.get(child) == 1:
                return path[path.index(child):] + [child]
            elif not colour.get(child):
                colour[child] = 1
                stack.append((child, iter(graph.get(child, []))))
                path.append(child)
    return None


def depths(edges: list[dict], seeds: set[str]) -> dict[str, int]:
    """Each node's shortest distance, in accepted edges, from a protest seed."""
    parents: dict[str, list[str]] = {}
    for e in edges:
        if e["review_status"] == "ACCEPTED":
            parents.setdefault(e["target_event_id"], []).append(e["source_event_id"])
    depth = {s: 0 for s in seeds}
    level = sorted(seeds)
    while level:
        nxt = []
        for node in level:
            for p in parents.get(node, []):
                if p not in depth:
                    depth[p] = depth[node] + 1
                    nxt.append(p)
        level = sorted(nxt)
    return depth


def convergence(edges: list[dict]) -> Counter:
    """How many effects each accepted cause explains; above 1 is a shared node."""
    return Counter(e["source_event_id"] for e in edges if e["review_status"] == "ACCEPTED")
