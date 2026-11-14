import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from causal_query import Graph, explain, ground, label, without_unchecked_implied  # noqa: E402


def node(nid, description, kind="event", date="2024-08-17", status="PARENTS_FOUND", actors=()):
    return {"id": nid, "kind": kind, "description": description, "date": date,
            "search_status": status, "actors": list(actors), "locations": []}


def edge(source, target, relation, strength, quote, level=1, quality="explicit", outlets=1):
    return {"id": f"e:{source}>{target}", "source": source, "target": target,
            "relation": relation, "strength": strength, "evidence_quality": quality,
            "corroboration_count": outlets, "temporal_gap_days": 1, "expansion_level": level,
            "evidence": [{"article_id": "1", "start": 0, "end": len(quote), "text": quote}],
            "source_urls": [f"https://example.test/{target[3:]}"],
            "claim_ids": [f"cl:{source}{target}"]}


GRAPH = Graph({
    "nodes": [
        node("ce:boycott", "Doctors boycotted work in protest"),
        node("ce:killing", "rape and murder", date="2024-08-09"),
        node("ce:ima", "IMA call for a one-day boycott"),
        node("cc:violence", "violence against women", kind="condition", date=None,
             status="NO_SUPPORTED_PARENT_FOUND"),
        node("ce:camp", "Farmers camping", status="NOT_YET_REVIEWED", actors=["Farmers"]),
        node("ce:march", "farmers began the march", actors=["farmers"]),
        node("ce:rally", "doctors protest rally in Delhi", date="2024-12-01"),
        node("ce:fees", "fee hike for doctors", date="2024-11-01"),
    ],
    "edges": [
        edge("ce:killing", "ce:boycott", "TRIGGERS", 1.0, "in protest against the rape and murder"),
        edge("ce:ima", "ce:boycott", "MOBILIZES", 1.0, "in response to a call from the IMA"),
        edge("cc:violence", "ce:killing", "MOTIVATES", 2 / 3, "focused on violence against women",
             level=2),
        edge("ce:march", "ce:camp", "TRIGGERS", 1.0, "camping since the march was stopped"),
        edge("ce:fees", "ce:rally", "MOTIVATES", 1.0, "doctors rallied against the fee hike"),
    ],
})


def test_a_question_grounds_to_the_events_it_names():
    g = ground(GRAPH, "Why did doctors in Salem boycott work?")
    assert g["status"] == "ok" and g["targets"][0] == "ce:boycott"
    assert ground(GRAPH, "quantum physics")["status"] == "no_match"


def test_several_matching_clusters_are_asked_back_not_guessed():
    asked = ground(GRAPH, "why did doctors protest")
    assert asked["status"] == "clarify" and len(asked["options"]) == 2
    chosen = ground(GRAPH, "why did doctors protest", cluster=asked["options"][0]["cluster"])
    assert chosen["status"] == "ok"


def test_explanations_cite_only_relations_the_graph_holds():
    r = explain(GRAPH, "Why did doctors in Salem boycott work?")
    assert r["status"] == "ok"
    held = {(e["source"], e["target"], e["relation"]) for e in GRAPH.edges.values()}
    for path in r["paths"]:
        for e in path["edges"]:
            assert (e["source"], e["target"], e["relation"]) in held
            assert e["evidence"][0]["text"] in path["text"]  # the quote is the record's own
    # Strong, explicit, direct causes rank above the two-step chain.
    assert [p["nodes"][0]["id"] for p in r["paths"]][:2] == ["ce:ima", "ce:killing"]
    assert r["coverage"]["direct_shown"] == r["coverage"]["direct_total"] == 2
    assert 0 < r["coverage"]["strength_share"] <= 1


def test_coverage_names_what_nobody_searched():
    r = explain(GRAPH, "why are farmers camping", node="ce:camp")
    assert [n["id"] for n in r["coverage"]["not_searched"]] == ["ce:camp"]
    assert explain(GRAPH, "", node="ce:missing")["status"] == "no_match"


def test_answers_are_deterministic_and_labels_drop_repeated_actors():
    q = "Why did doctors in Salem boycott work?"
    assert explain(GRAPH, q) == explain(GRAPH, q)
    assert label({"kind": "event", "actors": ["the ED", "ED"],
                  "description": "the ED, ED arrested"}) == "ED arrested"


def test_effects_read_the_same_graph_downstream():
    asked = explain(GRAPH, "what did the violence against women lead to", direction="effects")
    assert asked["status"] == "ok" and asked["scope_note"]
    r = explain(GRAPH, "", node="cc:violence", direction="effects")
    assert r["direction"] == "effects"
    # violence -> killing -> boycott: the chain is reported cause first, ending downstream.
    chains = [[n["id"] for n in p["nodes"]] for p in r["paths"]]
    assert ["cc:violence", "ce:killing", "ce:boycott"] in chains
    held = {(e["source"], e["target"]) for e in GRAPH.edges.values()}
    assert all((e["source"], e["target"]) in held for p in r["paths"] for e in p["edges"])
    assert r["coverage"]["not_searched"] == []  # search status is about causes only
    assert explain(GRAPH, "", node="ce:boycott", direction="effects")["paths"] == []



def test_default_view_hides_only_unchecked_implied_links():
    data = {"nodes": [node("ce:a", "a"), node("ce:b", "b"), node("ce:c", "c"), node("ce:d", "d")],
            "edges": [edge("ce:a", "ce:b", "TRIGGERS", 1.0, "q"),
                      edge("ce:c", "ce:b", "MOTIVATES", 1 / 3, "q", quality="implicit"),
                      {**edge("ce:d", "ce:b", "MOTIVATES", 1 / 3, "q", quality="implicit"),
                       "human_verified": True}]}
    view = without_unchecked_implied(data)
    assert [e["source"] for e in view["edges"]] == ["ce:a", "ce:d"]
    assert view["hidden_implied"] == 1
    assert len(data["edges"]) == 3  # the published graph itself is untouched
