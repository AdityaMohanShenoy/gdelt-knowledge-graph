import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def load():
    path = ROOT / "pipeline" / "31_negative_controls.py"
    spec = importlib.util.spec_from_file_location("negative_controls", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _arm(grades):
    return [{"rc": str(i), "grade": g, "confidence": 0.5, "channels": {}}
            for i, g in enumerate(grades)]


def test_kept_rate_counts_only_the_grades_worth_standing_behind():
    nc = load()
    s = nc.summarise({"real": _arm(["confirmed", "reported", "pattern", "weak", "dropped"])})
    assert s["real"]["kept_rate"] == 0.6
    assert s["real"]["grades"]["weak"] == 1


def test_a_grade_firing_equally_on_both_has_no_discrimination():
    nc = load()
    s = nc.summarise({
        "real": _arm(["pattern", "weak", "weak", "weak"]),
        "shuffled": _arm(["pattern", "weak", "weak", "weak"]),
    })
    assert s["discrimination"]["pattern"] == 1.0, "identical shares must read as 1.0"


def test_discrimination_rewards_a_grade_that_separates():
    nc = load()
    s = nc.summarise({
        "real": _arm(["pattern", "pattern", "pattern", "weak"]),
        "shuffled": _arm(["pattern", "weak", "weak", "weak"]),
    })
    assert s["discrimination"]["pattern"] == 3.0


def test_a_grade_never_seen_in_the_control_is_not_a_division_by_zero():
    nc = load()
    s = nc.summarise({
        "real": _arm(["confirmed", "weak"]),
        "shuffled": _arm(["weak", "weak"]),
    })
    assert s["discrimination"]["confirmed"] is None


def test_false_positive_rate_is_reported_for_control_arms_only():
    nc = load()
    s = nc.summarise({
        "real": _arm(["pattern", "weak"]),
        "shuffled": _arm(["pattern", "weak"]),
        "future": _arm(["weak", "weak"]),
    })
    assert "false_positive_rate" not in s["real"]
    assert s["shuffled"]["false_positive_rate"] == 0.5
    assert s["future"]["false_positive_rate"] == 0.0
