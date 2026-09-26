"""A detached, single-worker queue; pending jobs survive terminal sessions."""

import fcntl
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx
from rich.prompt import Confirm, Prompt
from rich.table import Table
from rich.text import Text

from ..models import ClipsError
from ..ui import console
from .platforms import publish
from .store import LABELS, accounts, database, fingerprint, jobs, retry, state_directory, update


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
    from .workflow import posting_time, time_label

    while True:
        start_worker()
        entries = jobs()
        if not entries:
            console.print("No uploads queued.", style="muted")
            return
        console.print(
            f"\nUploads · local time {datetime.now().astimezone():%H:%M %Z}", style="heading"
        )
        table = Table(box=None, padding=(0, 1), show_edge=False, expand=True)
        table.add_column("ID", style="accent", no_wrap=True)
        table.add_column("Destination")
        table.add_column("Clip", ratio=1)
        table.add_column("Posting time")
        table.add_column("State")
        for entry in entries:
            style = (
                "success"
                if entry.state == "done"
                else "error"
                if entry.state in ("failed", "check account")
                else "muted"
            )
            table.add_row(
                str(entry.id),
                LABELS[entry.job.platform],
                Text(entry.job.title),
                time_label(entry.job.when),
                Text(entry.state, style=style),
            )
        console.print(table)
        for entry in entries:
            if entry.result:
                console.print(f"{entry.id} · {entry.result}", markup=False, style="muted")
        console.print("Uploaded YouTube schedules are managed in YouTube Studio.", style="muted")
        choice = (
            Prompt.ask(
                "refresh · cancel ID · retry ID · Enter to close",
                default="",
                show_default=False,
                console=console,
            )
            .strip()
            .lower()
        )
        if not choice:
            return
        if choice == "refresh":
            continue
        parts = choice.split()
        if len(parts) != 2 or parts[0] not in ("cancel", "retry") or not parts[1].isdecimal():
            console.print("Use cancel 3 or retry 3, for example.", style="warning")
            continue
        selected = next((entry for entry in entries if entry.id == int(parts[1])), None)
        if selected is None:
            console.print("Job not found.", style="warning")
        elif parts[0] == "cancel":
            with database() as db:
                changed = db.execute(
                    "UPDATE jobs SET state='cancelled' WHERE id=? AND state='queued'",
                    (selected.id,),
                ).rowcount
            console.print("Cancelled." if changed else "This job has already started or finished.")
        elif selected.state not in ("failed", "check account", "cancelled"):
            console.print(
                "Only failed, interrupted or cancelled jobs can be retried.", style="warning"
            )
        else:
            console.print(selected.job.text, markup=False)
            console.print(
                "Check the destination account first: an interrupted upload may already exist."
            )
            when = posting_time()
            if selected.job.platform == "youtube":
                console.print(
                    f"YouTube visibility: {'public at the scheduled time' if when else selected.job.privacy}"
                )
            if Confirm.ask(
                "I checked the account; upload this clip again?", default=False, console=console
            ):
                retry(selected, when)


if __name__ == "__main__":
    worker()
