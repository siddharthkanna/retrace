"""SQL for the payments and refunds tables."""

import psycopg
from psycopg.rows import class_row
from psycopg_pool import ConnectionPool

from services.payment_api.controls import FeatureFlags
from services.payment_api.errors import PaymentNotFoundError, RefundExceedsPaymentError
from services.payment_api.models import Payment, Refund

_PAYMENT_COLUMNS = "id, order_id, amount_cents, provider_charge_id, status"
_REFUND_COLUMNS = "id, payment_id, amount_cents, provider_refund_id, status"


class PaymentRepository:
    def __init__(self, pool: ConnectionPool, flags: FeatureFlags) -> None:
        self._pool = pool
        self._flags = flags

    def get_payment(self, payment_id: int) -> Payment | None:
        with self._pool.connection() as conn, conn.cursor(row_factory=class_row(Payment)) as cur:
            return cur.execute(
                f"SELECT {_PAYMENT_COLUMNS} FROM payments WHERE id = %s", (payment_id,)
            ).fetchone()

    def find_payment_by_idempotency_key(self, idempotency_key: str) -> Payment | None:
        with self._pool.connection() as conn, conn.cursor(row_factory=class_row(Payment)) as cur:
            return cur.execute(
                f"SELECT {_PAYMENT_COLUMNS} FROM payments WHERE idempotency_key = %s",
                (idempotency_key,),
            ).fetchone()

    def insert_payment(
        self,
        order_id: str,
        amount_cents: int,
        provider_charge_id: str,
        status: str,
        idempotency_key: str,
    ) -> Payment:
        """Insert a payment, or return the existing one if the key was already used."""
        with self._pool.connection() as conn, conn.cursor(row_factory=class_row(Payment)) as cur:
            payment = cur.execute(
                "INSERT INTO payments"
                " (order_id, amount_cents, provider_charge_id, status, idempotency_key)"
                " VALUES (%s, %s, %s, %s, %s)"
                " ON CONFLICT (idempotency_key) DO NOTHING"
                f" RETURNING {_PAYMENT_COLUMNS}",
                (order_id, amount_cents, provider_charge_id, status, idempotency_key),
            ).fetchone()
            if payment is None:
                # A concurrent request with the same key inserted first.
                payment = cur.execute(
                    f"SELECT {_PAYMENT_COLUMNS} FROM payments WHERE idempotency_key = %s",
                    (idempotency_key,),
                ).fetchone()
        return payment

    def reserve_refund(self, payment_id: int, amount_cents: int, idempotency_key: str) -> Refund:
        """Reserve a refund as 'pending', or return the existing one for this key.

        Runs in one transaction. The payment row is locked (FOR UPDATE) so two
        concurrent refunds for the same payment cannot both pass the check.
        """
        with self._pool.connection() as conn, conn.cursor(row_factory=class_row(Refund)) as cur:
            paid_cents = self._paid_cents(conn, payment_id)
            existing = self._find_refund(cur, idempotency_key)
            if existing is not None:
                return existing
            if self._refunded_cents(conn, payment_id) + amount_cents > paid_cents:
                raise RefundExceedsPaymentError(payment_id)
            return self._insert_refund(cur, payment_id, amount_cents, idempotency_key)

    def _paid_cents(self, conn: psycopg.Connection, payment_id: int) -> int:
        """The amount paid. Locks the payment row unless row locking is switched off."""
        lock = " FOR UPDATE" if self._flags.refund_row_locking else ""
        payment = conn.execute(
            f"SELECT amount_cents FROM payments WHERE id = %s{lock}", (payment_id,)
        ).fetchone()
        if payment is None:
            raise PaymentNotFoundError(payment_id)
        return payment[0]

    def _find_refund(self, cur: psycopg.Cursor[Refund], idempotency_key: str) -> Refund | None:
        return cur.execute(
            f"SELECT {_REFUND_COLUMNS} FROM refunds WHERE idempotency_key = %s",
            (idempotency_key,),
        ).fetchone()

    def _refunded_cents(self, conn: psycopg.Connection, payment_id: int) -> int:
        return conn.execute(
            "SELECT COALESCE(SUM(amount_cents), 0) FROM refunds WHERE payment_id = %s",
            (payment_id,),
        ).fetchone()[0]

    def _insert_refund(
        self, cur: psycopg.Cursor[Refund], payment_id: int, amount_cents: int, idempotency_key: str
    ) -> Refund:
        return cur.execute(
            "INSERT INTO refunds (payment_id, amount_cents, status, idempotency_key)"
            f" VALUES (%s, %s, 'pending', %s) RETURNING {_REFUND_COLUMNS}",
            (payment_id, amount_cents, idempotency_key),
        ).fetchone()

    def complete_refund(self, refund_id: int, provider_refund_id: str) -> Refund:
        with self._pool.connection() as conn, conn.cursor(row_factory=class_row(Refund)) as cur:
            return cur.execute(
                "UPDATE refunds SET status = 'succeeded', provider_refund_id = %s"
                f" WHERE id = %s RETURNING {_REFUND_COLUMNS}",
                (provider_refund_id, refund_id),
            ).fetchone()

    def ping(self) -> None:
        with self._pool.connection() as conn:
            conn.execute("SELECT 1")
