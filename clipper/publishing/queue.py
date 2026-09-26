"""A detached, single-worker queue; pending jobs survive terminal sessions."""

import fcntl
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
from rich.prompt import Prompt
from rich.table import Table

from ..models import ClipsError
from ..ui import console
from .platforms import publish
from .store import LABELS, accounts, database, fingerprint, jobs, state_directory, update


def worker() -> None:
    os.umask(0o077)
    with (state_directory() / "worker.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        with database() as db:
            db.execute(
                "UPDATE jobs SET state='check account', result=result || "
                "' · Worker interrupted; verify remotely before uploading again.' WHERE state='uploading'"
            )
        while True:
            pending = [entry for entry in jobs() if entry.state == "queued"]
            if not pending:
                return
            entry = min(pending, key=lambda item: item.due)
            if entry.due > time.time():
                time.sleep(min(15, entry.due - time.time()))
                continue
            with database() as db:
                claimed = db.execute(
                    "UPDATE jobs SET state='uploading' WHERE id=? AND state='queued'", (entry.id,)
                ).rowcount
            if not claimed:
                continue
            reference = ""

            def checkpoint(message: str, job_id: int = entry.id) -> None:
                nonlocal reference
                reference = message
                update(job_id, "uploading", message)

            try:
                job = entry.job
                if job.when and time.time() - job.when > 900:
                    raise ClipsError(
                        "Posting time was missed by more than 15 minutes. Schedule again."
                    )
                account = accounts().get(job.platform)
                if account is None or account.id != job.account_id:
                    raise ClipsError("The selected account was disconnected or replaced.")
                if fingerprint(Path(job.path)) != job.sha256:
                    raise ClipsError(
                        "The clip changed after it was queued. Schedule the updated file again."
                    )
                message = publish(job, account, checkpoint)
                update(entry.id, "done", message)
            except (ClipsError, OSError, httpx.HTTPError, ValueError, KeyError) as error:
                message = (
                    str(error)
                    if isinstance(error, ClipsError)
                    else "Upload interrupted or invalid account data."
                )
                if reference:
                    message = f"{reference} · {message} Verify the account before uploading again."
                update(entry.id, "check account" if reference else "failed", message)


def start_worker() -> None:
    if not any(entry.state == "queued" for entry in jobs()):
        return
    with (state_directory() / "worker.log").open("ab") as log:
        log_path = Path(log.name)
        log_path.chmod(0o600)
        process = subprocess.Popen(
            [sys.executable, "-m", "clipper.publishing.queue"],
            cwd=Path(__file__).resolve().parents[2],
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            start_new_session=True,
        )
    time.sleep(0.1)
    if process.poll() not in (None, 0):
        raise ClipsError("Could not start the upload worker. See youtube-clips queue.")


def show_queue() -> None:
    start_worker()
    entries = jobs()
    table = Table(box=None, padding=(0, 2), show_edge=False)
    for column in ("ID", "Destination", "Clip", "State"):
        table.add_column(column)
    for entry in entries:
        table.add_row(
            str(entry.id), LABELS[entry.job.platform], Path(entry.job.path).name, entry.state
        )
    console.print(table)
    for entry in entries:
        if entry.result:
            console.print(f"{entry.id} · {entry.result}", markup=False)
    if any(entry.state == "queued" for entry in entries):
        choice = Prompt.ask(
            "Cancel queued job ID (Enter to leave running)", default="", console=console
        )
        if choice.isdecimal():
            with database() as db:
                changed = db.execute(
                    "UPDATE jobs SET state='cancelled' WHERE id=? AND state='queued'",
                    (int(choice),),
                ).rowcount
            console.print("Cancelled." if changed else "Job already started or not found.")
    console.print(
        "YouTube schedules already uploaded must be changed in YouTube Studio.", style="muted"
    )


if __name__ == "__main__":
    worker()
