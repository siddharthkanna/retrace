"""Runs scenarios through the investigator and marks each report."""

import argparse
import json
import time
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean

import httpx

from evals.grading import root_cause_is_right
from scenarios.base import INVESTIGATOR, Scenario, open_incident, reset
from scenarios.run import SCENARIOS

RESULTS = Path(__file__).parent / "results"
_POLL_S = 5
_GIVE_UP_AFTER_S = 1800


@dataclass(frozen=True)
class Trial:
    """One scenario investigated once, and how it went."""

    scenario: str
    model: str
    mark: str  # "right", "wrong" or "no_report"
    reproduced: bool
    tool_calls: int
    seconds: float
    tokens: int
    # Only known when the model's prices are set.
    cost_usd: float | None
    report: dict | None


def run_trial(scenario: Scenario) -> Trial:
    reset()
    incident_id = open_incident(scenario.trigger())
    started = time.monotonic()
    investigation = _investigate(incident_id)
    report = investigation["report"]
    usage = investigation.get("usage") or {}
    return Trial(
        scenario=scenario.id,
        model=investigation["model"],
        mark=_mark(report, scenario),
        reproduced=(investigation["reproduction"] or {}).get("outcome") == "reproduced",
        tool_calls=len(investigation["evidence"]),
        seconds=round(time.monotonic() - started, 1),
        tokens=usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
        cost_usd=usage.get("cost_usd"),
        report=report,
    )


def _investigate(incident_id: int) -> dict:
    """Start an investigation and wait for it to finish."""
    url = f"{INVESTIGATOR}/incidents/{incident_id}"
    httpx.post(f"{url}/investigate").raise_for_status()
    deadline = time.monotonic() + _GIVE_UP_AFTER_S
    while time.monotonic() < deadline:
        (investigation,) = httpx.get(f"{url}/investigations").json()
        outcome = (investigation["reproduction"] or {}).get("outcome")
        if outcome == "awaiting_approval":
            # The eval approves every recipe, as a person watching would.
            approve = f"{INVESTIGATOR}/investigations/{investigation['id']}/approve"
            httpx.post(approve).raise_for_status()
        elif investigation["status"] != "running" and outcome != "running":
            return investigation
        time.sleep(_POLL_S)
    raise TimeoutError(f"the investigation of incident {incident_id} did not finish")


def _mark(report: dict | None, scenario: Scenario) -> str:
    if report is None:
        return "no_report"
    right = root_cause_is_right(report["root_cause"], scenario.ground_truth)
    return "right" if right else "wrong"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trials", type=int, default=3, help="Trials per scenario.")
    parser.add_argument("--scenario", choices=list(SCENARIOS), action="append")
    args = parser.parse_args()

    RESULTS.mkdir(exist_ok=True)
    path = RESULTS / f"{datetime.now(UTC):%Y-%m-%dT%H-%M-%S}.jsonl"
    trials = []
    for scenario_id in args.scenario or SCENARIOS:
        for _ in range(args.trials):
            trial = run_trial(SCENARIOS[scenario_id])
            with path.open("a") as file:
                file.write(json.dumps(asdict(trial)) + "\n")
            print(
                f"{trial.scenario}: {trial.mark} ({trial.tool_calls} tool calls, {trial.seconds}s)",
                flush=True,
            )
            trials.append(trial)
    reset()
    _print_summary(trials)
    print(f"\nSaved to {path}")


def _print_summary(trials: list[Trial]) -> None:
    print(
        f"\n{'scenario':<28}{'right':>6}{'wrong':>6}{'no report':>10}{'reproduced':>11}"
        f"{'avg calls':>10}{'avg s':>7}{'avg tokens':>11}{'avg $':>8}"
    )
    for scenario_id in dict.fromkeys(t.scenario for t in trials):
        mine = [t for t in trials if t.scenario == scenario_id]
        marks = Counter(t.mark for t in mine)
        print(
            f"{scenario_id:<28}{marks['right']:>6}{marks['wrong']:>6}{marks['no_report']:>10}"
            f"{sum(t.reproduced for t in mine):>11}"
            f"{mean(t.tool_calls for t in mine):>10.1f}{mean(t.seconds for t in mine):>7.0f}"
            f"{mean(t.tokens for t in mine):>11,.0f}{_average_cost(mine):>8}"
        )


def _average_cost(trials: list[Trial]) -> str:
    costs = [t.cost_usd for t in trials if t.cost_usd is not None]
    return f"{mean(costs):.3f}" if costs else "-"


if __name__ == "__main__":
    main()
