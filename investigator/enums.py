"""The fixed sets of values an incident field can take."""

from enum import StrEnum


class Severity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Status(StrEnum):
    OPEN = "open"
    INVESTIGATING = "investigating"
    RESOLVED = "resolved"
    FAILED = "failed"


class InvestigationStatus(StrEnum):
    RUNNING = "running"
    RESOLVED = "resolved"
    FAILED = "failed"


class Source(StrEnum):
    REPORTED = "reported"
    WATCHER = "watcher"
