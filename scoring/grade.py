"""Grade assignment and the plain-words strength scale."""

from .config import CAUSAL_FLOOR


def strength(v: float, available: bool = True) -> str:
    """Turn a 0-1 score into a word. A reader should not have to know whether
    0.43 is good."""
    if not available:
        return "unavailable"
    if v >= 0.70:
        return "strong"
    if v >= 0.40:
        return "moderate"
    if v >= 0.15:
        return "weak"
    if v > 0:
        return "very weak"
    return "none"


def grade(documented: float, corroboration: float, prior: float, contrastive: float,
          actors: float, suff: float, confidence: float, domains: int) -> tuple[str, str]:
    """Returns (grade, the rule in plain words)."""
    pattern_strength = (prior + contrastive + actors) / 3.0
    if documented >= 0.5 and corroboration >= 0.5:
        return "confirmed", (
            f"The pipeline recorded this link and {domains} separate outlets "
            f"carried it. Both bars cleared, so this is as strong as the "
            f"evidence here gets.")
    if documented >= 0.5:
        return "reported", (
            f"The pipeline recorded this link, but only {domains} outlets carried "
            f"it. Confirmed needs broader coverage — around 9 outlets at this "
            f"scale — so it stops one step short.")
    if pattern_strength >= 0.45 and suff >= 0.30:
        return "pattern", (
            f"Nobody recorded this link, but the data behind it is consistent: "
            f"{suff*100:.0f}% of the time this cause showed up, the effect "
            f"followed. Strong enough to keep, as a pattern rather than a "
            f"documented fact.")
    if confidence >= CAUSAL_FLOOR:
        return "weak", (
            "Nobody recorded this link, and no single check is strong enough to "
            "carry it on its own. Kept on the list, but nothing here would "
            "survive a challenge.")
    return "dropped", (
        "Every check came back near zero. Not shown as a cause, but kept "
        "with its scores as a training example.")
