"""Render portrait H.264 clips with burned-in subtitles."""

import json
import re
import shutil
import subprocess
import tempfile
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .faces import FramingPlan, plan_framing, sample_faces, write_commands
from .models import Clip, ClipsError, Cue, Framing, ProgressCallback, finite_number
from .subtitles import write_clip_subtitles


@dataclass(frozen=True)
class Encoder:
    name: str
    device: str | None = None
    low_power: bool = False

    @property
    def kind(self) -> str:
        return "GPU" if self.device else "CPU"

    @property
    def input_options(self) -> list[str]:
        return ["-vaapi_device", self.device] if self.device else []

    @property
    def pixel_filter(self) -> str:
        return "format=nv12,hwupload" if self.device else "format=yuv420p"

    @property
    def video_options(self) -> list[str]:
        if self.device:
            return ["-c:v", self.name, "-b:v", "6M", "-low_power", str(int(self.low_power))]
        if self.name == "libx264":
            return "-c:v libx264 -crf 20 -preset fast".split()
        return ["-c:v", self.name, "-b:v", "6M"]


def command(args: list[str], timeout: float = 30) -> str:
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ClipsError(f"Could not run {args[0]}: {error}") from error
    if result.returncode:
        raise ClipsError(f"{args[0]} failed: {result.stderr[-2500:].strip()}")
    return result.stdout


def check_encoder() -> Encoder:
    for executable in ("ffmpeg", "ffprobe"):
        if not shutil.which(executable):
            raise ClipsError(f"Install {executable} and put it on PATH.")
    filters = command("ffmpeg -hide_banner -filters".split())
    for name in ("ass", "sendcmd"):
        if not re.search(rf"\b{name}\s", filters):
            raise ClipsError(f"FFmpeg needs the {name} filter.")
    encoders = command("ffmpeg -hide_banner -encoders".split())
    if not re.search(r"\baac\s", encoders):
        raise ClipsError("FFmpeg needs an AAC audio encoder.")
    candidates = [
        Encoder("h264_vaapi", str(device), low_power)
        for device in sorted(Path("/dev/dri").glob("renderD*"))
        for low_power in (True, False)
    ] + [Encoder(name) for name in ("libx264", "libopenh264")]
    for encoder in candidates:
        if not re.search(rf"\b{encoder.name}\s", encoders):
            continue
        try:
            # Listed GPU encoders can still lack a working driver or profile.
            command(
                "ffmpeg -nostdin -hide_banner -loglevel error".split()
                + encoder.input_options
                + "-f lavfi -i color=c=black:s=1080x1920:r=30:d=0.1".split()
                + ["-vf", encoder.pixel_filter]
                + encoder.video_options
                + "-f null -".split(),
                timeout=8,
            )
            return encoder
        except ClipsError:
            continue
    raise ClipsError("No working H.264 encoder. Install libx264, libopenh264, or a VA-API driver.")


def check_media(path: Path, end: float | None = None, size: tuple[int, int] | None = None) -> float:
    try:
        info = json.loads(
            command("ffprobe -v error -show_streams -show_format -of json".split() + [str(path)])
        )
    except ValueError as error:
        raise ClipsError("ffprobe returned invalid video information.") from error
    streams = info.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if not video or not any(s.get("codec_type") == "audio" for s in streams):
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


def video_filters(
    width: int,
    height: int,
    layout: Framing,
    pixel_filter: str = "format=yuv420p",
    plan: FramingPlan | None = None,
) -> str:
    start = "[0:v]setpts=PTS-STARTPTS,scale=trunc(iw*sar/2)*2:ih,setsar=1,"
    finish = f"setsar=1,ass=captions.ass,{pixel_filter}[v]"
    fit = f"scale={width}:{height}:force_original_aspect_ratio=decrease:force_divisible_by=2"
    fill = f"scale={width}:{height}:force_original_aspect_ratio=increase:force_divisible_by=2"
    if layout == "face" and plan:
        views = {scene.view for scene in plan.scenes}
        if views == {"black"}:
            return start + f"{fit},pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,{finish}"
        if views == {"face"}:
            return start + f"{fill},sendcmd=f=face.cmd,crop@face={width}:{height},{finish}"
        if views == {"split"}:
            return (
                start + f"{fill},split=2[first][second];"
                f"[first]sendcmd=f=top.cmd,crop@top={width}:{height // 2}[top];"
                f"[second]sendcmd=f=bottom.cmd,crop@bottom={width}:{height // 2}[bottom];"
                f"[top][bottom]vstack=inputs=2,{finish}"
            )
        parts = [
            start + "split=2[whole][people]",
            f"[whole]{fit},pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black[full]",
            f"[people]{fill},split=3[single][first][second]",
            f"[single]sendcmd=f=face.cmd,crop@face={width}:{height}[face]",
            f"[first]sendcmd=f=top.cmd,crop@top={width}:{height // 2}[top]",
            f"[second]sendcmd=f=bottom.cmd,crop@bottom={width}:{height // 2}[bottom]",
            "[top][bottom]vstack=inputs=2[pair]",
        ]
        for view, foreground, background, result in (
            ("face", "face", "full", "composed"),
            ("split", "pair", "composed", "framed"),
        ):
            enabled = (
                "+".join(
                    f"gte(t,{scene.start:.6f})*lt(t,{scene.end:.6f})"
                    for scene in plan.scenes
                    if scene.view == view
                )
                or "0"
            )
            parts.append(f"[{background}][{foreground}]overlay=0:0:enable='{enabled}'[{result}]")
        return ";".join(parts + [f"[framed]{finish}"])
    return start + f"{fit},pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,{finish}"


def encode(args: list[str], work: Path, duration: float, progress: ProgressCallback | None) -> None:
    # Keep stderr separate so codec messages cannot block the progress pipe.
    with tempfile.TemporaryFile(mode="w+") as errors:
        with subprocess.Popen(
            args,
            cwd=work,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=errors,
            text=True,
        ) as process:
            assert process.stdout is not None
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
            raise ClipsError(
                "FFmpeg failed: " + (errors.read()[-2500:].strip() or "Encoding timed out.")
            )
    if progress:
        progress("Encoding", 1.0)


def render_clip(
    source: Path,
    clip: Clip,
    cues: Sequence[Cue],
    output: Path,
    number: int,
    encoder: Encoder,
    layout: Framing = "face",
    progress: ProgressCallback | None = None,
) -> tuple[Path, str]:
    check_media(source, end=clip.end)
    width, height = 1080, 1920
    output.mkdir(parents=True, exist_ok=True)
    destination = output / f"clip-{number:02d}.mp4"
    note = ""
    with tempfile.TemporaryDirectory(prefix=".render-", dir=output) as temporary:
        work = Path(temporary)
        plan = None
        if layout == "face":
            if progress:
                progress("Finding faces", 0.0)
            try:
                scan = sample_faces(source, clip, progress)
                plan = plan_framing(scan.samples, clip.duration)
                write_commands(plan, work, width, height, clip.duration)
                note = plan.summary + f" · detection: {scan.engine}"
            except ClipsError as error:
                layout, note = "black", f"{error} Used the full picture on black."
        write_clip_subtitles(
            cues,
            clip.start,
            clip.end,
            work,
            width,
            height,
            plan.split_ranges if plan and layout == "face" else (),
        )
        if progress:
            progress("Encoding", 0.0)
        encode(
            "ffmpeg -nostdin -hide_banner -loglevel error -y".split()
            + encoder.input_options
            + [
                "-progress",
                "pipe:1",
                "-nostats",
                "-ss",
                f"{clip.start:.3f}",
                "-i",
                str(source.resolve()),
                "-t",
                f"{clip.duration:.3f}",
                "-filter_complex",
                video_filters(width, height, layout, encoder.pixel_filter, plan),
            ]
            + "-map [v] -map 0:a:0 -af asetpts=PTS-STARTPTS".split()
            + encoder.video_options
            + "-r 30 -c:a aac -b:a 128k -ar 48000 -ac 2 -movflags +faststart -map_metadata -1 video.mp4".split(),
            work,
            clip.duration,
            progress,
        )
        duration = check_media(work / "video.mp4", size=(width, height))
        if abs(duration - clip.duration) > 0.25:
            raise ClipsError("The rendered duration does not match the chosen clip.")
        (work / "post.txt").write_text(clip.publishing_text, encoding="utf-8")
        (work / "video.mp4").replace(destination)
        (work / "post.txt").replace(destination.with_suffix(".txt"))
    return destination, note
