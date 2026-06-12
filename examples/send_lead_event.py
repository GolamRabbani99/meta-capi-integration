"""
Example: send a server-side Lead event when a student enquiry form is
submitted, mirrored with the browser Pixel for deduplication.

Run:
    cp .env.example .env   # fill in credentials
    pip install -r requirements.txt python-dotenv
    python examples/send_lead_event.py
"""

import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from dotenv import load_dotenv
from capi import CapiClient, ServerEvent, UserData

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

load_dotenv()


def main():
    client = CapiClient()  # credentials read from environment

    # Raw PII is hashed at this boundary and never stored in plaintext.
    user = UserData.from_raw(
        email="prospect@example.com",
        phone="07700 900123",          # UK national format - normalised to 447700900123
        first_name="Aisha",
        last_name="Rahman",
        city="London",
        postcode="E1 6AN",
        client_ip_address="203.0.113.7",
        client_user_agent="Mozilla/5.0 (example)",
        fbp="fb.1.1700000000000.1234567890",  # from _fbp cookie
    )

    # The enquiry ID makes the event_id deterministic:
    # - the browser Pixel fires the same event_id -> Meta deduplicates
    # - an HTTP retry of this script cannot double-count the lead
    event = ServerEvent.create(
        event_name="Lead",
        user_data=user,
        reference="enquiry-2026-04-1187",
        event_source_url="https://example.com/enquiry/thank-you",
        custom_data={"currency": "GBP", "value": 2000.00},  # commission value
    )

    result = client.send([event])
    print(f"Meta accepted {result.get('events_received')} event(s), "
          f"trace: {result.get('fbtrace_id')}")


if __name__ == "__main__":
    main()
