import copy
import hashlib
import sys
from pathlib import Path

import pytest
import spacy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

from event_mentions import extract_article, extract_sentence, validate_mention  # noqa: E402


@pytest.fixture(scope="module")
def nlp():
    return spacy.load("en_core_web_sm")


def mentions(nlp, text):
    return extract_sentence(nlp(text), {"start_char": 0})


def test_fields_are_spans_of_the_sentence(nlp):
    [m] = mentions(nlp, "Farmers protested against the farm laws in Ludhiana on Monday.")
    assert m["action"]["lemma"] == "protest" and m["event_type"] == "14"
    assert [a["text"] for a in m["actors"]] == ["Farmers"]
    assert m["targets"][0]["text"].startswith("the farm laws")
    assert [p["text"] for p in m["locations"]] == ["Ludhiana"]
    assert m["event_time"]["text"] == "Monday" and m["status"] == "asserted"


@pytest.mark.parametrize(
    "text",
    ["No protest was held in Delhi.", "Police did not arrest anyone.", "He said it was calm."],
)
def test_denied_or_reported_events_are_never_invented(nlp, text):
    assert mentions(nlp, text) == []


@pytest.mark.parametrize(
    ("text", "action", "status"),
    [
        ("The union will strike on Friday.", "strike", "announced"),
        ("Workers went on strike in Chennai.", "went on strike", "asserted"),
        ("Students staged a dharna outside the Nabanna.", "staged a dharna", "asserted"),
        ("The farmers decided to march to Delhi.", "march", "announced"),
    ],
)
def test_protest_constructions(nlp, text, action, status):
    [m] = mentions(nlp, text)
    assert (m["action"]["text"], m["event_type"], m["status"]) == (action, "14", status)


def test_a_nominal_event_is_not_its_own_actor(nlp):
    [m] = mentions(nlp, "Protests erupted in Kolkata after the verdict.")
    assert m["actors"] == [] and m["action"]["text"] == "Protests erupted"


def article(text, sentences, core):
    spans, start = [], 0
    for index, sentence in enumerate(sentences, 1):
        start = text.index(sentence, start)
        spans.append({"sentence_id": index, "paragraph_id": 1, "text": sentence,
                      "start_char": start, "end_char": start + len(sentence)})
        start += len(sentence)
    return {
        "article_id": "7",
        "article_text": text,
        "article_text_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "sentences": spans,
        "supporting_sentence_ids": [core],
        "core_sentence_id": core,
    }


def test_article_offsets_pin_to_the_snapshot_and_seed_the_focal_event(nlp):
    text = "Kolkata, Aug 27. Police arrested 220 students in Howrah. The city was tense."
    found = extract_article(nlp, article(text, [
        "Kolkata, Aug 27.", "Police arrested 220 students in Howrah.", "The city was tense."
    ], core=2))
    [arrest] = [m for m in found if m["origin"] == "rules"]
    assert arrest["focal"] and arrest["event_type"] == "17"
    assert text[arrest["action"]["start"] : arrest["action"]["end"]] == "arrested"
    assert arrest["text_sha256"] == hashlib.sha256(text.encode()).hexdigest()
    # No rule fires in the core sentence, so Phase 2's focal event still seeds a mention.
    seeded = extract_article(nlp, article(text, [
        "Kolkata, Aug 27.", "Police arrested 220 students in Howrah.", "The city was tense."
    ], core=3))
    [seed] = [m for m in seeded if m["origin"] == "focal_seed"]
    assert seed["focal"] and seed["action"] is None and seed["sentence_id"] == 3


def test_validation_rejects_any_field_that_is_not_the_article_text(nlp):
    text = "Police arrested 220 students in Howrah."
    [m] = extract_article(nlp, article(text, [text], core=1))
    validate_mention(m, text)
    for corrupt in (
        lambda x: x["action"].update(text="detained"),
        lambda x: x.update(evidence_end=5),
        lambda x: x.update(text_sha256="0" * 64),
    ):
        broken = copy.deepcopy(m)
        corrupt(broken)
        with pytest.raises(ValueError):
            validate_mention(broken, text)


@pytest.mark.parametrize(
    "text",
    [
        "Citizens have the right to protest peacefully.",
        "The government should withdraw the order.",
        "The blockade delayed trains for four hours.",
        "The House met at 11 am.",
    ],
)
def test_descriptive_prescriptive_and_consequence_uses_are_not_events(nlp, text):
    assert mentions(nlp, text) == []


def test_adjectival_participle_is_not_an_event(nlp):
    found = mentions(nlp, "The agitating doctors met the Chief Secretary.")
    assert [m["action"]["lemma"] for m in found] == ["meet"]


def test_place_and_time_come_from_the_events_own_clause(nlp):
    [clash] = mentions(nlp, "Police on Monday said the farmers clashed with forces in Ambala.")
    assert clash["event_time"] is None  # Monday is when police spoke
    assert [p["text"] for p in clash["locations"]] == ["Ambala"]
    [strike] = mentions(nlp, "Delhi Chief Minister Atishi began a hunger strike on Friday.")
    assert strike["locations"] == []  # Delhi names her office, not the place
    [blockade] = mentions(nlp, "The blockade began on Monday and lasted 45-minute.")
    assert blockade["event_time"]["text"] == "Monday"


def test_pronoun_actors_stay_uncertain(nlp):
    [march] = mentions(nlp, "He said they will march to Delhi.")
    assert march["actors"] == [] and march["status"] == "announced"


@pytest.mark.parametrize(
    ("text", "action", "event_type"),
    [
        ("Police fired tear gas at the farmers.", "fired tear gas", "17"),
        ("The police denied permission for the rally.", "denied permission", "17"),
        ("Police registered a case against the workers.", "registered a case", "17"),
        ("Farmers held talks with the ministers.", "held talks", "04"),
        ("Farmers blocked the highway near Ludhiana.", "blocked the highway", "14"),
        ("The protesters burnt an effigy of the Prime Minister.", "burnt an effigy", "14"),
    ],
)
def test_state_actions_meetings_and_protest_acts(nlp, text, action, event_type):
    [m] = mentions(nlp, text)
    assert (m["action"]["text"], m["event_type"]) == (action, event_type)
    assert "Minister" not in " ".join(a["text"] for a in m["actors"])


def test_scheduled_event_is_announced_and_keeps_its_actor(nlp):
    [rally] = mentions(nlp, "The union is scheduled to hold a rally next week.")
    assert rally["status"] == "announced" and [a["text"] for a in rally["actors"]] == ["The union"]


def test_review_keeps_only_verbatim_spans_and_records_rejections(nlp):
    from event_mentions import apply_review

    text = "Police arrested 220 students in Howrah. The union called a bandh on Friday."
    gold = article(text, [
        "Police arrested 220 students in Howrah.", "The union called a bandh on Friday."
    ], core=2)
    proposals = extract_article(nlp, gold)
    by_sentence = {m["sentence_id"]: m["event_mention_id"] for m in proposals}
    review = {
        "mentions": [
            {"mention_id": by_sentence[1], "verdict": "accept", "actors": ["Police"],
             "targets": ["220 students"], "locations": ["Howrah", "Kolkata"],
             "event_time": None, "event_type": "17", "status": "asserted"},
            {"mention_id": by_sentence[2], "verdict": "reject", "reason": "test rejection",
             "actors": [], "targets": [], "locations": [], "event_time": None,
             "event_type": None, "status": None},
        ],
        "added": [
            {"sentence_id": 2, "action": "called a bandh", "actors": ["The union"],
             "targets": [], "locations": [], "event_time": "Friday", "event_type": "14",
             "status": "announced"},
            {"sentence_id": 2, "action": "invented phrase", "actors": [], "targets": [],
             "locations": [], "event_time": None, "event_type": None, "status": "asserted"},
        ],
    }
    rows, dropped = apply_review(gold, proposals, review, "Claude (AI)")
    assert dropped == 2  # "Kolkata" is not in the sentence; the invented action is not either
    arrest = next(r for r in rows if r["sentence_id"] == 1)
    # Only the unverifiable "Kolkata" differed, and it was dropped, so nothing changed.
    assert arrest["review_status"] == "REVIEWED" and not arrest["corrected"]
    assert [p["text"] for p in arrest["locations"]] == ["Howrah"]
    assert next(r for r in rows if r["review_status"] == "REJECTED")["review_reason"]
    [added] = [r for r in rows if r["origin"] == "review_added"]
    assert added["focal"] and added["event_time"]["text"] == "Friday"
    assert text[added["action"]["start"] : added["action"]["end"]] == "called a bandh"
    with pytest.raises(ValueError, match="cover exactly"):
        apply_review(gold, proposals, {**review, "mentions": review["mentions"][:1]}, "x")
