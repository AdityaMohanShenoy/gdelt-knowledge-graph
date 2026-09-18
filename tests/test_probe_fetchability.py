import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))


def load_probe():
    path = ROOT / "pipeline" / "10_probe_fetchability.py"
    spec = importlib.util.spec_from_file_location("probe_fetchability", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_stratify_does_not_let_one_domain_dominate():
    probe = load_probe()
    urls = [f"https://big.test/a{i}" for i in range(500)]
    urls += [f"https://small{i}.test/x" for i in range(10)]

    sample, counts = probe.stratify(urls, 20)

    assert len(sample) == 20
    big = [u for u in sample if "big.test" in u]
    assert len(big) <= 11, "round-robin must cap the prolific domain, not fill the sample"
    assert counts["big.test"] == 500
    assert len({probe.host_of(u) for u in sample}) == 11


def test_stratify_falls_back_to_available_urls():
    probe = load_probe()
    sample, _ = probe.stratify(["https://a.test/1", "https://b.test/1"], 50)
    assert sorted(sample) == ["https://a.test/1", "https://b.test/1"]


def test_detect_language_prefers_the_html_lang_attribute():
    probe = load_probe()
    assert probe.detect_language(b"<html lang='en-IN'><body>x", "hello there") == "en-in"
    assert probe.detect_language(b'<html lang="hi">', "x") == "hi"


def test_detect_language_falls_back_to_script_ranges():
    probe = load_probe()
    devanagari = "किसानों ने विरोध प्रदर्शन किया और सरकार से बातचीत की मांग की"
    assert "devanagari" in probe.detect_language(b"<html><body>", devanagari)
    assert probe.detect_language(b"<html><body>", "a plain english sentence") == "en"
    assert probe.detect_language(b"", "") == "unknown"
