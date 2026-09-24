"""Render portrait clips with subtitles and a chosen framing style."""

import json
import re
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

from .faces import face_commands
from .models import ClipsError, finite_number
from .subtitles import write_clip_subtitles


def command(args, timeout=30):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ClipsError(f"Could not run {args[0]}: {error}") from error
    if result.returncode:
        raise ClipsError(f"{args[0]} failed: {result.stderr[-2500:].strip()}")
    return result.stdout


def check_encoder():
    for executable in ("ffmpeg", "ffprobe"):
        if not shutil.which(executable):
            raise ClipsError(f"Install {executable} and put it on PATH.")
    filters = command(["ffmpeg", "-hide_banner", "-filters"])
    for name in ("ass", "sendcmd"):
        if not re.search(rf"\b{name}\s", filters):
            raise ClipsError(f"FFmpeg needs the {name} filter.")
    encoders = command(["ffmpeg", "-hide_banner", "-encoders"])
    if not re.search(r"\baac\s", encoders):
        raise ClipsError("FFmpeg needs an AAC audio encoder.")
    for name in ("libx264", "libopenh264"):
        if not re.search(rf"\b{name}\s", encoders):
            continue
        try:
            command([
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                "-i", "color=c=black:s=180x320:d=0.1",
                "-c:v", name, "-b:v", "500k", "-f", "null", "-",
            ])
            return name
        except ClipsError:
            continue
    raise ClipsError("No working H.264 encoder. Install FFmpeg with libx264 or libopenh264.")


def check_media(path, end=None, size=None):
    try:
        info = json.loads(command([
            "ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path),
        ]))
    except ValueError as error:
        raise ClipsError("ffprobe returned invalid video information.") from error
    streams = info.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if not video or not audio:
        raise ClipsError("The video must have both a picture and an audio track.")
    try:
        duration = float(info["format"]["duration"])
    except (ValueError, KeyError, TypeError) as error:
        raise ClipsError("Cannot determine the video duration.") from error
    if not finite_number(duration) or duration <= 0 or (end is not None and end > duration + 0.1):
        raise ClipsError("The chosen clip extends beyond the video.")
    if size and (video.get("width"), video.get("height")) != size:
        raise ClipsError("The rendered video has incorrect dimensions.")
    return duration


def video_filters(width, height, layout, following=False):
    # Normalize pixel shape before fitting/cropping; preserve the display aspect.
    start = "[0:v]setpts=PTS-STARTPTS,scale=trunc(iw*sar/2)*2:ih,setsar=1,"
    finish = "setsar=1,ass=captions.ass,format=yuv420p[v]"
    fit = f"scale={width}:{height}:force_original_aspect_ratio=decrease:force_divisible_by=2"
    fill = f"scale={width}:{height}:force_original_aspect_ratio=increase:force_divisible_by=2"
    if layout == "blur":
        small_w, small_h = width // 8 * 2, height // 8 * 2
        return (
            start + "split=2[back][front];"
            f"[back]scale={small_w}:{small_h}:force_original_aspect_ratio=increase,"
            f"crop={small_w}:{small_h},boxblur=8:1,scale={width}:{height}[bg];"
            f"[front]{fit}[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2,{finish}"
        )
    if layout == "black":
        return start + f"{fit},pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,{finish}"
    if following:
        crop = f"sendcmd=f=face.cmd,crop@face={width}:{height}"
    else:
        crop = f"crop={width}:{height}:(iw-ow)/2:(ih-oh)/2"
    return start + f"{fill},{crop},{finish}"


def encode(args, work, duration, progress):
    # Separate stderr keeps the progress pipe from filling with codec messages.
    with tempfile.TemporaryFile(mode="w+") as errors:
        with subprocess.Popen(
            args, cwd=work, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=errors, text=True,
        ) as process:
            timer = threading.Timer(max(180, duration * 30), process.kill)
            timer.daemon = True
            timer.start()
            try:
                for line in process.stdout:
                    if line.startswith("out_time_us=") and progress:
                        try:
                            seconds = int(line.split("=", 1)[1]) / 1_000_000
                        except ValueError:
                            continue
                        progress("Encoding", max(0.0, min(1.0, seconds / duration)))
                code = process.wait()
            except BaseException:
                process.kill()
                process.wait()
                raise
            finally:
                timer.cancel()
        if code:
            errors.seek(0)
            raise ClipsError("FFmpeg failed: " + (errors.read()[-2500:].strip() or "Encoding timed out."))
    if progress:
        progress("Encoding", 1.0)


def render_clip(source, clip, cues, output, number, encoder, layout="blur", progress=None):
    check_media(source, end=clip.end)
    width, height = 1080, 1920
    output.mkdir(parents=True, exist_ok=True)
    destination = output / f"clip-{number:02d}.mp4"
    note = ""
    with tempfile.TemporaryDirectory(prefix=".render-", dir=output) as temporary:
        work = Path(temporary)
        write_clip_subtitles(cues, clip.start, clip.end, work, width, height)
        following = False
        if layout == "face":
            if progress:
                progress("Tracking faces", 0.0)
            following = face_commands(source, clip, width, height, work / "face.cmd", progress)
            if not following:
                note = "No face found; used a centered crop."
        codec = (
            ["-c:v", "libx264", "-crf", "20", "-preset", "fast"]
            if encoder == "libx264"
            else ["-c:v", "libopenh264", "-b:v", "6M"]
        )
        if progress:
            progress("Encoding", 0.0)
        encode([
            "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
            "-progress", "pipe:1", "-nostats", "-ss", f"{clip.start:.3f}",
            "-i", str(source.resolve()), "-t", f"{clip.duration:.3f}",
            "-filter_complex", video_filters(width, height, layout, following),
            "-map", "[v]", "-map", "0:a:0", "-af", "asetpts=PTS-STARTPTS",
            *codec, "-r", "30", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            "-movflags", "+faststart", "-map_metadata", "-1", "video.mp4",
        ], work, clip.duration, progress)
        duration = check_media(work / "video.mp4", size=(width, height))
        if abs(duration - clip.duration) > 0.25:
            raise ClipsError("The rendered duration does not match the chosen clip.")
        post = "\n\n".join(part for part in (clip.title, clip.description, " ".join(clip.hashtags)) if part)
        (work / "post.txt").write_text(post + "\n", encoding="utf-8")
        (work / "video.mp4").replace(destination)
        (work / "post.txt").replace(destination.with_suffix(".txt"))
    return destination, note
