"""Hide the user's GCP account in text that may be shared (logs, diagnostics)."""

from __future__ import annotations

from collections.abc import Mapping
import json
from typing import Any

from . import const

REDACTED = "**REDACTED**"


def account_identifiers(data: Mapping[str, Any]) -> list[str]:
    """Return strings in a config entry's data that identify the user's GCP account.

    Google's error text can name the query project (e.g. in a job URL) and the
    service account, whose email names the project the key was made in.
    """
    found = [data[const.CONF_PROJECT_ID]]
    try:
        key = json.loads(data[const.CONF_CREDENTIALS_JSON])
    except ValueError:
        key = None
    if isinstance(key, dict):
        found += [key.get(field) for field in ("client_email", "project_id")]
    # Longest first, so an email is redacted before the project inside it.
    return sorted(
        {value for value in found if isinstance(value, str) and value},
        key=len,
        reverse=True,
    )


def redact_account(text: str, data: Mapping[str, Any]) -> str:
    """Return `text` with the account's identifiers replaced by REDACTED."""
    for identifier in account_identifiers(data):
        text = text.replace(identifier, REDACTED)
    return text
