"""Read existing YouTube captions and download a source into a session folder."""

import logging
import re
import shutil
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from yt_dlp import YoutubeDL
from yt_dlp.networking import Request
from yt_dlp.utils import DownloadError

from .models import ClipsError, Cue, ProgressCallback, Transcript, Video, finite_number
from .subtitles import parse_captions

type Metadata = dict[str, Any]
VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}\Z")


class QuietLogger:
    def debug(self, message: str) -> None:
        logging.getLogger(__name__).debug("yt-dlp: %s", message)

    warning = error = debug


def _options() -> Metadata:
    return {
        "quiet": True,
        "no_warnings": True,
        "logger": QuietLogger(),
        "cachedir": False,
        "socket_timeout": 25,
        "retries": 3,
        "extractor_retries": 2,
        "js_runtimes": {name: {} for name in ("deno", "node") if shutil.which(name)},
        "noplaylist": True,
    }


def video_from_url(value: str) -> Video:
    try:
        parsed = urlparse(value)
        host = (parsed.hostname or "").lower()
    except ValueError as error:
        raise ClipsError("Enter a valid YouTube video URL.") from error
    if parsed.scheme not in {"https", "http"} or not (
        host in {"youtube.com", "youtu.be", "www.youtu.be"} or host.endswith(".youtube.com")
    ):
        raise ClipsError("Enter a YouTube video URL.")
    if parsed.username or parsed.password:
        raise ClipsError("YouTube URLs must not contain credentials.")
    if host in {"youtu.be", "www.youtu.be"}:
        identifier = parsed.path.strip("/")
    elif parsed.path.startswith(("/shorts/", "/embed/", "/live/")):
        identifier = parsed.path.strip("/").split("/")[-1]
    else:
        identifier = parse_qs(parsed.query).get("v", [""])[0]
    return _video({"id": identifier})


def _video(info: Metadata) -> Video:
    identifier = info.get("id", "")
    if not isinstance(identifier, str) or not VIDEO_ID.fullmatch(identifier):
        raise ClipsError("Enter a link to one YouTube video.")
    duration = info.get("duration")
    return Video(
        id=identifier,
        url=f"https://www.youtube.com/watch?v={identifier}",
        title=str(info.get("title") or identifier),
        channel=str(info.get("channel") or info.get("uploader") or ""),
        duration=duration if finite_number(duration) else None,
    )


def _tracks(info: Metadata) -> Iterator[tuple[str, bool, Metadata]]:
    original = str(info.get("language") or "").lower().split("-")[0]
    choices = []
    for automatic, table in (
        (False, info.get("subtitles") or {}),
        (True, info.get("automatic_captions") or {}),
    ):
        for language, tracks in table.items():
            base = language.lower().replace("_", "-").split("-")[0]
            for track in tracks:
                extension = track.get("ext")
                if extension not in {"json3", "srt", "vtt"}:
                    continue
                if parse_qs(urlparse(track.get("url", "")).query).get("tlang"):
                    continue
                priority = (
                    base != "en",
                    base != original,
                    automatic,
                    language,
                    ["json3", "srt", "vtt"].index(extension),
                )
                choices.append((priority, language, automatic, track))
    for _, language, automatic, track in sorted(choices, key=lambda choice: choice[0]):
        yield language, automatic, track


def _caption_text(ydl: YoutubeDL, track: Metadata, headers: dict[str, str]) -> str:
    if isinstance(content := track.get("data"), str):
        return content
    for attempt in range(3):
        try:
            with ydl.urlopen(Request(track["url"], headers=headers)) as response:
                data: bytes = response.read(8 * 1024 * 1024 + 1)
            if len(data) > 8 * 1024 * 1024:
                raise ClipsError("Subtitle track exceeds 8 MiB.")
            return data.decode("utf-8-sig")
        except ClipsError:
            raise
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2**attempt)
    raise ClipsError("Could not fetch subtitles.")


def read_transcript(url: str) -> Transcript:
    candidate = video_from_url(url)
    try:
        with YoutubeDL(_options()) as ydl:
            info = ydl.extract_info(candidate.url, download=False)
            if not info or info.get("is_live") or info.get("live_status") == "is_upcoming":
                raise ClipsError("Live, upcoming or unavailable video.")
            video = _video(info)
            errors = []
            for language, automatic, track in _tracks(info):
                try:
                    content = _caption_text(ydl, track, info.get("http_headers", {}))
                    cues = parse_captions(content, track["ext"])
                    if video.duration is not None:
                        cues = [
                            Cue(c.id, c.start, min(c.end, video.duration), c.text)
                            for c in cues
                            if c.start < video.duration
                        ]
                    if not cues:
                        raise ClipsError("Subtitle cues are outside the video's duration.")
                    return Transcript(video, cues, language, automatic)
                except Exception as error:
                    errors.append(f"{language}/{track['ext']}: {error}")
            if errors:
                raise ClipsError("Could not read subtitles: " + "; ".join(errors)[-600:])
            raise ClipsError("This video has no existing subtitles.")
    except DownloadError as error:
        raise ClipsError(f"YouTube metadata unavailable: {error}") from error


def download_video(video: Video, directory: Path, progress: ProgressCallback) -> Path:
    def update(data: Metadata) -> None:
        total = data.get("total_bytes") or data.get("total_bytes_estimate")
        if data.get("status") == "downloading":
            progress(
                "Downloading video",
                min(1.0, data.get("downloaded_bytes", 0) / total) if total else None,
            )
        elif data.get("status") == "finished":
            progress("Preparing video", None)

    options = _options() | {
        "format": "bv*[height<=1080]+ba/b[height<=1080]/b",
        "merge_output_format": "mkv",
        "outtmpl": str(directory / "source.%(ext)s"),
        "progress_hooks": [update],
    }
    try:
        with YoutubeDL(options) as ydl:
            ydl.extract_info(video.url, download=True)
    except DownloadError as error:
        raise ClipsError(f"Video download failed: {error}") from error
    for suffix in ("mkv", "mp4", "webm", "mov"):
        path = directory / f"source.{suffix}"
        if path.is_file() and path.stat().st_size > 0:
            return path
    raise ClipsError("yt-dlp finished without a usable video file.")
