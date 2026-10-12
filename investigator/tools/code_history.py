"""list_commits and show_commit: look at recent changes to the target system's code."""

import posixpath
import subprocess
from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

DEFAULT_COMMITS = 20
MAX_COMMITS = 50


@dataclass(frozen=True)
class Repo:
    """Where the code history is, and how much of it may be shown."""

    dir: str | None = None
    paths: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    baseline: str | None = None


class ListCommitsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    since: datetime | None = Field(
        default=None, description="Only commits at or after this time (ISO 8601)."
    )
    until: datetime | None = Field(
        default=None, description="Only commits at or before this time (ISO 8601)."
    )
    path: str | None = Field(
        default=None, min_length=1, description="Only commits that changed this file or folder."
    )
    limit: int = Field(
        default=DEFAULT_COMMITS, ge=1, le=MAX_COMMITS, description="The most commits to return."
    )


class FileChange(BaseModel):
    path: str
    lines_added: int
    lines_removed: int


class Commit(BaseModel):
    id: str
    timestamp: datetime
    author: str
    message: str
    files: list[FileChange]


class ListCommitsOutput(BaseModel):
    commits: list[Commit] = []
    truncated: bool = False
    # Set when the request was refused or no code history is available.
    error: str | None = None


_GIT_TIMEOUT_S = 10
# Characters git is told to print between commits and between fields. They never
# appear in normal text, so a commit message can't be mistaken for a separator.
_RECORD, _FIELD = "\x1e", "\x1f"
_LOG_FORMAT = f"--format={_RECORD}%h{_FIELD}%aI{_FIELD}%an{_FIELD}%B{_FIELD}"


class CodeHistoryError(Exception):
    """The request was refused, or git could not answer it."""


def list_commits(repo: Repo, request: ListCommitsInput) -> ListCommitsOutput:
    """Return recent commits that changed the allowed paths, newest first."""
    try:
        args = ["log", _LOG_FORMAT, "--numstat", f"--max-count={request.limit + 1}"]
        if request.since is not None:
            args.append(f"--since={request.since.isoformat()}")
        if request.until is not None:
            args.append(f"--until={request.until.isoformat()}")
        args.append(_history_range(repo))
        output = _git(repo, [*args, "--", *_pathspecs(repo, request.path)])
    except CodeHistoryError as exc:
        return ListCommitsOutput(error=str(exc))

    commits = [_parse_commit(record) for record in output.split(_RECORD)[1:]]
    return ListCommitsOutput(
        commits=commits[: request.limit], truncated=len(commits) > request.limit
    )


def _pathspecs(repo: Repo, path: str | None) -> list[str]:
    """The paths git may look at: all the allowed ones, or one narrower path inside them."""
    if repo.dir is None or not repo.paths:
        raise CodeHistoryError("No code history is available.")
    if path is None:
        included = repo.paths
    else:
        path = posixpath.normpath(path)
        if not any(path == allowed or path.startswith(f"{allowed}/") for allowed in repo.paths):
            raise CodeHistoryError(f"'{path}' is outside the code this tool may show.")
        included = (path,)
    # "literal" switches off git's special path syntax; "exclude" hides a file.
    return [
        *(f":(literal){p}" for p in included),
        *(f":(exclude,literal){p}" for p in repo.exclude),
    ]


def _git(repo: Repo, args: list[str]) -> str:
    """Run git with a list of arguments (never through a shell) and return its output."""
    try:
        result = subprocess.run(
            ["git", f"--git-dir={repo.dir}/.git", *args],
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CodeHistoryError(f"git could not be run ({type(exc).__name__}).") from exc
    if result.returncode != 0:
        raise CodeHistoryError((result.stderr.strip().splitlines() or ["git failed."])[0])
    return result.stdout


def _parse_commit(record: str) -> Commit:
    commit_id, timestamp, author, message, numstat = record.split(_FIELD)
    files = []
    for line in numstat.strip().splitlines():
        added, removed, path = line.split("\t")
        files.append(
            FileChange(path=path, lines_added=_count(added), lines_removed=_count(removed))
        )
    return Commit(
        id=commit_id, timestamp=timestamp, author=author, message=message.strip(), files=files
    )


def _count(value: str) -> int:
    return 0 if value == "-" else int(value)  # git prints "-" for files that are not text


MAX_DIFF_LINES = 400


class ShowCommitInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    commit: str = Field(
        pattern=r"^[0-9a-f]{7,40}$",
        description="The commit ID, as returned by list_commits.",
    )
    path: str | None = Field(
        default=None,
        min_length=1,
        description="Show only the changes to this file or folder.",
    )


class ShowCommitOutput(BaseModel):
    commit: Commit | None = None
    diff: str = ""
    truncated: bool = False
    # Set when the request was refused or failed.
    error: str | None = None


def show_commit(repo: Repo, request: ShowCommitInput) -> ShowCommitOutput:
    """Return one commit's details and changed lines, limited to the allowed paths."""
    unavailable = CodeHistoryError(f"Commit {request.commit} is not available.")
    try:
        allowed = _pathspecs(repo, None)
        # Only commits the agent could have found through list_commits may be opened.
        visible = _git(repo, ["rev-list", _history_range(repo)]).split()
        matches = [commit_id for commit_id in visible if commit_id.startswith(request.commit)]
        if len(matches) != 1:
            raise unavailable
        summary = _git(repo, ["show", _LOG_FORMAT, "--numstat", matches[0], "--", *allowed])
        records = summary.split(_RECORD)[1:]
        if not records:  # the commit changed nothing in the allowed paths
            raise unavailable
        diff = _git(repo, ["show", "--format=", matches[0], "--", *_pathspecs(repo, request.path)])
    except CodeHistoryError as exc:
        return ShowCommitOutput(error=str(exc))

    lines = diff.strip().splitlines()
    return ShowCommitOutput(
        commit=_parse_commit(records[0]),
        diff="\n".join(lines[:MAX_DIFF_LINES]),
        truncated=len(lines) > MAX_DIFF_LINES,
    )


def _history_range(repo: Repo) -> str:
    """The commits that may be shown: after the baseline if one is set, up to now."""
    return f"{repo.baseline}..HEAD" if repo.baseline else "HEAD"
