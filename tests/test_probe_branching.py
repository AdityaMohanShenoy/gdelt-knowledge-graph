import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def load_probe():
    path = ROOT / "pipeline" / "probe_branching.py"
    spec = importlib.util.spec_from_file_location("probe_branching", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_counter = iter(range(1, 10_000))


def _row(target, depth, accept, events=1):
    return {
        "seed_id": "s1", "depth": str(depth), "target_id": target,
        "cand_group_id": f"g{next(_counter)}",
        "event_count": str(events), "accept": accept,
    }


def test_branching_factor_counts_accepted_parents_per_target():
    probe = load_probe()
    # depth 1: one target with 3 accepted of 5 retrieved
    rows = [_row("t1", 1, "y"), _row("t1", 1, "y"), _row("t1", 1, "y"),
            _row("t1", 1, "n"), _row("t1", 1, "n")]
    # depth 2: two targets, 1 and 3 accepted
    rows += [_row("t2", 2, "y"), _row("t2", 2, "n")]
    rows += [_row("t3", 2, "y"), _row("t3", 2, "y"), _row("t3", 2, "y")]

    s = probe.summarize(rows)

    assert s["judged_rows"] == 10
    assert s["by_depth"][1]["mean_accepted"] == 3.0
    assert s["by_depth"][1]["mean_retrieved"] == 5.0
    assert s["by_depth"][2]["mean_accepted"] == 2.0      # (1 + 3) / 2
    assert s["branching_factor"] == round((3 + 1 + 3) / 3, 2)


def test_gate_turns_on_the_threshold():
    probe = load_probe()
    low = probe.summarize([_row("t1", 1, "y"), _row("t1", 1, "y"), _row("t1", 1, "n")])
    assert low["branching_factor"] == 2.0
    assert low["gate_passed"] is True

    high = probe.summarize([_row("t1", 1, "y") for _ in range(9)])
    assert high["branching_factor"] == 9.0
    assert high["gate_passed"] is False
    # 500 seeds * (9 + 81 + 729)
    assert high["projected_group_edges"] == 500 * (9 + 81 + 729)


def test_blank_rows_are_never_read_as_rejections():
    probe = load_probe()
    # One accepted, two not yet looked at. Treating the blanks as "n" would
    # report a branching factor of 1 from a target nobody finished judging.
    rows = [_row("t1", 1, "y"), _row("t1", 1, ""), _row("t1", 1, "  ")]

    s = probe.summarize(rows)

    assert s["judged_rows"] == 0
    assert s["targets_judged"] == 0
    assert s["targets_partially_judged"] == 1
    assert s["branching_factor"] == 0.0


def test_instance_edges_scale_by_group_size():
    probe = load_probe()
    rows = [_row("t1", 1, "y", events=6), _row("t1", 1, "y", events=4)]
    s = probe.summarize(rows)
    assert s["branching_factor"] == 2.0
    # Mean per group (6 and 4), not their sum: instance edges are
    # group_edges x mean group size.
    assert s["mean_events_per_accepted_group"] == 5.0
    assert s["projected_instance_edges"] == s["projected_group_edges"] * 5


def test_partially_judged_targets_are_dropped_not_averaged_in():
    probe = load_probe()
    rows = [_row("full", 1, "y"), _row("full", 1, "n"),
            _row("half", 1, "y"), _row("half", 1, "")]

    s = probe.summarize(rows)

    assert s["targets_judged"] == 1
    assert s["targets_partially_judged"] == 1
    # "half" would have contributed 1 accepted and dragged the mean to 1.0
    assert s["branching_factor"] == 1.0
    assert s["by_depth"][1]["targets"] == 1


def test_sampling_keeps_targets_whole():
    probe = load_probe()
    rows = []
    for t in range(6):
        for _ in range(14):
            rows.append(_row(f"t{t}", 1, ""))
    for t in range(6, 12):
        for _ in range(14):
            rows.append(_row(f"t{t}", 2, ""))

    sample = probe.sample_for_judging(rows, targets_per_depth=2)

    by_target = {}
    for r in sample:
        by_target.setdefault(r["target_id"], []).append(r)
    assert len(by_target) == 4, "2 targets per depth across 2 depths"
    assert all(len(v) == 14 for v in by_target.values()), "every sampled target must be complete"
    assert {int(r["depth"]) for r in sample} == {1, 2}


def _sentinel(target, depth):
    return {"seed_id": "s1", "depth": str(depth), "target_id": target,
            "cand_group_id": "", "event_count": "0", "accept": "-"}


def test_targets_with_no_candidates_count_as_zero_not_as_missing():
    probe = load_probe()
    rows = [_row("has", 1, "y"), _row("has", 1, "y"), _row("has", 1, "n")]
    rows.append(_sentinel("none", 1))

    s = probe.summarize(rows)

    assert s["targets_judged"] == 2
    # Ignoring the childless target would report 2.0 by averaging only over
    # events that happen to have parents.
    assert s["branching_factor"] == 1.0
    assert s["by_depth"][1]["min_accepted"] == 0
    assert s["by_depth"][1]["mean_retrieved"] == 1.5


def test_sentinels_alone_cannot_decide_the_gate():
    probe = load_probe()
    # An untouched worksheet: every real row blank, only no-candidate sentinels
    # are "done". This must not read as a completed, passing measurement.
    rows = [_row("real", 1, ""), _row("real", 1, "")]
    rows += [_sentinel("none1", 1), _sentinel("none2", 1)]

    s = probe.summarize(rows)

    assert s["targets_with_candidates_judged"] == 0, "guard must see nothing judged"
    assert s["targets_judged"] == 2, "sentinels are complete, but decide nothing"
