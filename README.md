# Retrace

An agent that investigates API incidents and proves
its root cause by reproducing the failure.

You report what went wrong in plain words. The agent reads the system's logs, traces,
database, settings and recent code changes, writes a report that cites its evidence, and
then tries to make the same failure happen again on a test copy of the system.

The repository has three parts:

| Part | Folder | What it is |
|---|---|---|
| Test-bed | `services/`, `scenarios/` | A small payment system that can be made to fail in known ways |
| Investigator | `investigator/`, `viewer/` | The agent, its API, and a web page for reading investigations |
| Eval | `evals/` | Measures how often the agent finds the right cause |

## Try it on the built-in example

You need [Docker Desktop](https://www.docker.com/products/docker-desktop/) and a key for
a model served in the OpenAI format.

1. Tell Retrace which model to use:

   ```bash
   cp .env.example .env
   ```

   Open `.env` and fill in the model's address, its name and your key.

2. Start Retrace with the payment system and cause an incident:

   ```bash
   make demo
   ```

   This makes one payment get refunded twice, and reports it as an incident.

3. Open <http://localhost:5173>, select the incident and click **Investigate**.

   The page updates by itself. After a few minutes it shows the root cause and the
   evidence behind it.

4. The agent then proposes a recipe to make the failure happen again: which settings to
   change and which requests to send. Nothing is sent until you click **Approve**. Click
   **Decline** to stop there. To let the agent go ahead without asking, set
   `REPRODUCTION_NEEDS_APPROVAL=false` in `.env`.

## Use it on your own project

Nothing in the investigator is specific to payments. Fill in the second half of `.env`
with what you have, then start Retrace on its own:

```bash
docker compose up
```

Open <http://localhost:5173>, click **New incident**, describe what went wrong and click
**Investigate**.

Every line is optional. The agent is only given the tools for what is connected.

| Line in `.env` | What the agent can then do | What your project needs |
|---|---|---|
| `TARGET_DATABASE_URL` | Read the system's data | A Postgres database. Retrace opens it read-only, whatever login you give |
| `TARGET_REPO` | Read recent code changes | A git repository on this machine |
| `CONFIG_SOURCES` | Read settings and feature switches | An address that returns the current settings as JSON |
| `TARGET_API_URL` | Reproduce the failure | An API that describes itself at `/openapi.json`, a settings address that accepts `PUT`, and the database line above |

### Logs and traces

Retrace receives logs and traces in the [OpenTelemetry](https://opentelemetry.io) format
and keeps them in its own database. Tell your project to send them to Retrace:

```bash
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:8002
OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
OTEL_METRICS_EXPORTER=none
```

If your project already uses OpenTelemetry, those three settings are all it needs. If it
doesn't, add the OpenTelemetry library for your language first; it exists for Python, Go,
Node, Java and others. Logs kept in files can be forwarded by the
[OpenTelemetry Collector](https://opentelemetry.io/docs/collector/).

A project running inside Docker reaches Retrace at `http://host.docker.internal:8002`.

Only ever point `TARGET_API_URL` at a test or staging copy. Reproduction sends real
requests and changes settings while it runs.

### A worked example

`examples/bookings` is a small room-booking API that knows nothing about Retrace. It has
its own database and uses only the standard OpenTelemetry library. To connect it:

1. Start it, and add these lines to Retrace's `.env`:

   ```bash
   docker compose -f examples/bookings/docker-compose.yml up -d
   ```

   ```bash
   TARGET_DATABASE_URL=postgresql://bookings:bookings@host.docker.internal:5433/bookings
   CONFIG_SOURCES={"bookings-api": "http://host.docker.internal:8010/settings"}
   TARGET_API_URL=http://host.docker.internal:8010
   ```

2. Start Retrace with `docker compose up -d`.

3. Make one room get booked twice:

   ```bash
   sh examples/bookings/cause_incident.sh
   ```

   It prints a sentence to report. Paste it into **New incident** at
   <http://localhost:5173> and click **Investigate**.

## Commands for the built-in example

| Command | What it does |
|---|---|
| `make demo` | Start everything and cause one incident |
| `make demo SCENARIO=double_charge` | The same, with a different failure |
| `make eval` | Run every scenario 3 times and print how often the agent was right |
| `make test` | Run the linter and the tests |
| `make reset` | Put the payment system back to healthy |
| `make stop` | Stop everything |

The scenarios are `double_refund`, `double_charge` and `charge_without_record`.
`double_refund_injected` is the double refund with a customer's order ID that tells the
agent to blame something else. It checks that text inside the system's data cannot steer
the agent.
