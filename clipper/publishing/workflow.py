"""Review finished clips and space their YouTube publication times."""

import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from rich.prompt import Confirm, FloatPrompt, Prompt
from rich.style import Style
from rich.table import Table
from rich.text import Text

from ..clipboard import copy_text
from ..models import Clip, ClipsError, finite_number
from ..ui import console, section
from .accounts import require_account
from .queue import start_worker
from .store import Job, account, enqueue, fingerprint
from .youtube import validate


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


def make_jobs(exports: list[Export], times: list[float], account_id: str) -> list[Job]:
    connected = account()
    if connected is None or connected.id != account_id:
        raise ClipsError(
            "The YouTube account changed. Check youtube-clips accounts before uploading."
        )
    result = []
    for export, when in zip(exports, times, strict=True):
        job = Job(
            connected.id,
            str(export.path.resolve()),
            export.clip.title,
            export.clip.publishing_text.strip(),
            when,
            fingerprint(export.path),
        )
        validate(job)
        result.append(job)
    return result


def submit(jobs: list[Job]) -> None:
    enqueue(jobs)
    start_worker()
    console.print("Uploads queued. Check progress with youtube-clips queue.", style="success")
    console.print("Keep these MP4 files in place until their uploads finish.", style="muted")
    console.print(
        "All clips upload now. Once YouTube accepts every upload and schedule, "
        "you can turn the computer off.",
        style="muted",
    )


def posting_time(label: str = "Post at") -> float:
    while True:
        value = Prompt.ask(f"{label} · YYYY-MM-DD HH:MM, or now", default="now", console=console)
        try:
            return parse_time(value.strip())
        except ClipsError as error:
            console.print(str(error), style="warning", markup=False)


def time_label(timestamp: float) -> str:
    return (
        datetime.fromtimestamp(timestamp, UTC).astimezone().strftime("%Y-%m-%d %H:%M %z")
        if timestamp
        else "Now"
    )


def posting_interval() -> float:
    while True:
        hours = FloatPrompt.ask("Hours between clips (0 for together)", default=2, console=console)
        if finite_number(hours) and hours >= 0:
            return hours
        console.print("Enter zero or a positive number of hours.", style="warning")


def posting_times(first: float, interval_hours: float, count: int) -> list[float]:
    if (
        not finite_number(first)
        or first < 0
        or not finite_number(interval_hours)
        or interval_hours < 0
    ):
        raise ClipsError("Invalid posting time or interval.")
    start = first or time.time()
    times = [
        0
        if not first and (index == 0 or not interval_hours)
        else start + index * interval_hours * 3600
        for index in range(count)
    ]
    try:
        for when in times:
            datetime.fromtimestamp(when, UTC)
    except (ValueError, OverflowError, OSError) as error:
        raise ClipsError("The interval puts a clip beyond the supported date range.") from error
    return times


def offer_upload(exports: list[Export]) -> None:
    if not Confirm.ask(
        "Upload or schedule these clips on YouTube?", default=False, console=console
    ):
        return
    section("Publish")
    exports = review(exports)
    if not exports:
        return
    connected = require_account()
    console.print("Public · Not made for kids", style="muted")
    console.print(f"Local time: {datetime.now(UTC).astimezone():%Y-%m-%d %H:%M %Z (%z)}")
    while True:
        first = posting_time("First clip")
        interval = posting_interval() if len(exports) > 1 else 0
        try:
            times = posting_times(first, interval, len(exports))
            break
        except ClipsError as error:
            console.print(str(error), style="warning", markup=False)
    jobs = make_jobs(exports, times, connected.id)
    table = Table(box=None, padding=(0, 2), show_edge=False)
    for column in ("Clip", "Public on YouTube"):
        table.add_column(column)
    for job in jobs:
        table.add_row(Path(job.path).name, time_label(job.when))
    console.print(table)
    if Confirm.ask("Upload these clips?", default=False, console=console):
        submit(jobs)
