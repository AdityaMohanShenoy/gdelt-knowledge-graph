import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

from causal_candidates import condition_node, in_window, proposed  # noqa: E402
from conditions import apply_extraction, canonical_condition, holds_at  # noqa: E402

TEXT = (
    "Residents protested over the water crisis in Delhi since May 2024. "
    "The minister called the protesters traitors."
)


def gold():
    first, second = TEXT.split(". ", 1)
    first += "."
    return {
        "article_id": "9",
        "article_text": TEXT,
        "sentences": [
            {"sentence_id": 1, "text": first, "start_char": 0, "end_char": len(first)},
            {"sentence_id": 2, "text": second, "start_char": len(first) + 1,
             "end_char": len(TEXT)},
        ],
        "source_metadata": {"gdelt_observations": [{"day": 20240620}]},
    }


EXTRACTION = {
    "conditions": [
        {"sentence_id": 1, "condition": "the water crisis", "holders": ["Residents", "nobody"],
         "locations": ["Delhi"], "since": "May 2024", "until": None, "status": "ongoing",
         "kind": "shortage", "role": "protest_cause"},
        {"sentence_id": 1, "condition": "an invented crisis", "holders": [], "locations": []},
    ],
    "remarks": [
        {"sentence_id": 2, "action": "called the protesters traitors", "actors": ["The minister"],
         "targets": ["the protesters"], "event_type": "11", "provoked_reaction": True},
    ],
}


def test_extraction_keeps_only_verbatim_spans_and_dates_from_the_text():
    conditions, remarks, dropped = apply_extraction(gold(), EXTRACTION, "Claude (AI)")
    assert dropped == 2  # "nobody" and the invented condition are not in the sentence
    [water] = conditions
    assert TEXT[water["condition"]["start"] : water["condition"]["end"]] == "the water crisis"
    assert [h["text"] for h in water["holders"]] == ["Residents"]
    # The stated year gives the start; the end is the fallback, so it is not "stated".
    assert water["validity"]["start"] == "2024-05-01" and water["validity"]["start_stated"]
    assert not water["validity"]["end_stated"]
    assert holds_at(water["validity"], dt.date(2024, 7, 1))
    assert not holds_at(water["validity"], dt.date(2023, 12, 1))
    [insult] = remarks
    assert insult["origin"] == "remark_added" and insult["event_type"] == "11"
    assert insult["status"] == "asserted" and [a["text"] for a in insult["actors"]] == [
        "The minister"
    ]


def test_canonical_condition_keeps_every_phrasing_and_the_stated_start():
    conditions, _, _ = apply_extraction(gold(), EXTRACTION, "Claude (AI)")
    other = {**conditions[0], "condition_mention_id": "10:1:k1", "source_article_id": "10",
             "condition": {**conditions[0]["condition"], "text": "the water shortage"},
             "validity": {**conditions[0]["validity"], "start": "2023-12-23",
                          "start_stated": False}}
    merged = canonical_condition(conditions + [other], [], lambda m: m["source_article_id"])
    assert merged["review_status"] == "MERGED" and merged["valid_from"] == "2024-05-01"
    assert merged["phrasings"] == ["the water crisis", "the water shortage"]
    assert merged["independent_outlets"] == ["10", "9"]


def test_a_condition_is_a_candidate_only_while_it_holds():
    seed = {"canonical_event_id": "ce:s", "best_time": "2024-06-20",
            "time_range": ["2024-06-20", "2024-06-20"]}
    node = condition_node({"canonical_condition_id": "cc:1", "holders": [], "locations": [],
                           "valid_from": "2024-01-01", "valid_to": "2024-07-20",
                           "supporting_sources": ["9"]}, ["s"])
    assert in_window(seed, node, 0)
    assert not in_window({**seed, "best_time": "2024-08-01"}, node, 0)


def test_far_and_condition_candidates_need_stronger_signals():
    names_only = {"same_article": [], "actors": [], "locations": [],
                  "shared_names": ["delhi"], "similarity": 0.2}
    assert proposed(names_only) and not proposed(names_only, "far")
    similar = {**names_only, "similarity": 0.58}
    assert not proposed(similar, "far")  # similar wording alone is a topic, not a link
    assert proposed({**similar, "locations": ["delhi"]}, "far")
    assert not proposed(similar, "condition") and proposed({**similar, "similarity": 0.6},
                                                           "condition")
    co_reported = {**names_only, "same_article": ["9"]}
    assert proposed(co_reported, "far") and proposed(co_reported, "condition")
