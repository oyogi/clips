import json
import math
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path


class ClipsError(Exception):
    """A user-actionable failure."""


class SkipVideo(ClipsError):
    """This source is unsuitable; continue with other sources."""


@dataclass(frozen=True)
class Cue:
    id: int
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class Video:
    id: str
    url: str
    title: str
    channel: str = ""
    duration: float | None = None


@dataclass(frozen=True)
class Clip:
    start: float
    end: float
    title: str
    description: str
    hashtags: list[str] = field(default_factory=list)

    @property
    def duration(self):
        return self.end - self.start


def finite_number(value):
    return type(value) in (int, float) and math.isfinite(value)


def dump_json(path: Path, data):
    """Atomic writes keep interrupted downloads from leaving corrupt cache files."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=".json-", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))

