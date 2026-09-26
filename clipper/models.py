"""Shared clip, transcript, and progress types."""

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal, TypeGuard

type Framing = Literal["face", "black"]
type ProgressCallback = Callable[[str, float | None], None]


class ClipsError(Exception):
    """A failure that can be shown directly in the terminal."""


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
class Transcript:
    video: Video
    cues: list[Cue]
    language: str
    automatic: bool


@dataclass(frozen=True)
class Clip:
    start: float
    end: float
    title: str
    description: str
    hashtags: list[str] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return self.end - self.start

    @property
    def publishing_text(self) -> str:
        return (
            "\n\n".join(filter(None, (self.title, self.description, " ".join(self.hashtags))))
            + "\n"
        )


def finite_number(value: object) -> TypeGuard[int | float]:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
