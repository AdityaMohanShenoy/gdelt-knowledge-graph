"""Atomic event mentions: several structured events per article, every field a span.

Rules over spaCy's parse of the stored sentences, so a mention can only name text
that is in the article. A field the rules cannot fill stays empty, which means
"uncertain"; it is never guessed. The extractor proposes; review decides.

v2 changes come from the v1 dev review (docs/measurements/event_mentions.md):
place and time are taken from the event's own clause, descriptive and prescriptive
uses are not events, pronoun actors stay empty, and state actions, meetings and
appeals are recognised.
"""

import re
from typing import Any

from focal_events import ACTION_LEMMAS, REPORTING_LEMMAS, text_hash

SCHEMA_VERSION = "event-mention.v1"
EXTRACTOR_VERSION = "rules.v2"

PROTEST_VERBS = frozenset("agitate boycott gherao picket blockade besiege".split())
STATE_VERBS = frozenset("lathicharge lathi-charge teargas adjourn appeal urge".split())
GATHER_VERBS = frozenset("gather assemble congregate".split())  # only intransitive
EVENT_LEMMAS = ACTION_LEMMAS | PROTEST_VERBS | STATE_VERBS | GATHER_VERBS
# "staged a protest", "called a bandh": the event is the noun, the verb only carries it.
# "stag" is in the list because spaCy lemmatises "staged" to "stag".
LIGHT_VERBS = frozenset(
    "stage stag hold call launch observe organise organize begin start resume".split()
)
PROTEST_NOUNS = frozenset(
    "protest rally march strike bandh hartal dharna demonstration agitation sit-in blockade "
    "gherao boycott fast walkout picket roko procession vigil satyagraha".split()
)
MEETING_NOUNS = frozenset("talk talks meeting negotiation negotiations dialogue".split())
# A protest noun as subject is an event only when the verb says it happened:
# "protests erupted", not "the blockade delayed trains".
ONSET_VERBS = frozenset(
    "erupt begin start continue enter end spread intensify escalate turn break resume "
    "mark take".split()
)
INTENT_LEMMAS = frozenset(
    "plan threaten decide vow warn announce call schedule set prepare propose agree".split()
)
PRESCRIPTIVE_MODALS = frozenset("should must ought might may could".split())
INSTITUTIONS = frozenset("house assembly parliament session".split())
# verb + object pairs whose meaning lives in the object: "denied permission",
# "registered a case", "fired tear gas", "sealed the border".
OBJECT_EVENTS = {
    ("deny", "permission"): "17",
    ("register", "case"): "17",
    ("register", "fir"): "17",
    ("file", "fir"): "17",
    ("fire", "gas"): "17",
    ("fire", "shell"): "17",
    ("use", "gas"): "17",
    ("seal", "border"): "17",
    ("impose", "curfew"): "17",
    ("impose", "section"): "17",
    ("impose", "restriction"): "17",
    ("burn", "effigy"): "14",
    ("submit", "memorandum"): "02",
    ("block", "road"): "14",
    ("block", "highway"): "14",
    ("block", "track"): "14",
    ("block", "traffic"): "14",
    ("close", "shop"): "14",
    ("close", "market"): "14",
}

# CAMEO root codes, only where the words settle it; anything else stays None.
CAMEO_ROOT = {
    **dict.fromkeys(
        "protest demonstrate march rally strike agitate boycott picket gherao blockade".split(),
        "14",
    ),
    **dict.fromkeys(PROTEST_NOUNS, "14"),
    **dict.fromkeys(MEETING_NOUNS, "04"),
    **dict.fromkeys("arrest detain ban lathicharge lathi-charge teargas".split(), "17"),
    **dict.fromkeys("attack kill injure".split(), "18"),
    **dict.fromkeys("demand appeal urge".split(), "02"),
    "clash": "19",
    "meet": "04",
    "reject": "12",
    "deploy": "15",
}

# NER labels to the store's entities.kind, in one place (BUILD_PLAN Phase 7).
STORE_ENTITY_KIND = {
    "PERSON": "actor",
    "ORG": "organisation",
    "ORGANIZATION": "organisation",
    "NORP": "organisation",
    "GPE": "place",
    "LOC": "place",
    "FAC": "place",
    "LOCATION": "place",
}
PLACE_LABELS = frozenset({"GPE", "LOC", "FAC"})
TIME_LABELS = frozenset({"DATE", "TIME"})
DURATION = re.compile(
    r"^(\d+|a|an|one|two|three|four|five|six|seven|eight|nine|ten|several|few|many)"
    r"[\s-]+(minute|hour|day|week|month|year)s?(-long)?$|-long$|-day$|-hour$",
    re.IGNORECASE,
)


def span(doc_span: Any, base: int, kind: str | None = None) -> dict:
    result = {
        "text": doc_span.text,
        "start": base + doc_span.start_char,
        "end": base + doc_span.end_char,
    }
    if kind:
        result["kind"] = kind
    return result


def subtree(token: Any) -> Any:
    return token.doc[token.left_edge.i : token.right_edge.i + 1]


def negated(*tokens: Any) -> bool:
    # "did not arrest" hangs `neg` on the verb; "no protest was held" hangs `no` on the noun.
    return any(
        child.dep_ == "neg" or (child.dep_ == "det" and child.lower_ == "no")
        for token in tokens
        for child in token.children
    )


def not_an_event(verb: Any) -> bool:
    """Descriptive, purposive or prescriptive uses of an event word."""
    if verb.dep_ == "amod" or (verb.dep_ == "acl" and verb.i < verb.head.i):
        return True  # "protesting farmers"
    has_to = any(c.dep_ == "aux" and c.lower_ == "to" for c in verb.children)
    if has_to and verb.dep_ in {"advcl", "acl"}:
        return True  # "gathered to demonstrate support", "the right to protest"
    if any(c.tag_ == "MD" and c.lower_ in PRESCRIPTIVE_MODALS for c in verb.children):
        return True  # "should withdraw", "may protest"
    subjects = [c.lemma_.lower() for c in verb.children if c.dep_ == "nsubj"]
    return verb.lemma_.lower() == "meet" and any(s in INSTITUTIONS for s in subjects)


def find_actions(doc: Any) -> list[tuple[Any, Any, str | None]]:
    """(verb, event word, event type). The event word is the verb, or the noun it carries."""
    actions = []
    for token in doc:
        lemma = token.lemma_.lower()
        if token.pos_ != "VERB" or lemma in REPORTING_LEMMAS or not_an_event(token):
            continue
        objects = [c for c in token.children if c.dep_ in {"dobj", "attr"}]
        carried = [c for c in objects if c.lemma_.lower() in PROTEST_NOUNS | MEETING_NOUNS] + [
            grandchild
            for child in token.children
            if child.dep_ == "prep" and child.lower_ == "on"
            for grandchild in child.children
            if grandchild.dep_ == "pobj" and grandchild.lemma_.lower() in PROTEST_NOUNS
        ]
        subjects = [
            child
            for child in token.children
            if child.dep_ in {"nsubj", "nsubjpass"} and child.lemma_.lower() in PROTEST_NOUNS
        ]
        paired = [
            (c, OBJECT_EVENTS[(lemma, c.lemma_.lower())])
            for c in objects + [c for c in token.children if c.dep_ == "nsubjpass"]
            if (lemma, c.lemma_.lower()) in OBJECT_EVENTS
        ]
        walked_out = lemma == "walk" and any(c.lower_ == "out" for c in token.children)
        if lemma in LIGHT_VERBS and carried:
            noun = carried[0]
            actions.append((token, noun, CAMEO_ROOT.get(noun.lemma_.lower())))
        elif carried and lemma in {"go", "sit", "be"}:
            actions.append((token, carried[0], "14"))  # "went on strike", "sat on dharna"
        elif subjects and lemma in ONSET_VERBS:
            actions.append((token, subjects[0], "14"))  # "protests erupted"
        elif paired:
            actions.append((token, paired[0][0], paired[0][1]))
        elif walked_out:
            actions.append((token, token, "14"))
        elif lemma in GATHER_VERBS:
            if not objects:
                actions.append((token, token, None))
        elif lemma in EVENT_LEMMAS:
            actions.append((token, token, CAMEO_ROOT.get(lemma)))
    # "decided to march" is one announced march, not a separate "decided" event.
    heads = {verb.head.i for verb, _, _ in actions if verb.dep_ == "xcomp"}
    return [
        action
        for action in actions
        if not (action[0].i in heads and action[0].lemma_.lower() in INTENT_LEMMAS)
    ]


def actors_of(verb: Any, event: Any) -> list[Any]:
    # spaCy builds a new Token object on every access, so compare positions, not identity.
    found: list[Any] = []
    # Nominal event, "farmers' protest" or "protest by farmers". Only for protest and
    # meeting nouns: in "burnt an effigy of the PM" the PM is no actor.
    if event.i != verb.i and event.lemma_.lower() in PROTEST_NOUNS | MEETING_NOUNS:
        found = [c for c in event.children if c.dep_ == "poss"] + [
            g
            for c in event.children
            if c.dep_ == "prep" and c.lower_ in {"by", "of"}
            for g in c.children
            if g.dep_ == "pobj"
        ]
    if not found:
        if any(c.dep_ == "nsubjpass" for c in verb.children):
            found = [g for c in verb.children if c.dep_ == "agent" for g in c.children]
        else:
            found = [c for c in verb.children if c.dep_ == "nsubj" and c.i != event.i]
            if not found and verb.dep_ in {"xcomp", "conj"}:  # "decided to protest"
                found = [c for c in verb.head.children if c.dep_ in {"nsubj", "nsubjpass"}]
    # A bare pronoun names nobody; leave the actor uncertain rather than wrong.
    return [t for t in found if t.pos_ != "PRON"]


def targets_of(verb: Any, event: Any) -> list[Any]:
    found = [c for c in verb.children if c.dep_ in {"dobj", "nsubjpass"} and c.i != event.i]
    for head in [verb] if event.i == verb.i else [verb, event]:
        found += [
            g
            for c in head.children
            if c.dep_ == "prep" and c.lower_ in {"against", "over"}
            for g in c.children
            if g.dep_ == "pobj"
        ]
    return [t for t in found if t.pos_ != "PRON"]


def own_clause(verb: Any, event: Any, others: set[int]) -> set[int]:
    """Tokens governed by this event and not by another event verb inside it."""
    scope = set()
    for head in {verb.i, event.i}:
        for token in verb.doc[head].subtree:
            ancestor = token
            while ancestor.i not in (verb.i, event.i):
                if ancestor.i in others or ancestor.head.i == ancestor.i:
                    break
                ancestor = ancestor.head
            else:
                scope.add(token.i)
    return scope


def clause_entities(doc: Any, scope: set[int], labels: frozenset) -> list[Any]:
    return [
        e
        for e in doc.ents
        if e.label_ in labels
        and e.root.i in scope
        # "Delhi Chief Minister": a place naming someone's title, not where it happened.
        and e.root.dep_ not in {"compound", "amod", "poss", "nmod"}
        and not DURATION.search(e.text.strip())
    ]


def entity_kind(doc_span: Any) -> str | None:
    for entity in doc_span.ents:
        if entity.label_ in STORE_ENTITY_KIND:
            return STORE_ENTITY_KIND[entity.label_]
    return None


def extract_sentence(doc: Any, sentence: dict) -> list[dict]:
    base = sentence["start_char"]
    actions = find_actions(doc)
    verbs = {verb.i for verb, _, _ in actions}
    mentions = []
    for verb, event, event_type in actions:
        if negated(verb, event):
            continue
        announced = any(c.tag_ == "MD" for c in verb.children) or (
            verb.dep_ == "xcomp" and verb.head.lemma_.lower() in INTENT_LEMMAS
        )
        scope = own_clause(verb, event, verbs - {verb.i})
        places = clause_entities(doc, scope, PLACE_LABELS)
        times = clause_entities(doc, scope, TIME_LABELS)
        action = doc[min(verb.i, event.i) : max(verb.i, event.i) + 1]
        mentions.append(
            {
                "token": verb.i,
                "action": {**span(action, base), "lemma": event.lemma_.lower()},
                "actors": [
                    span(subtree(t), base, entity_kind(subtree(t))) for t in actors_of(verb, event)
                ],
                "targets": [span(subtree(t), base) for t in targets_of(verb, event)],
                "locations": [span(e, base, "place") for e in places],
                "event_time": span(times[0], base) if times else None,
                "event_type": event_type,
                "status": "announced" if announced else "asserted",
            }
        )
    return mentions


def spans_of(mention: dict) -> list[dict]:
    fields = [mention["action"], mention["event_time"]]
    fields += mention["actors"] + mention["targets"] + mention["locations"]
    return [field for field in fields if field is not None]


def validate_mention(mention: dict, text: str) -> None:
    if mention["text_sha256"] != text_hash(text):
        raise ValueError(f"{mention['event_mention_id']}: pinned text hash mismatch")
    start, end = mention["evidence_start"], mention["evidence_end"]
    if not 0 <= start < end <= len(text):
        raise ValueError(f"{mention['event_mention_id']}: evidence span out of range")
    for field in spans_of(mention):
        if text[field["start"] : field["end"]] != field["text"]:
            raise ValueError(f"{mention['event_mention_id']}: span text differs from article")
        if not start <= field["start"] < field["end"] <= end:
            raise ValueError(f"{mention['event_mention_id']}: field outside its evidence")


def extract_article(nlp: Any, gold: dict) -> list[dict]:
    """Mentions for one reviewed article, offsets into its frozen snapshot text."""
    text = gold["article_text"]
    sentences = gold["sentences"]
    docs = nlp.pipe(s["text"] for s in sentences)
    mentions = []
    for sentence, doc in zip(sentences, docs, strict=True):
        for found in extract_sentence(doc, sentence):
            token = found.pop("token")
            mentions.append(
                {
                    "schema_version": SCHEMA_VERSION,
                    "event_mention_id": f"{gold['article_id']}:{sentence['sentence_id']}:{token}",
                    "source_article_id": gold["article_id"],
                    "text_sha256": text_hash(text),
                    "sentence_id": sentence["sentence_id"],
                    "evidence_start": sentence["start_char"],
                    "evidence_end": sentence["end_char"],
                    **found,
                    "focal": False,
                    "origin": "rules",
                    "confidence": None,  # uncalibrated rules: no score rather than a fake one
                    "review_status": "UNREVIEWED",
                    "extractor": EXTRACTOR_VERSION,
                }
            )
    # Phase 2's focal event seeds the article: its core sentence (or first support
    # sentence) carries the focal mention, even when the rules found nothing there.
    focal_id = gold.get("core_sentence_id") or min(gold["supporting_sentence_ids"])
    in_focal = [m for m in mentions if m["sentence_id"] == focal_id]
    if in_focal:
        in_focal[0]["focal"] = True
    else:
        sentence = next(s for s in sentences if s["sentence_id"] == focal_id)
        mentions.append(
            {
                "schema_version": SCHEMA_VERSION,
                "event_mention_id": f"{gold['article_id']}:{focal_id}:focal",
                "source_article_id": gold["article_id"],
                "text_sha256": text_hash(text),
                "sentence_id": focal_id,
                "evidence_start": sentence["start_char"],
                "evidence_end": sentence["end_char"],
                "action": None,
                "actors": [],
                "targets": [],
                "locations": [],
                "event_time": None,
                "event_type": None,
                "status": None,
                "focal": True,
                "origin": "focal_seed",
                "confidence": None,
                "review_status": "UNREVIEWED",
                "extractor": EXTRACTOR_VERSION,
            }
        )
    mentions.sort(key=lambda m: (m["sentence_id"], m["evidence_start"], m["event_mention_id"]))
    for mention in mentions:
        validate_mention(mention, text)
    return mentions
