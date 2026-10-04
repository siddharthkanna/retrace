"""HTTP calls to the payment provider."""

import logging

import httpx

from services.payment_api.controls import FeatureFlags

logger = logging.getLogger(__name__)


class ProviderError(Exception):
    """The provider could not be reached or returned an error."""


class ProviderClient:
    def __init__(
        self, base_url: str, timeout_s: float, max_retries: int, flags: FeatureFlags
    ) -> None:
        self._http = httpx.Client(base_url=base_url, timeout=timeout_s)
        self._max_retries = max_retries
        self._flags = flags

    def create_charge(self, order_id: str, amount_cents: int, idempotency_key: str) -> str:
        """Charge the customer and return the provider's charge ID."""
        resp = self._request(
            "POST",
            "/charges",
            json={"order_id": order_id, "amount_cents": amount_cents},
            idempotency_key=idempotency_key,
        )
        return resp.json()["charge_id"]

    def create_refund(self, charge_id: str, amount_cents: int, idempotency_key: str) -> str:
        """Refund part or all of a charge and return the provider's refund ID."""
        resp = self._request(
            "POST",
            "/refunds",
            json={"charge_id": charge_id, "amount_cents": amount_cents},
            idempotency_key=idempotency_key,
        )
        return resp.json()["refund_id"]

    def ping(self) -> None:
        self._request("GET", "/health")

    def close(self) -> None:
        self._http.close()

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict | None = None,
        idempotency_key: str | None = None,
    ) -> httpx.Response:
        forward_key = idempotency_key and self._flags.forward_idempotency_key
        headers = {"Idempotency-Key": idempotency_key} if forward_key else None
        attempt = 0
        while True:
            attempt += 1
            try:
                resp = self._http.request(method, path, json=json, headers=headers)
                resp.raise_for_status()
                return resp
            except httpx.HTTPError as exc:
                # Only timeouts are retried: the request may or may not have been
                # processed, and the idempotency key makes repeating it safe.
                retryable = isinstance(exc, httpx.TimeoutException) and attempt <= self._max_retries
                logger.warning(
                    "provider request timed out, retrying"
                    if retryable
                    else "provider request failed",
                    extra={
                        "method": method,
                        "path": path,
                        "attempt": attempt,
                        "error": f"{type(exc).__name__}: {exc}",
                    },
                )
                if not retryable:
                    raise ProviderError(str(exc)) from exc
