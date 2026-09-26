"""Background download with progress and cancellation of the FFmpeg merger."""

import multiprocessing
import os
import signal
import time
from dataclasses import dataclass
from multiprocessing.connection import Connection
from pathlib import Path
from typing import Self

from .models import ClipsError, ProgressCallback, Video
from .youtube import download_video


@dataclass(frozen=True)
class DownloadState:
    stage: str = "Starting download"
    fraction: float | None = None
    source: Path | None = None
    error: str | None = None


def _download(directory: Path, video: Video, connection: Connection) -> None:
    os.setsid()
    last_update = 0.0

    def update(stage: str, fraction: float | None) -> None:
        nonlocal last_update
        now = time.monotonic()
        if now - last_update >= 0.25:
            connection.send(DownloadState(stage, fraction))
            last_update = now

    try:
        source = download_video(video, directory, update)
        connection.send(DownloadState("Video ready", 1.0, source=source))
    except Exception as error:
        connection.send(DownloadState("Download failed", error=str(error)))
    finally:
        connection.close()


class SourceDownload:
    def __init__(self, directory: Path, video: Video) -> None:
        context = multiprocessing.get_context("spawn")
        self._receive, self._send = context.Pipe(duplex=False)
        self._process = context.Process(
            target=_download, args=(directory, video, self._send), daemon=True
        )
        self._state = DownloadState()

    def __enter__(self) -> Self:
        try:
            self._process.start()
        except BaseException:
            if self._process.pid:
                self._stop(signal.SIGKILL)
                self._process.join()
            self._process.close()
            self._receive.close()
            raise
        finally:
            self._send.close()
        return self

    def __exit__(self, *_exc: object) -> None:
        self._process.join(timeout=0.2)
        for sig in (signal.SIGTERM, signal.SIGKILL):
            if self._process.is_alive():
                self._stop(sig)
                self._process.join(timeout=1 if sig == signal.SIGTERM else None)
        self._receive.close()
        self._process.close()

    def _stop(self, sig: signal.Signals) -> None:
        pid = self._process.pid
        assert pid is not None
        try:
            if os.getpgid(pid) == pid:
                os.killpg(pid, sig)
            else:
                os.kill(pid, sig)  # The worker may not have called setsid yet.
        except ProcessLookupError:
            pass

    def poll(self) -> DownloadState:
        while not (self._state.source or self._state.error) and self._receive.poll():
            try:
                self._state = self._receive.recv()
            except EOFError:
                self._state = DownloadState(
                    "Download failed", error="The downloader stopped unexpectedly."
                )
        return self._state

    def result(self, progress: ProgressCallback) -> Path:
        while True:
            state = self.poll()
            progress(state.stage, state.fraction)
            if state.error:
                raise ClipsError(state.error)
            if state.source:
                return state.source
            self._receive.poll(0.1)
