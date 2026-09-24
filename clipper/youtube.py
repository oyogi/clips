"""Download a YouTube video's existing captions and cache its source video."""

import logging
import re
import shutil
import time
from dataclasses import asdict
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from yt_dlp import YoutubeDL
from yt_dlp.networking import Request
from yt_dlp.utils import DownloadError

from .models import (
    ClipsError,
    Cue,
    SkipVideo,
    Video,
    dump_json,
    finite_number,
    read_json,
)
from .subtitles import clean_text, parse_captions

log = logging.getLogger(__name__)
VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}\Z")


class QuietLogger:
    def debug(self, message):
        pass

    def warning(self, message):
        log.debug("yt-dlp: %s", message)

    def error(self, message):
        log.debug("yt-dlp: %s", message)


def video_from_url(value):
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
    if not VIDEO_ID.fullmatch(identifier):
        raise ClipsError("Enter a link to one video, rather than a channel or playlist.")
    return video_from_info({"id": identifier})


def video_from_info(info):
    identifier = info.get("id", "")
    if not VIDEO_ID.fullmatch(identifier):
        raise SkipVideo("Entry is not a YouTube video.")
    return Video(
        id=identifier,
        url=f"https://www.youtube.com/watch?v={identifier}",
        title=str(info.get("title") or identifier),
        channel=str(info.get("channel") or info.get("uploader") or ""),
        duration=info.get("duration") if finite_number(info.get("duration")) else None,
    )


def subtitle_choices(info):
    """Prefer English, then the original language; never request a translation."""
    choices = []
    original = str(info.get("language") or "").lower().split("-")[0]
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
                    base != "en", base != original, automatic,
                    language, ["json3", "srt", "vtt"].index(extension),
                )
                choices.append((priority, language, automatic, track))
    for _, language, automatic, track in sorted(choices, key=lambda choice: choice[0]):
        yield language, automatic, track


class YouTube:
    def __init__(self, cache: Path):
        self.cache = cache.resolve()

    def options(self, **extra):
        runtimes = {name: {} for name in ("deno", "node") if shutil.which(name)}
        options = {
            "quiet": True,
            "no_warnings": True,
            "logger": QuietLogger(),
            "cachedir": str(self.cache / "yt-dlp"),
            "socket_timeout": 25,
            "retries": 3,
            "extractor_retries": 2,
            "js_runtimes": runtimes,
            "noplaylist": True,
        }
        options.update(extra)
        return options

    def captions(self, url):
        candidate = video_from_url(url)
        directory = self.cache / candidate.id
        cache_file = directory / "captions.json"
        if cache_file.exists():
            try:
                cached = read_json(cache_file)
                # Clean old cached text too, keeping IDs/times for pasted replies.
                cues = [Cue(**{**cue, "text": clean_text(cue["text"])}) for cue in cached["cues"]]
                if cues:
                    return Video(**cached["video"]), cues, cached["track"]
            except (OSError, ValueError, KeyError, TypeError):
                pass
        try:
            with YoutubeDL(self.options()) as ydl:
                info = ydl.extract_info(candidate.url, download=False)
                if not info or info.get("is_live") or info.get("live_status") == "is_upcoming":
                    raise SkipVideo("Live/upcoming or unavailable video.")
                video = video_from_info(info)
                choices = list(subtitle_choices(info))
                if not choices:
                    raise SkipVideo("This video has no existing subtitles.")
                errors = []
                for language, automatic, track in choices:
                    try:
                        content = track.get("data")
                        if content is None:
                            for attempt in range(3):
                                try:
                                    request = Request(
                                        track["url"], headers=info.get("http_headers", {})
                                    )
                                    with ydl.urlopen(request) as response:
                                        content = response.read(8 * 1024 * 1024 + 1)
                                    if len(content) > 8 * 1024 * 1024:
                                        raise SkipVideo("Subtitle track is too large (over 8 MiB).")
                                    content = content.decode("utf-8-sig")
                                    break
                                except SkipVideo:
                                    raise
                                except Exception:
                                    if attempt == 2:
                                        raise
                                    time.sleep(2**attempt)
                        cues = parse_captions(content, track["ext"])
                        if video.duration is not None:
                            cues = [
                                Cue(c.id, c.start, min(c.end, video.duration), c.text)
                                for c in cues
                                if c.start < video.duration
                            ]
                        if not cues:
                            raise SkipVideo("Subtitle cues are outside the video's duration.")
                        detail = {"language": language, "automatic": automatic}
                        dump_json(
                            cache_file,
                            {"video": asdict(video), "cues": [asdict(cue) for cue in cues], "track": detail},
                        )
                        return video, cues, detail
                    except Exception as error:
                        errors.append(f"{language}/{track['ext']}: {error}")
                raise SkipVideo("Could not read any subtitle track: " + "; ".join(errors)[-600:])
        except DownloadError as error:
            raise SkipVideo(f"YouTube metadata unavailable: {error}") from error

    def download(self, video, progress=None):
        directory = self.cache / video.id
        directory.mkdir(parents=True, exist_ok=True)
        marker = directory / "download.json"
        if marker.exists():
            try:
                filename = read_json(marker)["filename"]
                cached = directory / Path(filename).name
                if cached.is_file() and cached.stat().st_size > 0:
                    if progress:
                        progress("Using cached video", 1.0)
                    return cached
            except (ValueError, KeyError, OSError, TypeError):
                pass
        def update(data):
            if not progress:
                return
            total = data.get("total_bytes") or data.get("total_bytes_estimate")
            if data.get("status") == "downloading":
                progress("Downloading source", min(1.0, data.get("downloaded_bytes", 0) / total) if total else None)
            elif data.get("status") == "finished":
                progress("Preparing source", None)

        try:
            with YoutubeDL(
                self.options(
                    format="bv*[height<=1080]+ba/b[height<=1080]/b",
                    merge_output_format="mkv",
                    outtmpl=str(directory / "source.%(ext)s"),
                    continuedl=True,
                    overwrites=False,
                    progress_hooks=[update],
                )
            ) as ydl:
                ydl.extract_info(video.url, download=True)
        except DownloadError as error:
            raise SkipVideo(f"Video download failed: {error}") from error
        # A merge may change the extension; do not mistake .part/fragments for final files.
        for suffix in ("mkv", "mp4", "webm", "mov"):
            path = directory / f"source.{suffix}"
            if path.is_file() and path.stat().st_size > 0:
                dump_json(marker, {"filename": path.name})
                return path
        raise SkipVideo("yt-dlp finished without a usable video file.")
