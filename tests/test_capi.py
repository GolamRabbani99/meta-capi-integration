"""Unit tests: PII hashing normalisation and event deduplication.

Run: pytest tests/ -v
"""

import hashlib
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
from capi.hashing import hash_email, hash_phone, hash_postcode
from capi.events import UserData, ServerEvent, deterministic_event_id


def sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


class TestHashing:
    def test_email_is_normalised_before_hashing(self):
        # Different surface forms of the same address must hash identically
        assert hash_email("  Prospect@Example.COM ") == sha("prospect@example.com")

    def test_invalid_email_rejected(self):
        with pytest.raises(ValueError):
            hash_email("not-an-email")

    def test_uk_phone_national_to_international(self):
        # 07700 900123 must normalise to 447700900123 per Meta spec
        assert hash_phone("07700 900123") == sha("447700900123")

    def test_phone_symbols_stripped(self):
        assert hash_phone("+44 (0)7700-900123") == sha("447700900123")

    def test_postcode_spaces_removed(self):
        assert hash_postcode("E1 6AN") == sha("e16an")


class TestDeduplication:
    def test_event_id_is_deterministic(self):
        # Same business reference -> same event_id, so a retried request
        # or a mirrored Pixel event is deduplicated by Meta.
        a = deterministic_event_id("Lead", "enquiry-1187")
        b = deterministic_event_id("Lead", "enquiry-1187")
        assert a == b

    def test_different_references_differ(self):
        assert deterministic_event_id("Lead", "enquiry-1") != \
               deterministic_event_id("Lead", "enquiry-2")

    def test_event_create_uses_reference(self):
        user = UserData.from_raw(email="a@b.com")
        e1 = ServerEvent.create("Purchase", user, reference="order-9")
        e2 = ServerEvent.create("Purchase", user, reference="order-9")
        assert e1.event_id == e2.event_id


class TestGdprPayload:
    def test_no_plaintext_pii_in_payload(self):
        user = UserData.from_raw(
            email="prospect@example.com", phone="07700 900123",
            first_name="Aisha", city="London", postcode="E1 6AN",
        )
        payload = user.to_payload()
        flat = str(payload).lower()
        for raw in ("prospect@example.com", "07700", "aisha", "e1 6an"):
            assert raw not in flat, f"Plaintext PII leaked: {raw}"

    def test_data_minimisation_omits_missing_fields(self):
        user = UserData.from_raw(email="a@b.com")
        payload = user.to_payload()
        assert set(payload.keys()) == {"em"}
