"""Resumable YouTube uploads with native publication scheduling."""

import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path

import httpx

from ..models import ClipsError, finite_number
from .accounts import access_token
from .http import check, data, required, upload_url
from .store import Account, Job, object_data

type Checkpoint = Callable[[str], None]


def file_chunks(path: Path, offset: int = 0) -> Iterator[bytes]:
    with path.open("rb") as stream:
        stream.seek(offset)
        while chunk := stream.read(1024 * 1024):
            yield chunk


def validate(job: Job) -> None:
    path = Path(job.path)
    if not path.is_file() or not path.stat().st_size:
        raise ClipsError("The clip file is missing or empty.")
    if not 1 <= len(job.title) <= 100 or any(char in job.title + job.text for char in "<>"):
        raise ClipsError("YouTube needs a title of 1–100 characters and no < or > in its text.")
    if len(job.text.encode("utf-8")) > 5000:
        raise ClipsError("YouTube description exceeds 5,000 bytes.")
    if not finite_number(job.when) or job.when < 0:
        raise ClipsError("Invalid YouTube posting time.")


def youtube(client: httpx.Client, job: Job, token: str, checkpoint: Checkpoint) -> str:
    headers = {"Authorization": "Bearer " + token}
    scheduled = job.when > time.time()
    if job.when and job.when <= time.time() + 60:
        raise ClipsError("The YouTube posting time is too close or has passed. Schedule again.")
    status: dict[str, str | bool] = {
        "privacyStatus": "private" if scheduled else "public",
        "selfDeclaredMadeForKids": False,
    }
    if scheduled:
        status["publishAt"] = datetime.fromtimestamp(job.when, UTC).isoformat()
    path = Path(job.path)
    size = path.stat().st_size
    response = check(
        client.post(
            "https://www.googleapis.com/upload/youtube/v3/videos",
            params={"uploadType": "resumable", "part": "snippet,status"},
            headers={
                **headers,
                "X-Upload-Content-Length": str(size),
                "X-Upload-Content-Type": "video/mp4",
            },
            json={
                "snippet": {"title": job.title, "description": job.text, "categoryId": "22"},
                "status": status,
            },
        )
    )
    address = upload_url(response.headers.get("Location"), "googleapis.com")
    checkpoint("YouTube upload session created")
    offset = 0
    response = httpx.Response(308)
    for attempt in range(4):
        try:
            response = client.put(
                address,
                headers={
                    **headers,
                    "Content-Type": "video/mp4",
                    "Content-Length": str(size - offset),
                    "Content-Range": f"bytes {offset}-{size - 1}/{size}",
                },
                content=file_chunks(path, offset),
            )
            if response.is_success:
                break
            if response.status_code not in (308, 500, 502, 503, 504):
                check(response)
        except httpx.TransportError:
            pass
        time.sleep(2**attempt)
        response = client.put(
            address, headers={**headers, "Content-Length": "0", "Content-Range": f"bytes */{size}"}
        )
        if response.is_success:
            break
        if response.status_code != 308:
            check(response)
        acknowledged = response.headers.get("Range", "")
        offset = int(acknowledged.rsplit("-", 1)[-1]) + 1 if acknowledged else 0
        if not 0 <= offset < size:
            raise ClipsError("YouTube upload status is inconclusive; check YouTube Studio.")
    if not response.is_success:
        raise ClipsError(
            "YouTube upload did not finish; check YouTube Studio before uploading again."
        )
    result = data(response)
    identifier = required(result, "id")
    checkpoint("YouTube video " + identifier)
    returned = object_data(result.get("status", {}))
    visibility = str(returned.get("privacyStatus", "unknown"))
    if scheduled:
        if visibility == "public" and time.time() >= job.when:
            return f"https://youtu.be/{identifier} · public; scheduled time reached during upload"
        try:
            accepted_time = datetime.fromisoformat(required(returned, "publishAt"))
            confirmed = (
                accepted_time.tzinfo is not None and abs(accepted_time.timestamp() - job.when) < 1
            )
        except (ClipsError, ValueError, OverflowError):
            confirmed = False
        if not confirmed or visibility != "private":
            raise ClipsError(
                "YouTube did not confirm the requested schedule. Check YouTube Studio."
            )
        message = "schedule accepted"
    else:
        if visibility != "public":
            raise ClipsError(
                f"YouTube returned visibility {visibility!r}, not public. "
                "Check YouTube Studio and your API project's upload restrictions."
            )
        message = f"upload accepted ({visibility}); processing may still be in progress"
    return f"https://youtu.be/{identifier} · {message}"


def publish(job: Job, account: Account, checkpoint: Checkpoint) -> str:
    validate(job)
    with httpx.Client(timeout=httpx.Timeout(120, connect=20), follow_redirects=False) as client:
        token = access_token(account, client)
        return youtube(client, job, token, checkpoint)
