"""HTTP helpers that keep credentials out of terminal and queue errors."""

import re
from typing import Any
from urllib.parse import urlsplit

import httpx

from ..models import ClipsError
from .store import object_data


def check(response: httpx.Response) -> httpx.Response:
    if not response.is_success:
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        code = error_code(payload)
        hint = "Check account permissions and platform limits."
        if response.status_code == 401:
            hint = "Reconnect the account with youtube-clips accounts."
        elif response.status_code == 429:
            hint = "The platform's rate limit was reached. Try again later."
        raise ClipsError(f"API returned HTTP {response.status_code}{code}. {hint}")
    return response


def error_code(payload: object) -> str:
    error = payload.get("error") if isinstance(payload, dict) else None
    code = error.get("status", error.get("code")) if isinstance(error, dict) else error
    if isinstance(error, dict) and isinstance(error.get("errors"), list) and error["errors"]:
        detail = error["errors"][0]
        if isinstance(detail, dict):
            code = detail.get("reason", code)
    return f" ({code})" if code is not None and re.fullmatch(r"[\w.-]{1,80}", str(code)) else ""


def data(response: httpx.Response) -> dict[str, Any]:
    check(response)
    try:
        result = object_data(response.json())
    except ValueError as error:
        raise ClipsError("The platform returned an invalid JSON response.") from error
    api_error = result.get("error")
    if api_error and (not isinstance(api_error, dict) or api_error.get("code") != "ok"):
        raise ClipsError(
            f"The platform rejected the request{error_code(result)}. Check account permissions and upload limits."
        )
    return result


def upload_url(value: object, domain: str) -> str:
    if isinstance(value, str):
        parsed = urlsplit(value)
        host = parsed.hostname or ""
        if (
            parsed.scheme == "https"
            and not parsed.username
            and not parsed.password
            and (host == domain or host.endswith("." + domain))
        ):
            return value
    raise ClipsError("The platform returned an unexpected upload address.")


def required(value: dict[str, Any], key: str) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result:
        raise ClipsError(f"The platform response is missing {key}.")
    return result
