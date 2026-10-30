import hashlib
import importlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

evaluation = importlib.import_module("focal_event_evaluation")
CLI = [sys.executable, str(ROOT / "pipeline" / "10_extract_focal_events.py")]


def words(article_id, count=100):
    return " ".join(f"w{article_id}x{index}" for index in range(count))


def record(article_id, text=None, url=None, content_hash=None, day=20240601):
    text = words(article_id) if text is None else text
    return {
        "schema_version": "focal-event-gold.v1",
        "article_id": article_id,
        "article_text_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "headline": f"Headline {article_id}",
        "article_text": text,
        "sentences": [
            {"sentence_id": 1, "paragraph_id": 1, "text": text, "start_char": 0,
             "end_char": len(text)}
        ] if text else [],
        **evaluation.blank_labels(),
        "screening": {"text_quality": {"status": "READABLE"}},
        "entity_schema": {"LOCATION": "Named places"},
        "source_metadata": {
            "url_key": url or f"https://outlet{int(article_id[1:]) % 7}.in/{article_id}",
            "final_url": None,
            "content_hash": content_hash,
            "gdelt_observations": [{"day": day}],
        },
    }


def drafted(item):
    item.update(
        reviewer="Codex (AI)",
        label_source="ai_assisted",
        focal_event_summary="Farmers marched",
        supporting_sentence_ids=[1],
        ai_proposal={"disposition": "USABLE"},
    )
    item["eligibility"]["protest_relevance"] = "PROTEST"
    return item


def grouped(records):
    ids = [r["article_id"] for r in records]
    return sorted(sorted(ids[i] for i in g) for g in evaluation.split_groups(records))


def test_duplicates_are_grouped_and_empty_texts_are_not():
    near = words("c1").split()
    near[50] = "changed"
    records = [
        record("a1", url="https://x.in/same"),
        record("a2", url="https://x.in/same"),
        record("b1", content_hash="h"),
        record("b2", content_hash="h"),
        record("c1"),
        record("c2", text=" ".join(near)),
        record("d1", text=""),
        record("d2", text=""),
    ]
    assert grouped(records) == [["a1", "a2"], ["b1", "b2"], ["c1", "c2"], ["d1"], ["d2"]]
    assignment, groups = evaluation.assign_splits(records, set(), "s", 0.4, 0.2)
    for group in groups:
        assert len({assignment[member] for member in group}) == 1


def test_pilot_and_its_duplicates_never_reach_test():
    records = [record(f"r{i}") for i in range(40)]
    records.append(record("dup", url=records[0]["source_metadata"]["url_key"]))
    for seed in ("a", "b", "c", "d"):
        assignment, _ = evaluation.assign_splits(records, {"r0", "r1"}, seed, 0.5, 0.2)
        assert assignment["r0"] == assignment["r1"] == assignment["dup"] == "pilot"
        assert "pilot" not in {assignment[f"r{i}"] for i in range(2, 40)}


def test_assignment_is_stable_and_proportional():
    records = [record(f"r{i}") for i in range(100)]
    first, _ = evaluation.assign_splits(records, set(), "seed", 0.2, 0.2)
    again, _ = evaluation.assign_splits(list(reversed(records)), set(), "seed", 0.2, 0.2)
    other, _ = evaluation.assign_splits(records, set(), "other", 0.2, 0.2)
    assert first == again
    assert first != other
    assert sorted(first.values()).count("test") == 20
    assert sorted(first.values()).count("dev") == 20


def test_cli_blinds_test_records_keeps_drafts_elsewhere_and_never_overwrites(tmp_path):
    records = [drafted(record(f"r{i}")) for i in range(30)]
    source = tmp_path / "packet.jsonl"
    source.write_text("".join(json.dumps(r) + "\n" for r in records))
    pilot = tmp_path / "pilot.jsonl"
    pilot.write_text(json.dumps({"article_id": "r0"}) + "\n")
    output = tmp_path / "packet.splits.jsonl"
    command = CLI + ["split", "--input", str(source), "--pilot", str(pilot),
                     "--output", str(output)]
    original = source.read_bytes()

    result = subprocess.run(command, text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr
    assert source.read_bytes() == original
    written = [json.loads(line) for line in output.read_text().splitlines()]
    manifest = json.loads(output.with_suffix(".manifest.json").read_text())
    assert manifest["output_sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()
    assert {r["article_id"]: r["split"] for r in written} == manifest["assignment"]
    assert manifest["pilot_ids_matched"] == 1

    by_id = {r["article_id"]: r for r in records}
    tests = [r for r in written if r["split"] == "test"]
    assert tests and manifest["blinded_test_articles"] == len(tests)
    for blind in tests:
        assert "ai_proposal" not in blind
        assert blind["reviewer"] is None and blind["focal_event_summary"] is None
        assert blind["supporting_sentence_ids"] == []
        assert blind["eligibility"]["protest_relevance"] is None
        for key in evaluation.SNAPSHOT_KEYS:
            assert blind[key] == by_id[blind["article_id"]][key]
    kept = [r for r in written if r["split"] != "test"]
    assert all(r["reviewer"] == "Codex (AI)" and "ai_proposal" in r for r in kept)

    again = subprocess.run(command, text=True, capture_output=True, check=False)
    assert again.returncode != 0 and "already exists" in again.stderr


def test_cli_refuses_input_that_already_has_reviews(tmp_path):
    records = [record(f"r{i}") for i in range(5)]
    records[3]["eligibility"]["review_status"] = "REVIEWED"
    source = tmp_path / "reviewed.jsonl"
    source.write_text("".join(json.dumps(r) + "\n" for r in records))
    output = tmp_path / "out.jsonl"
    result = subprocess.run(
        CLI + ["split", "--input", str(source), "--pilot", str(source), "--output", str(output)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0 and "already reviewed" in result.stderr
    assert not output.exists()
