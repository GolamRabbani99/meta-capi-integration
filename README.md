# Meta Conversions API — Production Server-Side Tracking (Python)

A production-grade implementation of Meta's Conversions API (CAPI) for
server-side event tracking, built around three concerns most example code
ignores: **event deduplication**, **GDPR-aware payload design**, and
**operational resilience** (retries, rate limits, PII-safe logging).

> Context: I built and ran a CAPI integration in production as Digital
> Marketing Manager at an education company in London, recovering ~20% of
> attribution data lost to iOS 14+ privacy restrictions. This repo is a
> cleaned-up, generalised version of that pattern.

---

## Why server-side tracking

Browser-only Pixel tracking loses events to ad blockers, Safari ITP and
iOS App Tracking Transparency. Sending the same conversions from your
server restores attribution — but introduces two problems this repo solves:

1. **Double counting** — if both Pixel and server fire for one purchase,
   you report 2 conversions. Solved with shared, deterministic `event_id`s.
2. **PII exposure** — customer data now flows through your backend.
   Solved with hash-at-the-boundary design and data minimisation.

## Architecture

```
 Browser ──── Pixel event ───────────────┐
                (event_id: abc123)       ▼
                                   ┌──────────┐
 Your server ─ CAPI event ───────▶ │   Meta   │ ── deduplicates on
   (this lib)  (event_id: abc123)  └──────────┘    matching event_id
```

```
 Raw PII ──▶ UserData.from_raw() ──▶ SHA-256 hashes only ──▶ payload ──▶ Meta
             (the ONLY place                │
              plaintext exists)             └──▶ logs contain event_ids
                                                 and counts — never PII
```

## Key design decisions

### Deduplication (`events.py`)
`event_id` is derived deterministically from the event name + a business
reference (order ID, enquiry ID):

```python
event = ServerEvent.create("Lead", user, reference="enquiry-2026-04-1187")
```

- The browser Pixel sends the same ID → Meta deduplicates Pixel vs server.
- A retried HTTP request produces the same ID → retries are idempotent
  and can never double-count a conversion.

### GDPR-aware payload design (`hashing.py`, `events.py`)
- **Hash at the boundary**: raw PII is SHA-256 hashed inside
  `UserData.from_raw()` and plaintext is never stored on any object.
- **Normalisation per Meta spec** (so match quality doesn't suffer):
  emails lowercased/trimmed; UK phone numbers converted to international
  digits-only form (`07700 900123` → `447700900123`); postcodes
  de-spaced and lowercased.
- **Data minimisation** (GDPR Art. 5(1)(c)): unset fields are omitted
  from the payload entirely, not sent as empty strings.
- **PII-safe logging**: logs carry truncated event_ids, counts and Meta's
  `fbtrace_id` for auditability — never customer data. Logs are safe to
  ship to any aggregator.

### Operational resilience (`client.py`)
- Exponential backoff with jitter on HTTP 429 and Meta throttle codes
  (4, 17, 80004).
- Credentials from environment variables only; the access token is never
  logged or serialised.
- Batch limit enforcement (Meta caps at 1,000 events/request).
- Full Meta error envelope surfaced on non-retryable failures.

## Quick start

```bash
pip install -r requirements.txt python-dotenv pytest
cp .env.example .env        # add your Pixel ID + access token
pytest tests/ -v            # run the unit tests
python examples/send_lead_event.py
```

Use Meta Events Manager → **Test Events** and set `META_TEST_EVENT_CODE`
in `.env` to verify events arrive and deduplicate before going live.

## Project layout

```
src/capi/
  hashing.py    # PII normalisation + SHA-256 (single auditable boundary)
  events.py     # UserData / ServerEvent models, deterministic event_ids
  client.py     # HTTP client: retries, rate limits, PII-safe logging
examples/
  send_lead_event.py
tests/
  test_capi.py  # hashing normalisation, dedup, GDPR payload checks
```

## What I'd add for a larger deployment

- A queue (e.g. Redis/SQS) between the app and the sender, so conversion
  capture survives Meta outages.
- Event Match Quality monitoring via the Graph API.
- A consent gate: only send events for users with marketing consent
  (GDPR Art. 6) — in my production deployment this was enforced upstream
  at form level.
