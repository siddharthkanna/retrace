"""Trigger an incident: python -m scenarios.run <scenario-id> (or: reset)."""

import argparse

from scenarios import charge_without_record, double_charge, double_refund
from scenarios.base import open_incident, reset

SCENARIOS = {
    s.id: s
    for s in (double_charge.SCENARIO, charge_without_record.SCENARIO, double_refund.SCENARIO)
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", choices=[*SCENARIOS, "reset"])
    args = parser.parse_args()

    reset()
    if args.scenario == "reset":
        print("Both services are back to healthy defaults.")
        return
    report = SCENARIOS[args.scenario].trigger()
    incident_id = open_incident(report)
    print(f"Incident #{incident_id} opened ({report.severity}): {report.description}")


if __name__ == "__main__":
    main()
