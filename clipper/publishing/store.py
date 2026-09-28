"""Private local storage for a YouTube account and its upload queue."""

import hashlib
import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

from ..models import ClipsError


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
                "state TEXT DEFAULT 'queued', result TEXT DEFAULT '')"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, data TEXT)"
            )
            migrate(connection)
            connection.commit()
            yield connection
    finally:
        connection.close()


def migrate(db: sqlite3.Connection) -> None:
    if db.execute("PRAGMA user_version").fetchone()[0]:
        return
    db.execute("BEGIN IMMEDIATE")
    if db.execute("PRAGMA user_version").fetchone()[0]:
        return
    db.execute("DELETE FROM accounts WHERE platform <> 'youtube'")
    db.execute("UPDATE accounts SET data=json_remove(data, '$.platform')")
    db.execute("DELETE FROM jobs WHERE json_extract(data, '$.platform') IS NOT 'youtube'")
    db.execute(
        "UPDATE jobs SET state='cancelled', result='Publishing now uses public visibility and "
        "not made for kids. Review and retry this upload to use those settings.' "
        "WHERE state='queued' AND ((json_extract(data, '$.when')=0 AND "
        "json_extract(data, '$.privacy') IS NOT 'public') "
        "OR json_extract(data, '$.made_for_kids')=1)"
    )
    db.execute(
        "UPDATE jobs SET data=json_remove(data, '$.platform', '$.privacy', '$.made_for_kids')"
    )
    if any(row["name"] == "due" for row in db.execute("PRAGMA table_info(jobs)")):
        db.execute("ALTER TABLE jobs DROP COLUMN due")
    db.execute("DELETE FROM settings WHERE key='automatic'")
    db.execute("PRAGMA user_version=1")


def object_data(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ClipsError("Unexpected response or invalid saved publishing data.")
    return value


def saved_record[T](model: type[T], text: str) -> T:
    try:
        return model(**object_data(json.loads(text)))
    except (TypeError, ValueError) as error:
        raise ClipsError(
            "Saved publishing data is unreadable. Check the publishing database in "
            + str(state_directory())
            + "."
        ) from error


@dataclass
class Account:
    id: str
    label: str
    secrets: dict[str, str] = field(default_factory=dict, repr=False)

    def save(self, *, refresh: bool = False) -> None:
        with database() as db:
            if refresh:
                db.execute("BEGIN IMMEDIATE")
                current = db.execute(
                    "SELECT data FROM accounts WHERE platform='youtube'"
                ).fetchone()
                if not current or object_data(json.loads(current["data"])).get("id") != self.id:
                    raise ClipsError(
                        "The account was disconnected or replaced during token refresh."
                    )
            db.execute(
                "INSERT OR REPLACE INTO accounts VALUES ('youtube', ?)",
                (json.dumps(asdict(self)),),
            )


def account() -> Account | None:
    with database() as db:
        row = db.execute("SELECT data FROM accounts WHERE platform='youtube'").fetchone()
    return saved_record(Account, row["data"]) if row else None


def fingerprint(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


@dataclass(frozen=True)
class Job:
    account_id: str
    path: str
    title: str
    text: str
    when: float
    sha256: str


@dataclass(frozen=True)
class SavedJob:
    id: int
    job: Job
    state: str
    result: str


def enqueue(jobs: list[Job]) -> None:
    with database() as db:
        for job in jobs:
            db.execute(
                "INSERT INTO jobs (data) VALUES (?)",
                (json.dumps(asdict(job)),),
            )


def jobs() -> list[SavedJob]:
    with database() as db:
        return [
            SavedJob(
                row["id"],
                saved_record(Job, row["data"]),
                row["state"],
                row["result"],
            )
            for row in db.execute("SELECT * FROM jobs ORDER BY id")
        ]


def update(job_id: int, state: str, result: str) -> None:
    with database() as db:
        db.execute("UPDATE jobs SET state=?, result=? WHERE id=?", (state, result, job_id))


def retry(entry: SavedJob, when: float) -> None:
    if entry.state not in ("failed", "check account", "cancelled"):
        raise ClipsError("Only failed, interrupted or cancelled jobs can be retried.")
    job = replace(entry.job, when=when)
    with database() as db:
        changed = db.execute(
            "UPDATE jobs SET state='queued', result='', data=? WHERE id=? AND state=?",
            (
                json.dumps(asdict(job)),
                entry.id,
                entry.state,
            ),
        ).rowcount
    if not changed:
        raise ClipsError("This job changed while you were editing it. Open the queue again.")
