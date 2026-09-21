"""Scoring constants.

"Present" for a root code on a day means an unusually active day for that code:
daily count above its own 75th percentile. Raw presence is useless at day
granularity because common codes fire nearly every day in a busy country.
"""

CAUSAL_WINDOW_DAYS = 7
CAUSAL_FLOOR = 0.08
MIN_GROUP_EVENTS = 3          # a (day, type) group below this is too thin to score
ACTOR_MAX_SHARE = 0.05        # a token in >5% of events cannot discriminate
ACTOR_PROBES = 3              # how many of the rarest tokens to match on

# Illustrative weights. In the real design these are fitted on the Stage 1
# labelled decisions; there is no labelled set in this repo, so they are fixed
# and the UI says so. P3.4 replaces them with scoring/weights.json.
CAUSAL_W = {
    "documented":    2.6,
    "corroboration": 1.4,
    "prior":         1.1,
    "contrastive":   1.3,
    "actors":        0.9,
    "contradiction": -3.0,
}
CAUSAL_INTERCEPT = -3.2

CHANNEL_META = [
    {"key": "documented",    "label": "Reporter stated it",  "available": True,
     "note": "Proxied by the pipeline's own precursor links"},
    {"key": "corroboration", "label": "Independent outlets",  "available": True,
     "note": "Distinct source domains reporting the group"},
    {"key": "prior",         "label": "Usual pattern",        "available": True,
     "note": "Lift of effect type after cause type"},
    {"key": "contrastive",   "label": "What happened else",   "available": True,
     "note": "Sufficiency and necessity over spike days"},
    {"key": "actors",        "label": "Same people",          "available": True,
     "note": "Shared actor tokens, rare tokens weighted"},
    {"key": "contradiction", "label": "Anyone denied it",     "available": False,
     "note": "Needs article text -- no corpus in this build"},
]

ROOT_LABEL = {
    "01": "Public Statement", "02": "Appeal", "03": "Intent to Cooperate",
    "04": "Consult", "05": "Diplomatic Cooperation", "06": "Material Cooperation",
    "07": "Provide Aid", "08": "Yield", "09": "Investigate", "10": "Demand",
    "11": "Disapprove", "12": "Reject", "13": "Threaten", "14": "Protest",
    "15": "Military Posture", "16": "Reduce Relations", "17": "Coerce",
    "18": "Assault", "19": "Fight", "20": "Mass Violence",
}

# Actor tokens so common they carry no information about a specific link.
STOP_ACTORS = {
    "THE", "AND", "FOR", "OF", "A", "AN", "IN", "ON", "TO",
    "GOVERNMENT", "PRESIDENT", "MINISTER", "OFFICIAL", "OFFICIALS",
    "AUTHORITY", "AUTHORITIES", "POLICE", "MILITARY", "COUNTRY", "STATE",
}
