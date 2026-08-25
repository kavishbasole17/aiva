"""Shared request-field validation types.

Pydantic's built-in ``EmailStr`` hardcodes a call to
``email_validator.validate_email(value, check_deliverability=False)`` with no way to
pass additional options. That default rejects addresses under IANA's special-use
domain names (``.test``, ``.example``, ``.invalid``, ``.localhost`` — see RFC 2606),
which is exactly the class of address our own test fixtures and local/demo setups
use. This app never performs deliverability (MX/DNS) checks anyway — that would be
an outbound network call, which the air-gap policy forbids — so the special-use
check buys no real protection here and only breaks legitimate test/demo addresses.
``email_validator``'s own ``test_environment`` flag exists for exactly this case:
it allows special-use domains without weakening any other syntactic validation.
"""

from typing import Annotated

import email_validator
from pydantic import AfterValidator


def _validate_email(value: str) -> str:
    try:
        result = email_validator.validate_email(
            value, check_deliverability=False, test_environment=True
        )
    except email_validator.EmailNotValidError as exc:
        raise ValueError(str(exc)) from exc
    return result.normalized


EmailAddress = Annotated[str, AfterValidator(_validate_email)]
