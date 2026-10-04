CREATE DATABASE telemetry;
\connect telemetry

CREATE TABLE spans (
    span_id        TEXT PRIMARY KEY,
    trace_id       TEXT NOT NULL,
    parent_span_id TEXT,
    service        TEXT NOT NULL,
    name           TEXT NOT NULL,
    kind           TEXT NOT NULL,
    start_time     TIMESTAMPTZ NOT NULL,
    end_time       TIMESTAMPTZ NOT NULL,
    status         TEXT NOT NULL,
    attributes     JSONB NOT NULL
);
CREATE INDEX spans_trace_id_idx ON spans (trace_id);

CREATE TABLE logs (
    id         BIGSERIAL PRIMARY KEY,
    ts         TIMESTAMPTZ NOT NULL,
    service    TEXT NOT NULL,
    level      TEXT NOT NULL,
    logger     TEXT NOT NULL,
    message    TEXT NOT NULL,
    trace_id   TEXT,
    span_id    TEXT,
    attributes JSONB NOT NULL
);
CREATE INDEX logs_trace_id_idx ON logs (trace_id);
CREATE INDEX logs_ts_idx ON logs (ts);
