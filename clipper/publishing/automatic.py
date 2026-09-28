"""Saved YouTube timing for runs without a post-render review."""

import json
import time
from dataclasses import asdict, dataclass

from rich.prompt import Confirm, IntPrompt

from ..models import ClipsError, finite_number
from ..ui import console
from .accounts import require_account
from .store import account, database, saved_record
from .workflow import Export, make_jobs, posting_interval, posting_times, submit


@dataclass(frozen=True)
class Automatic:
    account_id: str
    delay_minutes: int
    interval_hours: float

    def validate(self) -> None:
        connected = account()
        if connected is None or connected.id != self.account_id:
            raise ClipsError("Automatic mode's account changed. Run youtube-clips auto-setup.")
        if not finite_number(self.delay_minutes) or not (
            self.delay_minutes == 0 or self.delay_minutes >= 10
        ):
            raise ClipsError("Invalid automatic posting delay. Run youtube-clips auto-setup.")
        first = time.time() + self.delay_minutes * 60 if self.delay_minutes else 0
        posting_times(first, self.interval_hours, 100)

    def upload(self, exports: list[Export]) -> None:
        self.validate()
        first = time.time() + self.delay_minutes * 60 if self.delay_minutes else 0
        times = posting_times(first, self.interval_hours, len(exports))
        submit(make_jobs(exports, times, self.account_id))


def configure() -> Automatic:
    console.print("Automatic runs use Faces framing and upload every finished clip without review.")
    connected = require_account()
    console.print("YouTube · Public · Not made for kids", style="muted")
    console.print("The first clip's delay starts when rendering finishes.", style="muted")
    while True:
        delay = IntPrompt.ask(
            "Minutes until the first clip (0 for now)", default=15, console=console
        )
        if delay == 0 or delay >= 10:
            break
        console.print("Choose zero or at least 10 minutes.", style="warning")
    settings = Automatic(connected.id, delay, posting_interval())
    settings.validate()
    if not Confirm.ask(
        "Save this timing for automatic YouTube uploads without review?",
        default=False,
        console=console,
    ):
        raise ClipsError("Automatic setup cancelled; no preferences were changed.")
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
    console.print("Automatic mode · YouTube · Public · Not made for kids", style="accent")
    console.print(
        "Every finished clip will upload without review. Change timing with youtube-clips auto-setup.",
        style="muted",
    )
    return settings
