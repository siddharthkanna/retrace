"""A guard: nothing the investigator is allowed to read may give away the test setup."""

import json
import os
from pathlib import Path

import pytest

GIVEAWAYS = ("chaos", "scenario", "investigat", "ground truth", "on purpose", "fault injection")


def _visible_files() -> list[Path]:
    """Every source file inside the paths the investigator's code-history tools may show."""
    files: list[Path] = []
    for allowed in json.loads(os.environ["TARGET_REPO_PATHS"]):
        path = Path(allowed)
        if path.is_file():
            files.append(path)
        else:
            files += sorted(p for p in path.rglob("*") if p.suffix in (".py", ".sql"))
    return files


def test_there_are_visible_files_to_check():
    assert len(_visible_files()) > 10


@pytest.mark.parametrize("path", _visible_files(), ids=str)
def test_visible_code_does_not_give_away_the_test_setup(path):
    text = path.read_text().lower()

    assert [word for word in GIVEAWAYS if word in text] == []
