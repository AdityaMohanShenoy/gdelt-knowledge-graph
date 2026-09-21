"""argparse %-formats help strings, so a literal % in one raises only when
--help is reached. A malformed string killed every refetch batch instantly
while the supervisor reported the run as merely slow."""

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = sorted(
    p for p in (ROOT / "pipeline").glob("*.py")
    if p.name[0].isdigit() or p.name.startswith("probe_")
)


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_help_renders(script):
    result = subprocess.run(
        [sys.executable, str(script), "--help"],
        capture_output=True, text=True, cwd=ROOT, timeout=120,
    )
    assert result.returncode == 0, f"{script.name} --help failed:\n{result.stderr[-600:]}"
    assert "usage:" in result.stdout
