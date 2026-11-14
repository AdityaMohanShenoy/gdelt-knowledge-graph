import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

from campaigns import duration, fold_campaigns  # noqa: E402

REPORT = dt.date(2024, 2, 21)


def test_stated_durations_become_ranges():
    since = duration(["The farmers have been camping at Shambhu since then.",
                      "They have camped at the border since February 13."], REPORT, REPORT)
    assert since["start"] == "2024-02-13" and since["end"] == "2024-02-21" and since["stated"]
    days = duration(["The doctors ended nearly 50 days of cease work."], REPORT, REPORT)
    assert days["start"] == "2024-01-02"
    nth = duration(["Wangchuk's fast entered its 18th day."], REPORT, REPORT)
    assert nth["start"] == "2024-02-04"


def test_ongoing_wording_without_a_date_is_open_but_not_stated():
    r = duration(["The indefinite strike continued."], dt.date(2024, 2, 18), REPORT)
    assert r["start"] == "2024-02-18" and r["end"] == "2024-02-21" and not r["stated"]
    plain = duration(["Farmers blocked rail tracks."], REPORT, REPORT)
    assert plain["start"] == plain["end"] == "2024-02-21" and plain["basis"] is None


def test_episodes_fold_into_one_campaign_spanning_them():
    nodes = {"ce:a": {"description": "farmers camping", "search_status": "PARENTS_FOUND"},
             "ce:b": {"description": "farmers protesting at the border points",
                      "search_status": "NO_SUPPORTED_PARENT_FOUND"}}
    ranges = {"ce:a": {"start": "2024-02-13", "end": "2024-02-21", "stated": True},
              "ce:b": {"start": "2024-03-01", "end": "2024-03-01", "stated": False}}
    [camp] = fold_campaigns([["ce:b", "ce:a"]], nodes, ranges).values()
    assert camp["kind"] == "campaign" and camp["episodes"] == ["ce:a", "ce:b"]
    assert camp["date_range"] == ["2024-02-13", "2024-03-01"] and camp["range_stated"]
    assert camp["description"] == "farmers camping"
    assert camp["search_status"] == "PARENTS_FOUND"
