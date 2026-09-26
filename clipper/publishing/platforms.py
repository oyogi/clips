"""Official YouTube, Instagram Reels and TikTok inbox upload protocols."""

import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path

import httpx

from ..models import ClipsError
from .accounts import GRAPH, access_token
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
    if job.platform == "youtube":
        if not 1 <= len(job.title) <= 100 or any(char in job.title + job.text for char in "<>"):
            raise ClipsError("YouTube needs a title of 1–100 characters and no < or > in its text.")
        if len(job.text.encode("utf-8")) > 5000:
            raise ClipsError("YouTube description exceeds 5,000 bytes.")
        if job.privacy not in ("private", "unlisted", "public"):
            raise ClipsError("Invalid YouTube visibility.")
    elif job.platform == "instagram":
        if len(job.text) > 2200 or job.text.count("#") > 30:
            raise ClipsError("Instagram allows 2,200 caption characters and 30 hashtags.")
        if path.stat().st_size > 1_000_000_000:
            raise ClipsError("Instagram clips must be at most 1 GB.")


def youtube(client: httpx.Client, job: Job, token: str, checkpoint: Checkpoint) -> str:
    headers = {"Authorization": "Bearer " + token}
    scheduled = job.when > time.time()
    if job.when and job.when <= time.time() + 60:
        raise ClipsError("The YouTube posting time is too close or has passed. Schedule again.")
    status: dict[str, str | bool] = {
        "privacyStatus": "private" if scheduled else job.privacy,
        "selfDeclaredMadeForKids": job.made_for_kids,
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
    if response is None or not response.is_success:
        raise ClipsError(
            "YouTube upload did not finish; check YouTube Studio before uploading again."
        )
    result = data(response)
    identifier = required(result, "id")
    checkpoint("YouTube video " + identifier)
    returned = object_data(result.get("status", {}))
    visibility = str(returned.get("privacyStatus", "unknown"))
    if scheduled:
        message = (
            "schedule accepted"
            if returned.get("publishAt")
            else "schedule NOT confirmed; check Studio"
        )
    else:
        message = f"upload accepted ({visibility}); processing may still be in progress"
    return f"https://youtu.be/{identifier} · {message}"


def instagram(client: httpx.Client, job: Job, token: str, checkpoint: Checkpoint) -> str:
    headers = {"Authorization": "Bearer " + token}
    info = data(
        client.post(
            f"{GRAPH}/{job.account_id}/media",
            headers=headers,
            data={"media_type": "REELS", "upload_type": "resumable", "caption": job.text},
        )
    )
    identifier = required(info, "id")
    checkpoint("Instagram container " + identifier)
    address = upload_url(info.get("uri"), "rupload.facebook.com")
    path = Path(job.path)
    size = str(path.stat().st_size)
    data(
        client.post(
            address,
            headers={
                "Authorization": "OAuth " + token,
                "offset": "0",
                "file_size": size,
                "Content-Length": size,
                "Content-Type": "application/octet-stream",
            },
            content=file_chunks(path),
        )
    )
    for _ in range(100):
        status = data(
            client.get(f"{GRAPH}/{identifier}", headers=headers, params={"fields": "status_code"})
        ).get("status_code")
        if status == "FINISHED":
            break
        if status in ("ERROR", "EXPIRED"):
            raise ClipsError(f"Instagram container {identifier} is {status.lower()}.")
        time.sleep(3)
    else:
        raise ClipsError(
            f"Instagram is still processing container {identifier}; check the account."
        )
    result = data(
        client.post(
            f"{GRAPH}/{job.account_id}/media_publish",
            headers=headers,
            data={"creation_id": identifier},
        )
    )
    return "Instagram published · media " + required(result, "id")


def tiktok(client: httpx.Client, job: Job, token: str, checkpoint: Checkpoint) -> str:
    headers = {"Authorization": "Bearer " + token}
    base = "https://open.tiktokapis.com/v2/post/publish"
    path = Path(job.path)
    size = path.stat().st_size
    chunk_size = min(size, 16 * 1024 * 1024)
    count = max(1, size // chunk_size)
    result = data(
        client.post(
            base + "/inbox/video/init/",
            headers=headers,
            json={
                "source_info": {
                    "source": "FILE_UPLOAD",
                    "video_size": size,
                    "chunk_size": chunk_size,
                    "total_chunk_count": count,
                }
            },
        )
    )
    info = object_data(result.get("data"))
    identifier = required(info, "publish_id")
    checkpoint("TikTok upload " + identifier)
    address = upload_url(info.get("upload_url"), "tiktokapis.com")
    with path.open("rb") as stream:
        offset = 0
        for index in range(count):
            chunk = stream.read(size - offset if index == count - 1 else chunk_size)
            check(
                client.put(
                    address,
                    content=chunk,
                    headers={
                        "Content-Type": "video/mp4",
                        "Content-Length": str(len(chunk)),
                        "Content-Range": f"bytes {offset}-{offset + len(chunk) - 1}/{size}",
                    },
                )
            )
            offset += len(chunk)
    for _ in range(100):
        result = data(
            client.post(base + "/status/fetch/", headers=headers, json={"publish_id": identifier})
        )
        status = object_data(result.get("data")).get("status")
        if status in ("SEND_TO_USER_INBOX", "PUBLISH_COMPLETE"):
            return "TikTok inbox delivered · finish editing and posting in TikTok · " + identifier
        if status == "FAILED":
            raise ClipsError(
                f"TikTok rejected upload {identifier}; check the account and media limits."
            )
        time.sleep(3)
    raise ClipsError(f"TikTok is still processing upload {identifier}; check your inbox.")


def publish(job: Job, account: Account, checkpoint: Checkpoint) -> str:
    validate(job)
    with httpx.Client(timeout=httpx.Timeout(120, connect=20), follow_redirects=False) as client:
        token = access_token(account, client)
        return {"youtube": youtube, "instagram": instagram, "tiktok": tiktok}[job.platform](
            client, job, token, checkpoint
        )
