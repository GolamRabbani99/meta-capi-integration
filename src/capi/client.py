"""
Meta Conversions API client.

Production concerns handled here:
- Secure credential handling: access token comes from environment only,
  never hardcoded, never logged.
- Rate-limit handling: respects HTTP 429 / Meta error code 80004 with
  exponential backoff + jitter.
- Retry policy: idempotent by design - event_ids are deterministic, so
  a retried batch cannot double-count conversions on Meta's side.
- PII-safe logging: log lines contain event names, event_ids and counts.
  Never user_data. This makes logs safe to ship to any log aggregator.
- Auditability: every accepted batch returns Meta's fbtrace_id, which is
  logged for end-to-end traceability.
"""

import os
import json
import time
import random
import logging
from typing import List, Optional

import requests

from .events import ServerEvent

logger = logging.getLogger("capi")

GRAPH_API_VERSION = "v21.0"
MAX_RETRIES = 4
BATCH_LIMIT = 1000  # Meta's max events per request


class CapiError(Exception):
    """Raised when Meta rejects a batch after all retries."""


class CapiClient:
    def __init__(
        self,
        pixel_id: Optional[str] = None,
        access_token: Optional[str] = None,
        test_event_code: Optional[str] = None,
        session: Optional[requests.Session] = None,
    ):
        self.pixel_id = pixel_id or os.environ.get("META_PIXEL_ID")
        self._access_token = access_token or os.environ.get("META_ACCESS_TOKEN")
        self.test_event_code = test_event_code or os.environ.get("META_TEST_EVENT_CODE")
        if not self.pixel_id or not self._access_token:
            raise ValueError(
                "META_PIXEL_ID and META_ACCESS_TOKEN must be set "
                "(environment variables or constructor arguments)."
            )
        self.session = session or requests.Session()
        self.endpoint = (
            f"https://graph.facebook.com/{GRAPH_API_VERSION}/{self.pixel_id}/events"
        )

    # ------------------------------------------------------------------ #

    def send(self, events: List[ServerEvent]) -> dict:
        """Send a batch of events with retry + backoff.

        Returns Meta's response dict on success, e.g.
        {"events_received": 2, "fbtrace_id": "..."}.
        Raises CapiError after exhausting retries.
        """
        if not events:
            return {"events_received": 0}
        if len(events) > BATCH_LIMIT:
            raise ValueError(f"Batch exceeds Meta limit of {BATCH_LIMIT} events")

        body = {"data": [e.to_payload() for e in events]}
        if self.test_event_code:
            body["test_event_code"] = self.test_event_code

        params = {"access_token": self._access_token}

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = self.session.post(
                    self.endpoint, params=params, json=body, timeout=15
                )
            except requests.RequestException as exc:
                logger.warning(
                    "CAPI network error (attempt %d/%d): %s",
                    attempt, MAX_RETRIES, exc.__class__.__name__,
                )
                self._backoff(attempt)
                continue

            if resp.status_code == 200:
                data = resp.json()
                logger.info(
                    "CAPI batch accepted: %d events, fbtrace_id=%s, event_ids=%s",
                    data.get("events_received", len(events)),
                    data.get("fbtrace_id"),
                    [e.event_id[:8] for e in events],  # truncated, no PII
                )
                return data

            if self._is_rate_limited(resp):
                logger.warning(
                    "CAPI rate limited (attempt %d/%d), backing off", attempt, MAX_RETRIES
                )
                self._backoff(attempt)
                continue

            # Non-retryable client error: log Meta's error envelope
            # (contains no PII - it's Meta's validation message).
            try:
                err = resp.json().get("error", {})
            except json.JSONDecodeError:
                err = {"message": resp.text[:200]}
            logger.error(
                "CAPI rejected batch: status=%s code=%s message=%s",
                resp.status_code, err.get("code"), err.get("message"),
            )
            raise CapiError(f"Meta rejected batch: {err.get('message')}")

        raise CapiError(f"CAPI batch failed after {MAX_RETRIES} attempts")

    # ------------------------------------------------------------------ #

    @staticmethod
    def _is_rate_limited(resp: requests.Response) -> bool:
        if resp.status_code == 429:
            return True
        if resp.status_code == 400:
            try:
                code = resp.json().get("error", {}).get("code")
                return code in (4, 17, 80004)  # Meta throttling codes
            except json.JSONDecodeError:
                return False
        return False

    @staticmethod
    def _backoff(attempt: int) -> None:
        """Exponential backoff with jitter: ~1s, 2s, 4s, 8s."""
        delay = (2 ** (attempt - 1)) + random.uniform(0, 0.5)
        time.sleep(delay)
