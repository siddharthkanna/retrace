"""Marks an investigator's report against a scenario's correct answer."""

from scenarios.base import GroundTruth


def root_cause_is_right(root_cause: str, truth: GroundTruth) -> bool:
    """True if the root cause meets every requirement in the answer key."""
    text = root_cause.lower()
    named = all(any(wording in text for wording in group) for group in truth.must_name)
    return named and not any(wording in text for wording in truth.must_not_name)
