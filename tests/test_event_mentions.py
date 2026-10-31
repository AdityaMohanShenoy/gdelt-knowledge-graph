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
