# Retrace

An AI agent that finds the root cause of an API incident and proves it.

You describe what went wrong in one sentence. Retrace reads your logs, traces, database,
settings and recent commits, writes a report that cites its evidence, and then makes the
failure happen again on a test copy, after you approve.

## Try it

You need [Docker Desktop](https://www.docker.com/products/docker-desktop/) and a key for any
model served in the OpenAI format.

```bash
cp .env.example .env    # then fill in LLM_BASE_URL, LLM_MODEL and LLM_API_KEY
make demo
```

This starts Retrace with a small payment system and makes one payment get refunded twice.
Open <http://localhost:5173>, choose the incident and click **Investigate**. A few minutes
later you have the report. Click **Approve** to let it reproduce the failure.

Leave the model lines empty to use a local Ollama model instead: free, but far less accurate.

## Use it on your own project

Start Retrace on its own with `docker compose up`, open <http://localhost:5173> and click
**New incident**.

Then connect what you have in `.env`. Every line is optional; the agent only gets the tools
for what is connected.

| Line in `.env` | Lets the agent |
|---|---|
| `TARGET_DATABASE_URL` | Read your Postgres data (always read-only) |
| `TARGET_REPO` | Read recent commits |
| `CONFIG_SOURCES` | Read your settings, from an address that returns JSON |
| `TARGET_API_URL` | Reproduce the failure. Point it at a test copy only |

Send your logs and traces to Retrace with OpenTelemetry:

```bash
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:8002
OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
OTEL_METRICS_EXPORTER=none    # Retrace takes logs and traces, not metrics
```

From inside Docker, use `http://host.docker.internal:8002`. `examples/bookings` is a small
API connected this way, with a script that causes an incident.

## Commands

| Command | What it does |
|---|---|
| `make demo` | Start everything and cause an incident |
| `make demo SCENARIO=double_charge` | The same, with another failure |
| `make eval` | Measure how often the agent finds the right cause |
| `make test` | Run the linter and tests |
| `make reset` | Put the payment system back to healthy |
| `make stop` | Stop everything (your data is kept) |
| `docker compose down -v` | Stop everything and delete all data |

Scenarios: `double_refund`, `double_charge`, `charge_without_record`, and
`double_refund_injected`, which plants a misleading note in the logs.

## What's inside

| Folder | What it is |
|---|---|
| `investigator/` | The agent, its tools and its API |
| `viewer/` | The web page |
| `services/`, `scenarios/` | The payment system and the ways it can break |
| `evals/` | The accuracy check |
| `examples/bookings/` | A separate API to try Retrace on |
