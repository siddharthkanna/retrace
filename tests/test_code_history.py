"""Checks for list_commits and show_commit, run against a temporary repository."""

import subprocess
from dataclasses import dataclass

import pytest
from pydantic import ValidationError

from investigator.tools.code_history import (
    MAX_DIFF_LINES,
    ListCommitsInput,
    ListCommitsOutput,
    Repo,
    ShowCommitInput,
    ShowCommitOutput,
    list_commits,
    show_commit,
)

EMAIL = "author@example.invalid"


@dataclass(frozen=True)
class History:
    """A repository with a known history. Only its `app` folder may be shown."""

    root: str
    first: str  # app/a.py, plus a hidden file
    hidden_only: str  # hidden files only; its message contains SECRET
    change: str  # app/a.py and app/controls.py, plus a hidden file
    big: str  # a 600-line file
    side: str  # on a branch that was never merged

    def repo(self, **settings) -> Repo:
        return Repo(dir=self.root, paths=("app",), **settings)


@pytest.fixture(scope="module")
def history(tmp_path_factory) -> History:
    root = tmp_path_factory.mktemp("repo")

    def git(*args: str, day: int = 1) -> str:
        date = f"2026-01-0{day}T12:00:00+00:00"
        result = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "-c",
                "user.name=Test Author",
                "-c",
                f"user.email={EMAIL}",
                *args,
            ],
            check=True,
            capture_output=True,
            text=True,
            env={"GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date},
        )
        return result.stdout.strip()

    def commit(message: str, day: int, files: dict[str, str]) -> str:
        for path, text in files.items():
            (root / path).parent.mkdir(parents=True, exist_ok=True)
            (root / path).write_text(text)
        git("add", "-A")
        git("commit", "-q", "-m", message, day=day)
        return git("rev-parse", "HEAD")

    git("init", "-q", "-b", "main")
    first = commit("first", 1, {"app/a.py": "x = 1\n", "hidden/answer.py": "CAUSE = 1\n"})
    hidden_only = commit("hidden only SECRET", 2, {"hidden/answer.py": "CAUSE = 2\n"})
    change = commit(
        "change a",
        3,
        {"app/a.py": "x = 2\n", "app/controls.py": "SWITCH = True\n", "hidden/more.py": "y = 1\n"},
    )
    big = commit("add big file", 4, {"app/big.py": "".join(f"line {i}\n" for i in range(600))})
    git("checkout", "-q", "-b", "side", first)
    side = commit("side branch work", 5, {"app/side.py": "s = 1\n"})
    git("checkout", "-q", "main")
    return History(str(root), first, hidden_only, change, big, side)


def _list(repo: Repo, **filters) -> ListCommitsOutput:
    return list_commits(repo, ListCommitsInput(**filters))


def _show(repo: Repo, **request) -> ShowCommitOutput:
    return show_commit(repo, ShowCommitInput(**request))


def _messages(output: ListCommitsOutput) -> list[str]:
    return [commit.message for commit in output.commits]


def _everything_returned(history: History) -> str:
    """All the text both tools return for the visible history."""
    repo = history.repo()
    return _list(repo).model_dump_json() + _show(repo, commit=history.change).model_dump_json()


def test_list_returns_commits_newest_first_with_their_files(history):
    result = _list(history.repo())

    assert _messages(result) == ["add big file", "change a", "first"]
    assert [file.path for file in result.commits[1].files] == ["app/a.py", "app/controls.py"]
    assert not result.truncated


def test_hidden_folders_and_their_commits_never_appear(history):
    returned = _everything_returned(history)

    assert "hidden" not in returned
    assert "SECRET" not in returned


def test_the_authors_email_never_appears(history):
    returned = _everything_returned(history)

    assert "Test Author" in returned
    assert EMAIL not in returned


def test_since_until_and_limit_narrow_the_list(history):
    repo = history.repo()

    assert _messages(_list(repo, since="2026-01-03T00:00:00Z")) == ["add big file", "change a"]
    assert _messages(_list(repo, until="2026-01-03T23:00:00Z")) == ["change a", "first"]

    limited = _list(repo, limit=1)
    assert _messages(limited) == ["add big file"]
    assert limited.truncated


@pytest.mark.parametrize(
    "path", ["hidden", "app/../hidden", "apple", "/etc/passwd", ":(top)hidden", "--output=x"]
)
def test_a_path_outside_the_allowed_folders_is_refused(history, path):
    assert "outside" in _list(history.repo(), path=path).error
    assert "outside" in _show(history.repo(), commit=history.change, path=path).error


def test_a_path_inside_the_allowed_folders_narrows_the_result(history):
    repo = history.repo()

    assert _messages(_list(repo, path="app/big.py")) == ["add big file"]
    assert "controls" not in _show(repo, commit=history.change, path="app/a.py").diff


def test_a_hidden_file_is_left_out_of_the_list_and_the_diff(history):
    repo = history.repo(exclude=("app/controls.py",))

    assert [file.path for file in _list(repo).commits[1].files] == ["app/a.py"]
    assert "SWITCH" not in _show(repo, commit=history.change).diff


def test_show_returns_the_changed_lines(history):
    result = _show(history.repo(), commit=history.change[:7])

    assert result.commit.message == "change a"
    assert "-x = 1" in result.diff
    assert "+x = 2" in result.diff
    assert not result.truncated


def test_a_long_diff_is_capped_and_says_so(history):
    result = _show(history.repo(), commit=history.big)

    assert len(result.diff.splitlines()) == MAX_DIFF_LINES
    assert result.truncated


def test_commits_before_the_baseline_cannot_be_listed_or_opened(history):
    repo = history.repo(baseline=history.change)

    assert _messages(_list(repo)) == ["add big file"]
    assert "not available" in _show(repo, commit=history.first).error
    assert "not available" in _show(repo, commit=history.change).error
    assert _show(repo, commit=history.big).error is None


@pytest.mark.parametrize("which", ["hidden_only", "side"])
def test_commits_outside_the_visible_history_cannot_be_opened(history, which):
    result = _show(history.repo(), commit=getattr(history, which))

    assert "not available" in result.error
    assert result.commit is None
    assert result.diff == ""


def test_an_unknown_commit_is_not_available(history):
    assert "not available" in _show(history.repo(), commit="abcdef1").error


@pytest.mark.parametrize("commit", ["main", "HEAD", "--help", "abc", "ABCDEF1"])
def test_only_commit_ids_are_accepted(commit):
    with pytest.raises(ValidationError):
        ShowCommitInput(commit=commit)


def test_with_no_repository_both_tools_say_so():
    assert _list(Repo()).error == "No code history is available."
    assert _show(Repo(), commit="abcdef1").error == "No code history is available."


def test_with_no_allowed_paths_the_whole_repository_may_be_shown(history):
    everything = Repo(dir=history.root)

    messages = [commit.message for commit in _list(everything).commits]

    assert "hidden only SECRET" in messages
    assert _list(everything, path="hidden").commits
