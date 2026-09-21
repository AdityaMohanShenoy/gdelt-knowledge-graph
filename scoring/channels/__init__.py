"""The six evidence channels.

Each scores one candidate cause on 0-1 and explains itself in plain words, so a
reader can re-derive the number rather than take the endpoint's word for it.

P3.2 and P3.3 replace `documented` with real connective detection and give
`contradiction` a corpus; they land here as textual.py and contradiction.py.
"""

import math

from ..config import ROOT_LABEL
from ..grade import strength
from ..sql import num


def score(candidate: dict, *, target_rc: str, matrix_index: dict, probe: list[str],
          token_idf: dict, idf_sum: float, documented_groups: set) -> tuple[dict, dict]:
    """Returns (channel scores, the intermediates the trace and grade need)."""
    c_day = int(num(candidate["day"]))
    c_rc = str(candidate["rc"]).zfill(2)
    stat = matrix_index.get((c_rc, target_rc), {})

    # Lift of 8+ is a strong type-level signal; below ~2 is noise.
    prior = min(max((num(stat.get("lift")) - 1.0) / 7.0, 0.0), 1.0)

    # Sufficiency carries most of the weight. Necessity alone is vacuous for
    # common types -- "every riot had a statement beforehand" is true of
    # almost any pair, because statements fire constantly.
    suff = max(num(stat.get("sufficiency")), 0.0)
    nec = max(num(stat.get("necessity")), 0.0)
    contrastive = min(0.75 * suff + 0.25 * nec, 1.0)

    # Each probe token contributes the share of the group's events naming it,
    # weighted by that token's own rarity.
    n_events = max(int(num(candidate["n"])), 1)
    hits = {t: int(num(candidate.get(f"hit{i}"))) for i, t in enumerate(probe)}
    actors = min(sum((hits[t] / n_events) * (token_idf[t]["idf"] / idf_sum)
                     for t in probe), 1.0) if probe else 0.0

    # Log scale: 40+ distinct domains is saturation, 8 is unremarkable.
    domains = int(num(candidate["domains"]))
    corroboration = min(math.log1p(domains) / math.log1p(40), 1.0)

    documented = 1.0 if (c_day, c_rc) in documented_groups else 0.0
    contradiction = 0.0            # no article text in this build

    channels = {
        "documented":    round(documented, 3),
        "corroboration": round(corroboration, 3),
        "prior":         round(prior, 3),
        "contrastive":   round(contrastive, 3),
        "actors":        round(actors, 3),
        "contradiction": round(contradiction, 3),
    }
    features = {
        "c_day": c_day, "c_rc": c_rc, "stat": stat, "suff": suff, "nec": nec,
        "lift": num(stat.get("lift")), "domains": domains, "hits": hits,
        "n_events": n_events, "documented": documented, "prior": prior,
        "contrastive": contrastive, "actors": actors, "corroboration": corroboration,
    }
    return channels, features


def explain(features: dict, *, target_rc: str, probe: list[str], token_idf: dict) -> list[dict]:
    """The per-channel derivation trace."""
    c_rc, c_day = features["c_rc"], features["c_day"]
    suff, nec, lift = features["suff"], features["nec"], features["lift"]
    domains, hits, n_events = features["domains"], features["hits"], features["n_events"]
    documented, corroboration = features["documented"], features["corroboration"]
    prior, contrastive, actors = features["prior"], features["contrastive"], features["actors"]
    c_name, t_name = ROOT_LABEL.get(c_rc, c_rc), ROOT_LABEL.get(target_rc, target_rc)

    if probe:
        actor_plain = " ".join(
            f'"{t}" appears in {token_idf[t]["share"]*100:.1f}% of all events, so it is '
            f'{"a distinctive" if token_idf[t]["share"] < 0.01 else "a fairly common"} name — '
            f'{hits[t]} of the {n_events} events here mention it.'
            for t in probe)
    else:
        actor_plain = ("None of the target's actor names are distinctive enough "
                       "to be worth matching on.")

    return [
        {"key": "documented", "question": "Did a reporter say so?",
         "score": round(documented, 3), "strength": strength(documented),
         "plain": ("Your existing pipeline already recorded this as a cause of the "
                   "target event." if documented >= 0.5 else
                   "The pipeline never linked anything of this type on this day to "
                   "the target event."),
         "math": f"precursor group ({c_day}, {c_rc}) "
                 f"{'matched' if documented >= 0.5 else 'not matched'}"},

        {"key": "corroboration", "question": "How many outlets carried it?",
         "score": round(corroboration, 3), "strength": strength(corroboration),
         "plain": f"{domains} different news sites reported events in this group. "
                  f"Around 40 sites would count as full marks.",
         "math": f"log1p({domains}) / log1p(40)"},

        {"key": "prior", "question": "Is this the usual pattern?",
         "score": round(prior, 3), "strength": strength(prior),
         "plain": (f"After one busy {c_name} day, another is {lift:.1f}× more likely "
                   f"than on an average day." if c_rc == target_rc else
                   f"After a busy {c_name} day, a busy {t_name} day is "
                   f"{lift:.1f}× more likely than on an average day."),
         "math": f"lift {lift:.3f}, rescaled as (lift − 1) / 7"},

        {"key": "contrastive", "question": "What happened the other times?",
         "score": round(contrastive, 3), "strength": strength(contrastive),
         "plain": (f"Of all the busy {c_name} days, {suff*100:.0f}% were followed by "
                   f"another within a week — and {nec*100:.0f}% had one before them. "
                   f"Same event type both sides, so these two figures are the same "
                   f"measurement." if c_rc == target_rc else
                   f"Of all the busy {c_name} days, {suff*100:.0f}% were followed by a "
                   f"busy {t_name} day within a week. Looking the other way, "
                   f"{nec*100:.0f}% of busy {t_name} days had one before them."),
         "math": f"0.75 × sufficiency {suff:.3f} + 0.25 × necessity {nec:.3f}"},

        {"key": "actors", "question": "Are the same people involved?",
         "score": round(actors, 3), "strength": strength(actors),
         "plain": actor_plain,
         "math": (" · ".join(f"{t} idf {token_idf[t]['idf']:.2f} × {hits[t]}/{n_events}"
                             for t in probe) if probe else "no usable tokens")},

        {"key": "contradiction", "question": "Did anyone deny it?",
         "score": 0.0, "strength": strength(0.0, available=False),
         "plain": "This build has no article text, so we cannot check whether anyone "
                  "denied the link. Left unscored rather than counted as a zero.",
         "math": "—"},
    ]
