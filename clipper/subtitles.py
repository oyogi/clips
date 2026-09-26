"""Read existing captions, clean rolling captions, and rebase them for each clip."""

import html
import json
import re
import textwrap
from collections.abc import Iterable, Sequence
from itertools import pairwise
from pathlib import Path

import pysubs2

from .models import ClipsError, Cue, finite_number


def clean_text(text: str) -> str:
    text = re.sub(r"<[^>]*>", "", text)
    text = re.sub(r"\{\\[^}]*\}", "", text)
    text = html.unescape(text).replace("\u200b", "")
    text = re.sub(r"(?<!\S)>{2,}\s*", "", text)
    return " ".join(text.split())


def normalize_cues(rows: Iterable[tuple[float, float, str]]) -> list[Cue]:
    cleaned: list[tuple[float, float, str]] = []
    for start, end, text in sorted(rows, key=lambda row: row[0]):
        text = clean_text(text)
        if not text or not finite_number(start) or not finite_number(end):
            continue
        start, end = max(0.0, start), max(0.0, end)
        if end <= start:
            continue
        if cleaned and start == cleaned[-1][0]:
            # Progressive caption revisions with the same start: keep the fuller line.
            old = cleaned[-1]
            if len(text) >= len(old[2]):
                cleaned[-1] = (start, max(end, old[1]), text)
            continue
        if cleaned and start < cleaned[-1][1]:
            prev_start, prev_end, prev_text = cleaned[-1]
            if text == prev_text:
                cleaned[-1] = (prev_start, max(prev_end, end), prev_text)
                continue
            previous, current = prev_text.split(), text.split()
            overlap = 0
            for size in range(min(len(previous), len(current)), 0, -1):
                if previous[-size:] == current[:size]:
                    overlap = size
                    break
            # Remove overlap only: adjacent repetition may be actual speech.
            text = " ".join(current[overlap:])
            if not text:
                continue
            cleaned[-1] = (prev_start, min(prev_end, start), prev_text)
        cleaned.append((start, end, text))
    return [Cue(i, round(s, 3), round(e, 3), t) for i, (s, e, t) in enumerate(cleaned)]


def parse_captions(content: str, extension: str) -> list[Cue]:
    rows: list[tuple[float, float, str]] = []
    if extension == "json3":
        events = json.loads(content).get("events", [])
        for event in events:
            if not event.get("segs"):
                continue
            start = event.get("tStartMs", 0)
            duration = event.get("dDurationMs", 0)
            if not finite_number(start) or not finite_number(duration):
                continue
            text = "".join(segment.get("utf8", "") for segment in event["segs"])
            rows.append((start / 1000, (start + duration) / 1000, text))
    else:
        subs = pysubs2.SSAFile.from_string(content, format_=extension)
        rows = [(s.start / 1000, s.end / 1000, s.plaintext) for s in subs]
    cues = normalize_cues(rows)
    if not cues:
        raise ClipsError("Subtitle track has no usable timed text.")
    return cues


def caption_cards(
    cues: Sequence[Cue],
    start: float,
    end: float,
    chars_per_line: int = 18,
) -> list[tuple[int, int, str]]:
    cards = []
    for cue in cues:
        left, right = max(cue.start, start), min(cue.end, end)
        if right <= left:
            continue
        # Literal user text must not turn into ASS formatting instructions.
        text = cue.text.replace("\\", "＼").replace("{", "｛").replace("}", "｝")
        lines = textwrap.wrap(text, width=chars_per_line, break_long_words=True)
        pages = ["\n".join(lines[i : i + 2]) for i in range(0, len(lines), 2)]
        total = sum(len(page) for page in pages)
        position = left
        for index, page in enumerate(pages):
            stop = (
                right if index == len(pages) - 1 else position + (right - left) * len(page) / total
            )
            a, b = round((position - start) * 1000), round((stop - start) * 1000)
            if b > a:
                cards.append((a, b, page))
            position = stop
    return cards


def write_clip_subtitles(
    cues: Sequence[Cue],
    start: float,
    end: float,
    directory: Path,
    width: int = 1080,
    height: int = 1920,
    middle_ranges: Sequence[tuple[float, float]] = (),
) -> None:
    subs = pysubs2.SSAFile()
    subs.info.update({"PlayResX": str(width), "PlayResY": str(height), "WrapStyle": "2"})
    subs.styles["Default"] = pysubs2.SSAStyle(
        fontname="DejaVu Sans",
        fontsize=min(width * 0.09, height * 0.072),
        bold=True,
        outline=width * 0.00525,
        shadow=width * 0.00225,
        alignment=pysubs2.Alignment.BOTTOM_CENTER,
        marginl=round(width * 0.07),
        marginr=round(width * 0.10),
        marginv=round(height * 0.14),
    )
    for left, right, text in caption_cards(cues, start, end):
        words = list(re.finditer(r"\S+", text))
        weights = [max(1, len(re.sub(r"\W", "", word.group()))) for word in words]
        total, elapsed = sum(weights), 0
        for word, weight in zip(words, weights, strict=True):
            word_start = left + round((right - left) * elapsed / total)
            elapsed += weight
            word_end = left + round((right - left) * elapsed / total)
            if word_end <= word_start:
                continue
            highlighted = (
                text[: word.start()]
                + r"{\1c&H0069C9F3&}"
                + word.group()
                + r"{\r}"
                + text[word.end() :]
            )
            boundaries = sorted(
                {word_start, word_end}
                | {
                    round(boundary * 1000)
                    for interval in middle_ranges
                    for boundary in interval
                    if word_start < round(boundary * 1000) < word_end
                }
            )
            for event_start, event_end in pairwise(boundaries):
                middle = any(
                    left * 1000 <= event_start < right * 1000 for left, right in middle_ranges
                )
                position = rf"{{\an5\pos({width // 2},{height // 2})}}" if middle else ""
                subs.append(
                    pysubs2.SSAEvent(
                        start=event_start,
                        end=event_end,
                        text=position + highlighted.replace("\n", r"\N"),
                    )
                )
    if not subs:
        raise ClipsError("Selected interval contains no subtitles.")
    subs.save(str(directory / "captions.ass"), encoding="utf-8")
