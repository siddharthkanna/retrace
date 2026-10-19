CREATE TABLE bookings (
    id         BIGSERIAL PRIMARY KEY,
    room       TEXT NOT NULL,
    day        DATE NOT NULL,
    guest      TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
