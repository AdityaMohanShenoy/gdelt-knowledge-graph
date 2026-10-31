"""Atomic event mentions: several structured events per article, every field a span.

Rules over spaCy's parse of the stored sentences, so a mention can only name text
that is in the article. A field the rules cannot fill stays empty, which means
"uncertain"; it is never guessed. The extractor proposes; review decides.
"""

from typing import Any

from focal_events import ACTION_LEMMAS, REPORTING_LEMMAS, text_hash

SCHEMA_VERSION = "event-mention.v1"
EXTRACTOR_VERSION = "rules.v1"

PROTEST_VERBS = frozenset("agitate boycott gherao picket blockade besiege".split())
EVENT_LEMMAS = ACTION_LEMMAS | PROTEST_VERBS
# "staged a protest", "called a bandh": the event is the noun, the verb only carries it.
# "stag" is in the list because spaCy lemmatises "staged" to "stag".
LIGHT_VERBS = frozenset("stage stag hold call launch observe organise organize begin start".split())
PROTEST_NOUNS = frozenset(
    "protest rally march strike bandh hartal dharna demonstration agitation sit-in blockade "
    "gherao boycott fast walkout picket roko procession vigil satyagraha".split()
)
INTENT_LEMMAS = frozenset("plan threaten decide vow warn announce call".split())

# CAMEO root codes, only where the verb settles it; anything else stays None.
CAMEO_ROOT = {
    **dict.fromkeys(
        "protest demonstrate march rally strike agitate boycott picket gherao blockade".split(),
        "14",
    ),
    **dict.fromkeys(PROTEST_NOUNS, "14"),
    **dict.fromkeys("arrest detain ban".split(), "17"),
    **dict.fromkeys("attack kill injure".split(), "18"),
    "clash": "19",
    "demand": "02",
    "meet": "04",
    "reject": "12",
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


def find_actions(doc: Any) -> list[tuple[Any, Any]]:
    """(verb, event word) pairs. The event word is the verb, or the protest noun it carries."""
    actions = []
    for token in doc:
        lemma = token.lemma_.lower()
        if token.pos_ != "VERB" or lemma in REPORTING_LEMMAS:
            continue
        carried = [
            child
            for child in token.children
            if child.dep_ in {"dobj", "attr"} and child.lemma_.lower() in PROTEST_NOUNS
        ] + [
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
        if lemma in LIGHT_VERBS and carried:
            actions.append((token, carried[0]))
        elif carried and lemma in {"go", "sit", "be"}:
            actions.append((token, carried[0]))  # "went on strike", "sat on dharna"
        elif subjects:
            actions.append((token, subjects[0]))  # "protests erupted", "the bandh continued"
        elif lemma in EVENT_LEMMAS:
            actions.append((token, token))
    # "decided to march" is one announced march, not a separate "decided" event.
    heads = {verb.head.i for verb, _ in actions if verb.dep_ == "xcomp"}
    return [
        (verb, event)
        for verb, event in actions
        if not (verb.i in heads and verb.lemma_.lower() in INTENT_LEMMAS)
    ]


def actors_of(verb: Any, event: Any) -> list[Any]:
    # spaCy builds a new Token object on every access, so compare positions, not identity.
    if event.i != verb.i:  # nominal event: "farmers' protest", "protest by farmers"
        found = [c for c in event.children if c.dep_ == "poss"] + [
            g
            for c in event.children
            if c.dep_ == "prep" and c.lower_ in {"by", "of"}
            for g in c.children
            if g.dep_ == "pobj"
        ]
        if found:
            return found
    if any(c.dep_ == "nsubjpass" for c in verb.children):
        return [g for c in verb.children if c.dep_ == "agent" for g in c.children]
    subjects = [c for c in verb.children if c.dep_ == "nsubj" and c.i != event.i]
    if not subjects and verb.dep_ in {"xcomp", "conj"}:  # "decided to protest"
        subjects = [c for c in verb.head.children if c.dep_ == "nsubj"]
    return subjects


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
    return found


def entity_kind(doc_span: Any) -> str | None:
    for entity in doc_span.ents:
        if entity.label_ in STORE_ENTITY_KIND:
            return STORE_ENTITY_KIND[entity.label_]
    return None


def extract_sentence(doc: Any, sentence: dict) -> list[dict]:
    base = sentence["start_char"]
    places = [span(e, base, "place") for e in doc.ents if e.label_ in PLACE_LABELS]
    times = [span(e, base) for e in doc.ents if e.label_ in TIME_LABELS]
    mentions = []
    for verb, event in find_actions(doc):
        if negated(verb, event):
            continue
        announced = any(c.tag_ == "MD" for c in verb.children) or (
            verb.dep_ == "xcomp" and verb.head.lemma_.lower() in INTENT_LEMMAS
        )
        lemma = event.lemma_.lower()
        action = doc[min(verb.i, event.i) : max(verb.i, event.i) + 1]
        mentions.append(
            {
                "token": verb.i,
                "action": {**span(action, base), "lemma": lemma},
                "actors": [
                    span(subtree(t), base, entity_kind(subtree(t))) for t in actors_of(verb, event)
                ],
                "targets": [span(subtree(t), base) for t in targets_of(verb, event)],
                "locations": places,
                "event_time": times[0] if times else None,
                "event_type": CAMEO_ROOT.get(lemma),
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
