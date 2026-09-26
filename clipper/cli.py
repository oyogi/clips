"""Interactive workflow from a YouTube link to finished clips."""

import argparse
import logging
import sqlite3
import tempfile
import time
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

import httpx
from rich.prompt import IntPrompt, Prompt
from rich.text import Text

from . import ui
from .clipboard import copy_text
from .download import SourceDownload
from .manual import make_prompt, parse_reply
from .models import Clip, ClipsError, Framing, Transcript
from .publishing.automatic import Automatic, load_automatic
from .publishing.workflow import Export, offer_upload
from .render import Encoder, check_encoder, render_clip
from .ui import console
from .youtube import read_transcript


def choose_video() -> Transcript | None:
    while True:
        url = Prompt.ask(
            "YouTube URL [muted](Enter to quit)[/muted]",
            default="",
            show_default=False,
            console=console,
        ).strip()
        if not url:
            return None
        try:
            with console.status("Reading captions…", spinner="dots"):
                return read_transcript(url)
        except ClipsError as error:
            console.print(Text(f"Skipped: {error}", style="warning"))


def get_clips(source: Transcript, count: int, download: SourceDownload) -> list[Clip]:
    prompt = make_prompt(source, count)
    if copy_text(prompt):
        console.print(
            "[success]Prompt copied.[/success] Paste it into ChatGPT, then paste its reply below."
        )
    else:
        console.print("[warning]Clipboard unavailable. Copy the prompt below.[/warning]")
        console.print("----- PROMPT START -----", style="muted")
        console.print(prompt, markup=False, soft_wrap=True)
        console.print("----- PROMPT END -----", style="muted")
    console.print("[muted]The video downloads while you use ChatGPT.[/muted]\n")
    while True:
        try:
            clips = parse_reply(ui.read_reply(download), source, count)
        except ClipsError as error:
            console.print(Text(f"{error}\nPaste a corrected reply to try again.", style="warning"))
            continue
        if clips:
            return clips
        console.print("[warning]No clips selected. Ask ChatGPT for another selection.[/warning]")


def create_clips(
    source: Path,
    clips: Sequence[Clip],
    transcript: Transcript,
    encoder: Encoder,
    layout: Framing,
    automatic: Automatic | None = None,
) -> int:
    output = Path("output") / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    exports: list[Export] = []
    started = time.monotonic()
    for number, clip in enumerate(clips, 1):
        label = Text(f"{number:02d}  ", style="accent")
        label.append(clip.title, style="bold")
        label.append(f"  {clip.duration:.1f}s", style="muted")
        console.print(label)
        try:
            with ui.progress("Preparing clip", encoder.kind) as update:
                path, note = render_clip(
                    source, clip, transcript.cues, output, number, encoder, layout, update
                )
            exports.append(Export(path, clip))
            console.print(f"[success]{path.name}[/success]  [muted]{encoder.kind}[/muted]")
            if note:
                console.print(Text(note, style="muted"))
        except ClipsError as error:
            console.print(Text(f"Could not render clip {number}: {error}", style="error"))

    elapsed = time.monotonic() - started
    if not exports:
        console.print("[error]No clips were created.[/error]")
        return 1
    copied = False
    paths = [export.path for export in exports]
    if len(paths) == 1:
        copied = copy_text(paths[0].with_suffix(".txt").read_text(encoding="utf-8"), persist=True)
        if not copied:
            console.print("[warning]Clipboard unavailable; use the TXT file.[/warning]")
    ui.summary(paths, len(clips), elapsed, copied)
    if automatic:
        automatic.upload(exports)
    else:
        offer_upload(exports)
    return 0 if len(paths) == len(clips) else 1


def run(automatic: Automatic | None = None) -> int:
    with console.status("Checking video tools…", spinner="dots"):
        encoder = check_encoder()
    ui.header(encoder)
    ui.section("Source")
    transcript = choose_video()
    if transcript is None:
        return 0
    ui.video_details(transcript)
    with tempfile.TemporaryDirectory(prefix="clips-") as temporary:
        with SourceDownload(Path(temporary), transcript.video) as download:
            while True:
                count = IntPrompt.ask("Clips", default=1, console=console)
                if 1 <= count <= 100:
                    break
                console.print("[warning]Enter a number from 1 to 100.[/warning]")
            layout: Framing = "auto" if automatic else ui.choose_layout()
            ui.section("Selection")
            clips = get_clips(transcript, count, download)
            if len(clips) < count:
                console.print(
                    f"[muted]ChatGPT selected {len(clips)} of {count} requested clips.[/muted]"
                )
            ui.section("Export")
            with ui.progress("Downloading video") as update:
                source = download.result(update)
        return create_clips(source, clips, transcript, encoder, layout, automatic)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Make portrait clips from a YouTube video using ChatGPT in your browser."
    )
    parser.add_argument(
        "command",
        nargs="?",
        choices=["auto", "auto-setup", "accounts", "queue", "doctor"],
        help="automatic runs, publishing preferences, accounts, uploads, or hardware checks",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    try:
        if args.command == "doctor":
            from .detection import benchmark

            with console.status("Checking encoders and face detection…"):
                encoder = check_encoder()
                detector, gpu = benchmark()
            console.print(f"Encoding: {encoder.kind} · {encoder.name}")
            console.print(
                f"Face detection: {detector.label} · {detector.milliseconds:.1f} ms/sample"
            )
            if not gpu:
                console.print(
                    "No OpenCV GPU compute backend is available. VA-API encoding is independent."
                )
            console.print(
                "Detection benchmark uses a 640 × 360 synthetic frame; real clips can differ.",
                style="muted",
            )
            return 0
        if args.command == "accounts":
            from .publishing.accounts import manage_accounts

            manage_accounts()
            return 0
        if args.command == "queue":
            from .publishing.queue import show_queue

            show_queue()
            return 0
        if args.command == "auto-setup":
            from .publishing.automatic import configure

            configure()
            return 0
        if args.command == "auto":
            return run(load_automatic())
        return run()
    except httpx.HTTPError:
        console.print(
            "[error]Could not reach the publishing service. Check your connection and account setup.[/error]"
        )
        return 1
    except sqlite3.Error as error:
        console.print(Text(f"Publishing database unavailable: {error}", style="error"))
        return 1
    except (ClipsError, OSError) as error:
        console.print(Text(f"Error: {error}", style="error"))
        return 1
    except (KeyboardInterrupt, EOFError):
        console.print("\n[muted]Stopped. Finished clips are in output/.[/muted]")
        return 130
