"""Saved publishing choices for runs without a post-render review."""

import json
import time
from dataclasses import asdict, dataclass

from rich.prompt import Confirm, IntPrompt, Prompt

from ..models import ClipsError
from ..ui import console
from .store import LABELS, Platform, accounts, database, saved_record
from .workflow import Export, choose_platforms, make_jobs, submit


@dataclass(frozen=True)
class Automatic:
    destinations: dict[Platform, str]
    privacy: str
    made_for_kids: bool
    delay_minutes: int
    interval_minutes: int

    def validate(self) -> None:
        connected = accounts()
        if not self.destinations or any(
            platform not in connected or connected[platform].id != identifier
            for platform, identifier in self.destinations.items()
        ):
            raise ClipsError("Automatic mode's accounts changed. Run youtube-clips auto-setup.")
        if not (
            self.delay_minutes == self.interval_minutes == 0
            or self.delay_minutes >= 10
            and self.interval_minutes >= 10
        ):
            raise ClipsError("Invalid automatic posting times. Run youtube-clips auto-setup.")
        if self.privacy not in ("private", "unlisted", "public"):
            raise ClipsError("Invalid automatic visibility. Run youtube-clips auto-setup.")

    def upload(self, exports: list[Export]) -> None:
        self.validate()
        start = time.time() + self.delay_minutes * 60
        times = [
            start + index * self.interval_minutes * 60
            if self.delay_minutes or self.interval_minutes
            else 0
            for index in range(len(exports))
        ]
        submit(
            make_jobs(
                exports,
                list(self.destinations),
                times,
                self.privacy,
                self.made_for_kids,
                self.destinations,
            )
        )


def minutes(label: str, default: int) -> int:
    while True:
        value = IntPrompt.ask(label, default=default, console=console)
        if value >= 10:
            return value
        console.print("Choose at least 10 minutes.", style="warning")


def configure() -> Automatic:
    console.print("Automatic runs use Faces framing and upload every finished clip without review.")
    platforms = choose_platforms()
    if not platforms:
        raise ClipsError("Select at least one destination for automatic mode.")
    timing = Prompt.ask("Posting", choices=["now", "spaced"], default="now", console=console)
    delay = minutes("Minutes until the first clip", 15) if timing == "spaced" else 0
    interval = minutes("Minutes between clips", 60) if timing == "spaced" else 0
    privacy, kids = "private", False
    if "youtube" in platforms:
        if timing == "spaced":
            privacy = "public"
            console.print(
                "Scheduled YouTube clips become PUBLIC at their posting time.", style="warning"
            )
        else:
            privacy = Prompt.ask(
                "YouTube visibility",
                choices=["private", "unlisted", "public"],
                default="private",
                console=console,
            )
        kids = Confirm.ask("Are these clips made for kids?", default=False, console=console)
    if "instagram" in platforms:
        console.print(
            "Instagram publishes to the connected account. Local schedules need this PC awake."
        )
    if "tiktok" in platforms:
        console.print(
            "TikTok receives drafts; you still finish posting and add captions in TikTok."
        )
    connected = accounts()
    for platform in platforms:
        console.print(f"{LABELS[platform]} · {connected[platform].label}", markup=False)
    if not Confirm.ask(
        "Save these choices for automatic uploads without review?", default=False, console=console
    ):
        raise ClipsError("Automatic setup cancelled; no preferences were changed.")
    settings = Automatic(
        {platform: connected[platform].id for platform in platforms}, privacy, kids, delay, interval
    )
    with database() as db:
        db.execute(
            "INSERT OR REPLACE INTO settings VALUES ('automatic', ?)",
            (json.dumps(asdict(settings)),),
        )
    return settings


def load_automatic() -> Automatic:
    with database() as db:
        row = db.execute("SELECT data FROM settings WHERE key='automatic'").fetchone()
    settings = saved_record(Automatic, row["data"]) if row else configure()
    settings.validate()
    console.print(
        "Automatic mode · " + ", ".join(LABELS[platform] for platform in settings.destinations),
        style="accent",
        markup=False,
    )
    console.print(
        "Every finished clip will upload without review. Change this with youtube-clips auto-setup.",
        style="muted",
    )
    return settings
