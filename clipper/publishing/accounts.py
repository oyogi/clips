"""Connect owned accounts through OAuth or a Meta access token."""

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
from .http import data, required
from .store import LABELS, PLATFORMS, Account, accounts, database, object_data

GRAPH = "https://graph.facebook.com/v25.0"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
TIKTOK_TOKEN = "https://open.tiktokapis.com/v2/oauth/token/"


def authorize(url: str, parameters: dict[str, str], *, tiktok: bool = False) -> dict[str, str]:
    state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = digest.hex() if tiktok else base64.urlsafe_b64encode(digest).decode().rstrip("=")
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
        redirect = "http://127.0.0.1:8765/callback/"
        parameters = {
            **parameters,
            "state": state,
            "response_type": "code",
            "redirect_uri": redirect,
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
    if "code" not in result:
        raise ClipsError("Account connection was cancelled or timed out.")
    return {
        "code": result["code"],
        "redirect_uri": redirect,
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
    if account.platform == "instagram":
        return account.secrets["access_token"]
    if float(account.secrets.get("expires_at", "0")) <= time.time():
        key = "client_key" if account.platform == "tiktok" else "client_id"
        token = data(
            client.post(
                TIKTOK_TOKEN if key == "client_key" else GOOGLE_TOKEN,
                data={
                    key: account.secrets[key],
                    "client_secret": account.secrets["client_secret"],
                    "refresh_token": account.secrets.get("refresh_token", ""),
                    "grant_type": "refresh_token",
                },
            )
        )
        save_token(account, token)
        account.save()
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
    token = data(client.post(GOOGLE_TOKEN, data={**credentials, **code}))
    account = Account("youtube", "", "", credentials)
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
    account.label = required(object_data(channel["snippet"]), "title")
    return account


def connect_instagram(client: httpx.Client) -> Account:
    console.print(
        "Use a Facebook-linked Instagram professional account and a long-lived Meta token."
    )
    identifier = Prompt.ask("Instagram account ID", console=console).strip()
    if not identifier.isdecimal():
        raise ClipsError("Instagram account IDs contain digits only.")
    token = Prompt.ask("Meta access token", password=True, console=console).strip()
    info = data(
        client.get(
            f"{GRAPH}/{identifier}",
            params={"fields": "id,username"},
            headers={"Authorization": "Bearer " + token},
        )
    )
    return Account(
        "instagram", required(info, "id"), "@" + required(info, "username"), {"access_token": token}
    )


def connect_tiktok(client: httpx.Client) -> Account:
    console.print("TikTok uploads go to your inbox. Finish editing and posting in TikTok.")
    console.print("Register http://127.0.0.1:8765/callback/ in your app's Desktop Login Kit.")
    credentials = {
        "client_key": Prompt.ask("TikTok client key", console=console).strip(),
        "client_secret": Prompt.ask("TikTok client secret", password=True, console=console).strip(),
    }
    code = authorize(
        "https://www.tiktok.com/v2/auth/authorize/",
        {
            "client_key": credentials["client_key"],
            "scope": "user.info.basic,video.upload",
        },
        tiktok=True,
    )
    token = data(client.post(TIKTOK_TOKEN, data={**credentials, **code}))
    if "video.upload" not in str(token.get("scope", "")).split(","):
        raise ClipsError("TikTok video.upload permission was not granted.")
    account = Account("tiktok", required(token, "open_id"), "", credentials)
    save_token(account, token)
    info = data(
        client.get(
            "https://open.tiktokapis.com/v2/user/info/",
            params={"fields": "open_id,display_name"},
            headers={"Authorization": "Bearer " + account.secrets["access_token"]},
        )
    )
    account.label = required(object_data(object_data(info["data"])["user"]), "display_name")
    return account


def manage_accounts() -> None:
    connected = accounts()
    for number, platform in enumerate(PLATFORMS, 1):
        label = connected[platform].label if platform in connected else "not connected"
        console.print(f"{number}  {LABELS[platform]} · {label}", markup=False)
    choice = Prompt.ask("Connect / replace account (Enter to return)", default="", console=console)
    if not choice:
        return
    if choice not in ("1", "2", "3"):
        raise ClipsError("Choose 1, 2 or 3.")
    platform = PLATFORMS[int(choice) - 1]
    if (
        platform in connected
        and Prompt.ask(
            "Action", choices=["connect", "disconnect"], default="connect", console=console
        )
        == "disconnect"
    ):
        with database() as db:
            db.execute("DELETE FROM accounts WHERE platform=?", (platform,))
        console.print(
            "Account removed. Pending uploads to it will fail; remote posts are unchanged."
        )
        return
    with httpx.Client(timeout=30) as client:
        connector = {
            "youtube": connect_youtube,
            "instagram": connect_instagram,
            "tiktok": connect_tiktok,
        }
        account = connector[platform](client)
    account.save()
    console.print(f"Connected {LABELS[platform]} · {account.label}", markup=False)
