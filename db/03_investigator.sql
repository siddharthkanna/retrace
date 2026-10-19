CREATE DATABASE investigator;
\connect investigator

CREATE TABLE incidents (
    id          BIGSERIAL PRIMARY KEY,
    description TEXT NOT NULL,
    severity    TEXT NOT NULL DEFAULT 'medium'
                CHECK (severity IN ('low', 'medium', 'high', 'critical')),
    status      TEXT NOT NULL DEFAULT 'open'
                CHECK (status IN ('open', 'investigating', 'resolved', 'failed')),
    source      TEXT NOT NULL DEFAULT 'reported'
                CHECK (source IN ('reported', 'watcher')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE investigations (
    id             BIGSERIAL PRIMARY KEY,
    incident_id    BIGINT NOT NULL REFERENCES incidents (id),
    model          TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'running'
                   CHECK (status IN ('running', 'resolved', 'failed')),
    failure_reason TEXT,
    report         JSONB,
    evidence       JSONB NOT NULL DEFAULT '[]',
    messages       JSONB NOT NULL DEFAULT '[]',
    reproduction   JSONB,
    usage          JSONB,
    started_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at    TIMESTAMPTZ
);

-- At most one investigation may be running for an incident at any moment.
CREATE UNIQUE INDEX investigations_one_running_per_incident
    ON investigations (incident_id) WHERE status = 'running';
