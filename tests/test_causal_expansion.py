import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

from causal_expansion import (  # noqa: E402
    convergence,
    depths,
    find_cycle,
    frontier,
    statuses,
    stop_reason,
)


def edge(cause, effect, status="ACCEPTED", cid=None):
    return {"claim_id": cid or f"{cause}>{effect}", "source_event_id": cause,
            "target_event_id": effect, "review_status": status}


def event(eid, day, status="asserted"):
    return {"canonical_event_id": eid, "best_time": day, "status": status}


NODES = {
    "ce:protest": event("ce:protest", "2024-03-22"),
    "ce:arrest": event("ce:arrest", "2024-03-21"),
    "ce:rally": event("ce:rally", "2024-03-30", status="announced"),
    "ce:old": event("ce:old", "2021-11-19"),
    "cc:water": {"canonical_condition_id": "cc:water", "valid_from": "2023-12-01",
                 "valid_from_stated": False, "observed": ["2024-06-01"]},
}


def test_branches_stop_before_2024_and_at_unasserted_events():
    assert stop_reason(NODES["ce:old"]) == "OUT_OF_SCOPE"
    assert stop_reason(NODES["ce:rally"]) == "UNVERIFIABLE"
    # A condition's guessed start is not its date; its first report is.
    assert stop_reason(NODES["cc:water"]) is None
    edges = [edge(n, "ce:protest") for n in ("ce:arrest", "ce:rally", "ce:old", "cc:water")]
    nxt, stopped = frontier(edges, {"ce:protest"}, NODES)
    assert nxt == ["cc:water", "ce:arrest"]
    assert stopped == {"ce:old": "OUT_OF_SCOPE", "ce:rally": "UNVERIFIABLE"}


def test_looked_and_found_nothing_differs_from_not_looked():
    edges = [edge("ce:arrest", "ce:protest"), edge("ce:x", "ce:arrest", "REJECTED")]
    claims = [{"claim_id": "ce:x>ce:arrest", "effect_event_id": "ce:arrest"},
              {"claim_id": "ce:y>cc:water", "effect_event_id": "cc:water"}]
    reached = {"ce:protest", "ce:arrest", "cc:water"}
    status = statuses(reached, {"ce:protest", "ce:arrest", "cc:water"}, claims, edges, {})
    assert status == {"ce:protest": "PARENTS_FOUND", "ce:arrest": "NO_SUPPORTED_PARENT_FOUND",
                      "cc:water": "NOT_YET_REVIEWED"}


def test_converging_branches_share_a_node_and_a_cycle_is_found():
    edges = [edge("ce:killing", "ce:march"), edge("ce:killing", "ce:strike"),
             edge("ce:arrest", "ce:killing")]
    assert convergence(edges)["ce:killing"] == 2
    assert depths(edges, {"ce:march", "ce:strike"})["ce:arrest"] == 2
    assert find_cycle(edges) is None
    looped = edges + [edge("ce:march", "ce:arrest")]
    assert find_cycle(looped) is not None
