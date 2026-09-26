"""Private local account storage and an upload queue."""

import hashlib
import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from ..models import ClipsError

type Platform = Literal["youtube", "instagram", "tiktok"]
PLATFORMS: tuple[Platform, ...] = ("youtube", "instagram", "tiktok")
LABELS = {"youtube": "YouTube", "instagram": "Instagram", "tiktok": "TikTok drafts"}


def state_directory() -> Path:
    root = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))
    directory = root / "youtube-clips"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory.chmod(0o700)
    return directory


@contextmanager
def database() -> Iterator[sqlite3.Connection]:
    path = state_directory() / "publishing.sqlite3"
    path.touch(mode=0o600, exist_ok=True)
    path.chmod(0o600)
    connection = sqlite3.connect(path, timeout=30)
    connection.row_factory = sqlite3.Row
    try:
        with connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS accounts (platform TEXT PRIMARY KEY, data TEXT)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS jobs (id INTEGER PRIMARY KEY, data TEXT, "
                "due REAL, state TEXT DEFAULT 'queued', result TEXT DEFAULT '')"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, data TEXT)"
            )
            yield connection
    finally:
        connection.close()


def object_data(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ClipsError("Unexpected response or invalid saved publishing data.")
    return value


@dataclass
class Account:
    platform: Platform
    id: str
    label: str
    secrets: dict[str, str] = field(default_factory=dict, repr=False)

    def save(self) -> None:
        with database() as db:
            db.execute(
                "INSERT OR REPLACE INTO accounts VALUES (?, ?)",
                (self.platform, json.dumps(asdict(self))),
            )


def accounts() -> dict[Platform, Account]:
    with database() as db:
        return {
            row["platform"]: Account(**object_data(json.loads(row["data"])))
            for row in db.execute("SELECT * FROM accounts")
        }


def fingerprint(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


@dataclass(frozen=True)
class Job:
    platform: Platform
    account_id: str
    path: str
    title: str
    text: str
    when: float
    sha256: str
    privacy: str = "private"
    made_for_kids: bool = False


@dataclass(frozen=True)
class SavedJob:
    id: int
    job: Job
    due: float
    state: str
    result: str


def enqueue(jobs: list[Job]) -> None:
    with database() as db:
        for job in jobs:
            db.execute(
                "INSERT INTO jobs (data, due) VALUES (?, ?)",
                (json.dumps(asdict(job)), 0 if job.platform == "youtube" else job.when),
            )


def jobs() -> list[SavedJob]:
    with database() as db:
        return [
            SavedJob(
                row["id"],
                Job(**object_data(json.loads(row["data"]))),
                row["due"],
                row["state"],
                row["result"],
            )
            for row in db.execute("SELECT * FROM jobs ORDER BY id")
        ]


def update(job_id: int, state: str, result: str) -> None:
    with database() as db:
        db.execute("UPDATE jobs SET state=?, result=? WHERE id=?", (state, result, job_id))
