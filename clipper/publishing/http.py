"""HTTP helpers that keep credentials out of terminal and queue errors."""

from typing import Any
from urllib.parse import urlsplit

import httpx

from ..models import ClipsError
from .store import object_data


def check(response: httpx.Response) -> httpx.Response:
    if not response.is_success:
        raise ClipsError(
            f"API returned HTTP {response.status_code}. Check account access and platform limits."
        )
    return response


def data(response: httpx.Response) -> dict[str, Any]:
    check(response)
    try:
        result = object_data(response.json())
    except ValueError as error:
        raise ClipsError("The platform returned an invalid JSON response.") from error
    api_error = result.get("error")
    if api_error and (not isinstance(api_error, dict) or api_error.get("code") != "ok"):
        raise ClipsError(
            "The platform rejected the request. Check account permissions and upload limits."
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
