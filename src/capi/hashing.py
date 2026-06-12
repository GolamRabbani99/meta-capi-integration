"""
PII normalisation and hashing for Meta Conversions API.

Meta requires customer information parameters (email, phone, name, etc.)
to be normalised and SHA-256 hashed before transmission. This module is
the single place PII is handled, so it can be audited in isolation.

GDPR notes:
- Raw PII never leaves this module unhashed.
- Hashing is one-way; payloads sent to Meta contain no recoverable PII.
- No PII is ever written to logs (see client.py logging policy).

Normalisation rules follow Meta's documentation:
https://developers.facebook.com/docs/marketing-api/conversions-api/parameters/customer-information-parameters
"""

import hashlib
import re

__all__ = ["hash_email", "hash_phone", "hash_name", "hash_city", "hash_postcode", "sha256"]


def sha256(value: str) -> str:
    """Lowercase, strip, and SHA-256 hash a string."""
    return hashlib.sha256(value.strip().lower().encode("utf-8")).hexdigest()


def hash_email(email: str) -> str:
    """Normalise and hash an email address.

    Meta spec: trim whitespace, lowercase, then SHA-256.
    """
    if not email or "@" not in email:
        raise ValueError("Invalid email address")
    return sha256(email)


def hash_phone(phone: str, default_country_code: str = "44") -> str:
    """Normalise a phone number to E.164-like digits-only form, then hash.

    Meta spec: digits only, including country code, no leading zeros,
    no symbols. UK example: '+44 7700 900123' -> '447700900123'.
    """
    digits = re.sub(r"\D", "", phone or "")
    if not digits:
        raise ValueError("Invalid phone number")
    # Convert UK national format (07700...) to international (447700...)
    if digits.startswith("0"):
        digits = default_country_code + digits.lstrip("0")
    # Handle the common written form "+44 (0)7700..." -> digits "4407700..."
    elif digits.startswith(default_country_code + "0"):
        digits = default_country_code + digits[len(default_country_code) + 1:]
    return sha256(digits)


def hash_name(name: str) -> str:
    """Normalise a first or last name: lowercase, letters only where possible."""
    if not name:
        raise ValueError("Empty name")
    cleaned = re.sub(r"[^a-zA-Z\u00C0-\u024F\u0980-\u09FF ]", "", name)
    return sha256(cleaned)


def hash_city(city: str) -> str:
    """Normalise a city: lowercase, no punctuation, no spaces."""
    if not city:
        raise ValueError("Empty city")
    cleaned = re.sub(r"[^a-zA-Z]", "", city)
    return sha256(cleaned)


def hash_postcode(postcode: str) -> str:
    """Normalise a UK postcode: lowercase, no spaces.

    Meta spec for zip/postcode: lowercase, no spaces; for UK,
    the outward code area is sufficient but full postcode is accepted.
    """
    if not postcode:
        raise ValueError("Empty postcode")
    cleaned = re.sub(r"\s", "", postcode)
    return sha256(cleaned)
