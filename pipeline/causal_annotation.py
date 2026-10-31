"""Phase 10: causal edges from judged candidate claims, and their agreement.

A judgement accepts a claim only on an exact quote that shows the link; the quote
is located in the effect's articles or the cause's, so every accepted edge points
at the article text that supports it. Rejections are kept with their reason: they
are the hard negatives a later ranker trains on.

There is no machine relation or strength model yet, so `machine_relation_type`
and `machine_strength` are null rather than a retrieval score dressed up as one.
"""

import random
from collections import Counter

EDGE_SCHEMA = "causal-edge.v1"
RELATIONS = (
    "TRIGGERS",
    "MOTIVATES",
    "MOBILIZES",
    "ENABLES",
    "ESCALATES",
    "PROMPTS_RESPONSE",
    "CONTRIBUTES_TO",
)
REJECT_REASONS = frozenset(
    {
        "NO_CAUSAL_EVIDENCE",
        "TEMPORALLY_INVALID",
        "WRONG_EVENT_MATCH",
        "DUPLICATE_EVENT",
        "CORRELATED_ONLY",
        "INSUFFICIENT_EVIDENCE",
        "WRONG_DIRECTION",
        "OTHER",
    }
)
QUALITIES = frozenset({"explicit", "implicit"})


def locate_quote(quote: str, texts: dict[str, str]) -> dict | None:
    """The first article whose text contains `quote` verbatim, with offsets."""
    for article_id in sorted(texts):
        at = texts[article_id].find(quote) if quote else -1
        if at >= 0:
            return {"article_id": article_id, "start": at, "end": at + len(quote), "text": quote}
    return None


def edge(
    claim: dict, judgement: dict, texts: dict, outlet, reviewer: str, role: str, stamp: str
) -> dict:
    """One judged claim as an edge record. `texts` holds the effect's and the cause's
    article texts; `outlet` maps an article id to its outlet. Raises on a judgement
    that breaks the rubric, so a bad batch is fixed rather than half-loaded."""
    cid = claim["claim_id"]
    row = {
        "schema_version": EDGE_SCHEMA,
        "claim_id": cid,
        "source_event_id": claim["cause_event_id"],
        "source_kind": claim["cause_kind"],
        "target_event_id": claim["effect_event_id"],
        "temporal_gap": claim["lag_days"],
        "machine_relation_type": None,
        "machine_strength": None,
        "relation_type": None,
        "final_strength": None,
        "primary_evidence": None,
        "supporting_evidence": [],
        "evidence_quality": None,
        "corroboration_count": 0,
        "review_status": None,
        "reject_reason": None,
        "why": judgement.get("why"),
        "reviewer_id": reviewer,
        "reviewed_at": stamp,
        "annotation_role": role,
        "label_source": "ai_assisted",
    }
    if judgement["decision"] == "reject":
        if judgement.get("reject_reason") not in REJECT_REASONS:
            raise ValueError(f"{cid}: reject needs a reason from the taxonomy")
        return {**row, "review_status": "REJECTED", "reject_reason": judgement["reject_reason"]}
    if judgement["decision"] != "accept":
        raise ValueError(f"{cid}: decision must be accept or reject")
    if judgement.get("relation") not in RELATIONS:
        raise ValueError(f"{cid}: unknown relation {judgement.get('relation')!r}")
    if judgement.get("strength") not in (1, 2, 3):
        raise ValueError(f"{cid}: strength must be 1, 2 or 3")
    if judgement.get("evidence_quality") not in QUALITIES:
        raise ValueError(f"{cid}: evidence_quality must be explicit or implicit")
    primary = locate_quote(judgement.get("evidence") or "", texts)
    if primary is None:
        raise ValueError(f"{cid}: evidence quote is not in the article text")
    supporting = [s for q in judgement.get("supporting") or [] if (s := locate_quote(q, texts))]
    spans = [primary, *supporting]
    return {
        **row,
        "relation_type": judgement["relation"],
        "final_strength": round(judgement["strength"] / 3, 4),
        "primary_evidence": primary,
        "supporting_evidence": supporting,
        "evidence_quality": judgement["evidence_quality"],
        # Independent outlets whose text carries the link, not article copies.
        "corroboration_count": len({outlet(s["article_id"]) for s in spans}),
        "review_status": "ACCEPTED",
    }


def double_sample(claims: list[dict], share: float, seed: str) -> set[str]:
    """Whole seeds, drawn at random until they hold `share` of the claims, so a
    second annotator reads each protest's article once."""
    by_seed = Counter(c["effect_event_id"] for c in claims)
    order = sorted(by_seed)
    random.Random(seed).shuffle(order)
    picked: set[str] = set()
    for seed_id in order:
        if sum(by_seed[s] for s in picked) >= share * len(claims):
            break
        picked.add(seed_id)
    return picked


def kappa(pairs: list[tuple]) -> float | None:
    """Cohen's kappa over (label_a, label_b) pairs; None when chance agreement is 1."""
    if not pairs:
        return None
    n = len(pairs)
    observed = sum(a == b for a, b in pairs) / n
    left, right = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    expected = sum(left[k] * right[k] for k in left) / (n * n)
    return None if expected == 1 else round((observed - expected) / (1 - expected), 4)


def agreement(primary: list[dict], second: list[dict]) -> dict:
    """Agreement between two annotators on the claims both judged: on accept/reject,
    on the relation where both accepted, and per relation type."""
    first = {e["claim_id"]: e for e in primary}
    both = [(first[e["claim_id"]], e) for e in second if e["claim_id"] in first]
    decisions = [(a["review_status"], b["review_status"]) for a, b in both]
    accepted = [
        (a["relation_type"], b["relation_type"])
        for a, b in both
        if a["review_status"] == b["review_status"] == "ACCEPTED"
    ]
    rejected = [
        (a["reject_reason"], b["reject_reason"])
        for a, b in both
        if a["review_status"] == b["review_status"] == "REJECTED"
    ]
    per_type = {}
    for relation in RELATIONS:
        n_a = sum(a == relation for a, _ in accepted)
        n_b = sum(b == relation for _, b in accepted)
        if n_a + n_b:
            joint = sum(a == b == relation for a, b in accepted)
            # Specific agreement: of the times either annotator chose this type, how
            # often both did. Computed where both accepted, so it is about the type.
            per_type[relation] = {
                "first": n_a,
                "second": n_b,
                "both": joint,
                "specific_agreement": round(2 * joint / (n_a + n_b), 4),
            }
    return {
        "double_annotated": len(both),
        "decision": {
            "observed": round(sum(a == b for a, b in decisions) / len(decisions), 4)
            if decisions
            else None,
            "kappa": kappa(decisions),
            "both_accepted": len(accepted),
            "both_rejected": len(rejected),
            "split": len(decisions) - len(accepted) - len(rejected),
        },
        "relation": {
            "observed": round(sum(a == b for a, b in accepted) / len(accepted), 4)
            if accepted
            else None,
            "kappa": kappa(accepted),
            "per_type": per_type,
            "confusions": dict(
                Counter(f"{a}|{b}" for a, b in accepted if a != b).most_common()
            ),
        },
        "reject_reason": {"observed": round(sum(a == b for a, b in rejected) / len(rejected), 4)
                          if rejected else None, "kappa": kappa(rejected)},
    }
