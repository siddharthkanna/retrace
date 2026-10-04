-- No UNIQUE constraint on order_id on purpose: the double-charge scenario
-- needs the database to accept two payments for the same order.
CREATE TABLE payments (
    id                 BIGSERIAL PRIMARY KEY,
    order_id           TEXT NOT NULL,
    amount_cents       INTEGER NOT NULL CHECK (amount_cents > 0),
    provider_charge_id TEXT,
    status             TEXT NOT NULL,
    idempotency_key    TEXT NOT NULL UNIQUE,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE refunds (
    id                 BIGSERIAL PRIMARY KEY,
    payment_id         BIGINT NOT NULL REFERENCES payments (id),
    amount_cents       INTEGER NOT NULL CHECK (amount_cents > 0),
    provider_refund_id TEXT,
    status             TEXT NOT NULL,
    idempotency_key    TEXT NOT NULL UNIQUE,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
