"""Connect a YouTube channel through Google Desktop OAuth."""

import base64
import hashlib
import json
import secrets
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
from rich.prompt import Prompt

from ..models import ClipsError
from ..ui import console
from .http import data, error_code, required
from .store import Account, account, database, object_data

GOOGLE_OAUTH_URL = "https://oauth2.googleapis.com/token"
CALLBACK = "http://127.0.0.1:8765/callback/"


def authorize(url: str, parameters: dict[str, str]) -> dict[str, str]:
    state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    result: dict[str, str] = {}

    class Callback(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urlsplit(self.path)
            query = parse_qs(parsed.query)
            valid = parsed.path == "/callback/" and secrets.compare_digest(
                query.get("state", [""])[0], state
            )
            self.send_response(200 if valid else 400)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            if valid:
                result.update({key: values[0] for key, values in query.items()})
                self.wfile.write(b"You can return to YouTube Clips and close this tab.")
            else:
                self.wfile.write(b"Invalid authorization callback.")

        def log_message(self, format: str, *args: object) -> None:
            pass

    with HTTPServer(("127.0.0.1", 8765), Callback) as server:
        server.timeout = 1
        parameters = {
            **parameters,
            "state": state,
            "response_type": "code",
            "redirect_uri": CALLBACK,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        address = url + "?" + urlencode(parameters)
        console.print("Open this link to connect your account:")
        console.print(address, markup=False)
        webbrowser.open(address)
        deadline = time.monotonic() + 300
        while not result and time.monotonic() < deadline:
            server.handle_request()
    if result.get("error"):
        hint = "Check the app's OAuth settings and test users in Google Cloud Console."
        if result["error"] == "access_denied":
            hint = "Access was denied. Connect again and approve the requested permissions."
        raise ClipsError(f"Account authorization failed{error_code(result)}. {hint}")
    if not result.get("code"):
        raise ClipsError("Account connection was cancelled or timed out.")
    return {
        "code": result["code"],
        "redirect_uri": CALLBACK,
        "code_verifier": verifier,
        "grant_type": "authorization_code",
    }


def save_token(account: Account, token: dict[str, object]) -> None:
    account.secrets["access_token"] = required(object_data(token), "access_token")
    refresh = token.get("refresh_token")
    if isinstance(refresh, str) and refresh:
        account.secrets["refresh_token"] = refresh
    expires = token.get("expires_in", 3600)
    if not isinstance(expires, (int, float)):
        raise ClipsError("Invalid token expiration returned by the platform.")
    account.secrets["expires_at"] = str(time.time() + expires - 120)


def access_token(account: Account, client: httpx.Client) -> str:
    if float(account.secrets.get("expires_at", "0")) <= time.time():
        token = data(
            client.post(
                GOOGLE_OAUTH_URL,
                data={
                    "client_id": account.secrets["client_id"],
                    "client_secret": account.secrets["client_secret"],
                    "refresh_token": account.secrets.get("refresh_token", ""),
                    "grant_type": "refresh_token",
                },
            )
        )
        save_token(account, token)
        account.save(refresh=True)
    return account.secrets["access_token"]


def connect_youtube(client: httpx.Client) -> Account:
    console.print("Use a Google Desktop OAuth client JSON with YouTube Data API v3 enabled.")
    path = Path(Prompt.ask("Client JSON path", console=console)).expanduser()
    try:
        settings = object_data(object_data(json.loads(path.read_text()))["installed"])
        credentials = {key: required(settings, key) for key in ("client_id", "client_secret")}
    except (ValueError, KeyError) as error:
        raise ClipsError("Choose the downloaded Desktop OAuth client JSON.") from error
    code = authorize(
        "https://accounts.google.com/o/oauth2/v2/auth",
        {
            "client_id": credentials["client_id"],
            "access_type": "offline",
            "prompt": "consent",
            "scope": "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly",
        },
    )
    token = data(client.post(GOOGLE_OAUTH_URL, data={**credentials, **code}))
    account = Account("", "", credentials)
    save_token(account, token)
    info = data(
        client.get(
            "https://www.googleapis.com/youtube/v3/channels",
            params={
                "part": "snippet",
                "mine": "true",
            },
            headers={"Authorization": "Bearer " + account.secrets["access_token"]},
        )
    )
    items = info.get("items")
    if not isinstance(items, list) or not items:
        raise ClipsError("This Google account has no accessible YouTube channel.")
    channel = object_data(items[0])
    account.id = required(channel, "id")
    account.label = required(object_data(channel.get("snippet")), "title")
    return account


def manage_accounts() -> None:
    connected = account()
    console.print(f"YouTube · {connected.label if connected else 'not connected'}", markup=False)
    action = Prompt.ask(
        "Account",
        choices=["connect", "disconnect", "back"] if connected else ["connect", "back"],
        default="back",
        console=console,
    )
    if action == "back":
        return
    if action == "disconnect":
        with database() as db:
            db.execute("DELETE FROM accounts WHERE platform='youtube'")
            db.execute("UPDATE jobs SET state='cancelled' WHERE state='queued'")
        console.print(
            "Account removed; pending uploads cancelled. Uploaded videos stay on YouTube."
        )
        return
    with httpx.Client(timeout=30) as client:
        connected = connect_youtube(client)
    connected.save()
    console.print(f"Connected YouTube · {connected.label}", markup=False)


def require_account() -> Account:
    connected = account()
    if connected is None:
        console.print(
            "Connect YouTube first. Setup instructions: docs/publishing.md", style="muted"
        )
        manage_accounts()
        connected = account()
    if connected is None:
        raise ClipsError("No YouTube account connected.")
    console.print(f"YouTube · {connected.label}", markup=False, style="accent")
    return connected
