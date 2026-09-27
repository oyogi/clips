"""Review finished clips and choose destinations and posting times."""

import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from rich.markup import escape
from rich.prompt import Confirm, Prompt
from rich.style import Style
from rich.table import Table
from rich.text import Text

from ..clipboard import copy_text
from ..models import Clip, ClipsError
from ..ui import console, section
from .accounts import manage_accounts
from .platforms import validate
from .queue import start_worker
from .store import LABELS, Job, Platform, accounts, enqueue, fingerprint


@dataclass(frozen=True)
class Export:
    path: Path
    clip: Clip


def parse_time(value: str) -> float:
    if value.lower() == "now":
        return 0
    try:
        chosen = datetime.fromisoformat(value)
        if chosen.tzinfo is None:
            timestamp = chosen.timestamp()
            local = datetime.fromtimestamp(timestamp, UTC).astimezone().replace(tzinfo=None)
            if local != chosen:
                raise ValueError("This local time does not exist.")
            if chosen.replace(fold=0).timestamp() != chosen.replace(fold=1).timestamp():
                raise ValueError("This local time is ambiguous. Include a UTC offset, e.g. -03:00.")
        else:
            timestamp = chosen.timestamp()
        if timestamp < time.time() + 600:
            raise ValueError("Choose a time at least 10 minutes from now, or enter now.")
        return timestamp
    except (ValueError, OverflowError, OSError) as error:
        raise ClipsError(f"Invalid posting time: {error}") from error


def review(exports: list[Export]) -> list[Export]:
    remaining = {str(number): export for number, export in enumerate(exports, 1)}
    console.print("Open the paths below to review. Deleting a clip removes its MP4 and TXT.")
    while remaining:
        table = Table(box=None, padding=(0, 2), show_edge=False, pad_edge=False)
        table.add_column("#", style="accent", no_wrap=True)
        table.add_column("Clips to upload")
        for number, export in remaining.items():
            path = export.path.resolve()
            detail = Text(export.clip.title)
            detail.append(f"\n{path}", style=console.get_style("muted") + Style(link=path.as_uri()))
            table.add_row(number, detail)
        console.print(table)
        number = Prompt.ask(
            "Number to delete (Enter to continue)", default="", console=console
        ).strip()
        if not number:
            break
        if number not in remaining:
            console.print("Enter one of the listed numbers.", style="warning")
            continue
        export = remaining[number]
        export.path.unlink(missing_ok=True)
        export.path.with_suffix(".txt").unlink(missing_ok=True)
        del remaining[number]
        console.print(f"Deleted {export.path.name} and its TXT.", style="muted", markup=False)
    selected = list(remaining.values())
    if not selected:
        console.print("No clips left to upload.", style="muted")
    if len(selected) == 1 and copy_text(selected[0].clip.publishing_text, persist=True):
        console.print("Publishing text copied.", style="success")
    return selected


def choose_platforms() -> list[Platform]:
    connected = accounts()
    if not connected:
        console.print(
            "Connect an account first. Setup instructions: docs/publishing.md", style="muted"
        )
        manage_accounts()
        connected = accounts()
    selected = []
    for platform, account in connected.items():
        if Confirm.ask(
            f"Upload to {LABELS[platform]} · {escape(account.label)}?",
            default=False,
            console=console,
        ):
            selected.append(platform)
    return selected


def make_jobs(
    exports: list[Export],
    platforms: list[Platform],
    times: list[float],
    privacy: str,
    made_for_kids: bool,
    expected_accounts: dict[Platform, str] | None = None,
) -> list[Job]:
    connected = accounts()
    for platform in platforms:
        if platform not in connected or (
            expected_accounts is not None
            and connected[platform].id != expected_accounts.get(platform)
        ):
            raise ClipsError(
                "A selected account changed. Check youtube-clips accounts before uploading."
            )
    result = []
    for export, when in zip(exports, times, strict=True):
        checksum = fingerprint(export.path)
        for platform in platforms:
            if platform == "instagram" and not 3 <= export.clip.duration <= 900:
                raise ClipsError("Instagram Reels must be between 3 seconds and 15 minutes.")
            job = Job(
                platform,
                connected[platform].id,
                str(export.path.resolve()),
                export.clip.title,
                export.clip.publishing_text.strip(),
                when,
                checksum,
                "public" if when and platform == "youtube" else privacy,
                made_for_kids,
            )
            validate(job)
            result.append(job)
    return result


def submit(jobs: list[Job]) -> None:
    enqueue(jobs)
    start_worker()
    console.print("Uploads queued. Check progress with youtube-clips queue.", style="success")
    console.print("Keep these MP4 files in place until their uploads finish.", style="muted")


def posting_time() -> float:
    while True:
        value = Prompt.ask("Post at · YYYY-MM-DD HH:MM, or now", default="now", console=console)
        try:
            return parse_time(value.strip())
        except ClipsError as error:
            console.print(str(error), style="warning", markup=False)


def time_label(timestamp: float) -> str:
    return (
        datetime.fromtimestamp(timestamp).astimezone().strftime("%Y-%m-%d %H:%M %z")
        if timestamp
        else "Now"
    )


def offer_upload(exports: list[Export]) -> None:
    if not Confirm.ask("Upload or schedule these clips?", default=False, console=console):
        return
    section("Publish")
    exports = review(exports)
    if not exports:
        return
    platforms = choose_platforms()
    if not platforms:
        return
    expected_accounts = {platform: account.id for platform, account in accounts().items()}
    console.print(
        "YouTube: native scheduling. Instagram: this computer must stay awake and online."
    )
    if "tiktok" in platforms:
        console.print(
            "TikTok: the chosen time delivers a draft to your inbox, not a published post. "
            "Add the TXT caption and finish posting in TikTok.",
            style="warning",
        )
    console.print(f"Local time: {datetime.now().astimezone():%Y-%m-%d %H:%M %Z (%z)}")
    times = []
    for export in exports:
        console.print(export.path.name, style="accent")
        times.append(posting_time())
    privacy = "private"
    made_for_kids = False
    if "youtube" in platforms:
        if any(when == 0 for when in times):
            privacy = Prompt.ask(
                "YouTube visibility for immediate uploads",
                choices=["private", "unlisted", "public"],
                default="private",
                console=console,
            )
        if any(times):
            console.print("Scheduled YouTube clips are private until their time, then public.")
        made_for_kids = Confirm.ask(
            "Are these clips made for kids?", default=False, console=console
        )
    jobs = make_jobs(exports, platforms, times, privacy, made_for_kids, expected_accounts)
    table = Table(box=None, padding=(0, 2), show_edge=False)
    for column in ("Clip", "Destination", "Time"):
        table.add_column(column)
    for job in jobs:
        table.add_row(Path(job.path).name, LABELS[job.platform], time_label(job.when))
    console.print(table)
    if Confirm.ask("Send these uploads?", default=False, console=console):
        submit(jobs)
