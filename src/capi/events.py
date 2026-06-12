"""
Event construction for Meta Conversions API.

Key design decisions:

1. Deduplication: every event carries an `event_id`. The same event_id is
   used by the browser Pixel and this server-side sender, so Meta can
   deduplicate when both fire for the same action. We generate
   deterministic IDs from (event_name, order/lead reference) so retries
   never create duplicate conversions.

2. Data minimisation (GDPR Art. 5(1)(c)): only the fields needed for
   match quality are included. Everything optional defaults to None and
   is omitted from the payload entirely.
"""

import time
import uuid
import hashlib
from dataclasses import dataclass, field
from typing import Optional

from .hashing import hash_email, hash_phone, hash_name, hash_city, hash_postcode


def deterministic_event_id(event_name: str, reference: str) -> str:
    """Build a stable event_id from the event name and a business reference
    (order ID, lead ID, enquiry ID).

    Deterministic IDs mean:
    - Pixel and server events for the same action share an ID -> Meta dedupes.
    - A retried HTTP request cannot double-count a conversion.
    """
    raw = f"{event_name}:{reference}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:32]


@dataclass
class UserData:
    """Customer information. All PII is hashed at construction time -
    raw values are never stored on the instance."""

    em: Optional[str] = None  # hashed email
    ph: Optional[str] = None  # hashed phone
    fn: Optional[str] = None  # hashed first name
    ln: Optional[str] = None  # hashed last name
    ct: Optional[str] = None  # hashed city
    zp: Optional[str] = None  # hashed postcode
    client_ip_address: Optional[str] = None  # NOT hashed per Meta spec
    client_user_agent: Optional[str] = None  # NOT hashed per Meta spec
    fbp: Optional[str] = None  # _fbp browser cookie
    fbc: Optional[str] = None  # _fbc click ID cookie

    @classmethod
    def from_raw(
        cls,
        email: Optional[str] = None,
        phone: Optional[str] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        city: Optional[str] = None,
        postcode: Optional[str] = None,
        client_ip_address: Optional[str] = None,
        client_user_agent: Optional[str] = None,
        fbp: Optional[str] = None,
        fbc: Optional[str] = None,
    ) -> "UserData":
        """Hash raw PII immediately. After this call, no plaintext PII exists
        in the object graph."""
        return cls(
            em=hash_email(email) if email else None,
            ph=hash_phone(phone) if phone else None,
            fn=hash_name(first_name) if first_name else None,
            ln=hash_name(last_name) if last_name else None,
            ct=hash_city(city) if city else None,
            zp=hash_postcode(postcode) if postcode else None,
            client_ip_address=client_ip_address,
            client_user_agent=client_user_agent,
            fbp=fbp,
            fbc=fbc,
        )

    def to_payload(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v is not None}


@dataclass
class ServerEvent:
    """A single Conversions API event."""

    event_name: str  # e.g. "Lead", "Purchase", "CompleteRegistration"
    user_data: UserData
    event_id: str
    event_time: int = field(default_factory=lambda: int(time.time()))
    event_source_url: Optional[str] = None
    action_source: str = "website"
    custom_data: Optional[dict] = None  # value, currency, content_ids...

    @classmethod
    def create(
        cls,
        event_name: str,
        user_data: UserData,
        reference: Optional[str] = None,
        **kwargs,
    ) -> "ServerEvent":
        """Create an event. If a business reference is supplied the event_id
        is deterministic (retry-safe + Pixel-dedupe-ready); otherwise a
        random UUID is used."""
        event_id = (
            deterministic_event_id(event_name, reference)
            if reference
            else uuid.uuid4().hex
        )
        return cls(event_name=event_name, user_data=user_data, event_id=event_id, **kwargs)

    def to_payload(self) -> dict:
        payload = {
            "event_name": self.event_name,
            "event_time": self.event_time,
            "event_id": self.event_id,
            "action_source": self.action_source,
            "user_data": self.user_data.to_payload(),
        }
        if self.event_source_url:
            payload["event_source_url"] = self.event_source_url
        if self.custom_data:
            payload["custom_data"] = self.custom_data
        return payload
