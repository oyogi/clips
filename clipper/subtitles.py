"""Read existing captions, clean rolling captions, and rebase them for each clip."""

import html
import json
import re
import textwrap
from pathlib import Path

import pysubs2

from .models import Cue, SkipVideo, finite_number


def clean_text(text):
    text = re.sub(r"<[^>]*>", "", text)
    text = re.sub(r"\{\\[^}]*\}", "", text)
    text = html.unescape(text).replace("\u200b", "")
    # YouTube captions may prefix a new speaker with >> (including &gt;&gt;).
    text = re.sub(r"(?<!\S)>{2,}\s*", "", text)
    return " ".join(text.split())


def normalize_cues(rows):
    cleaned = []
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
            # Only remove repeated words from overlapping rolling captions.
            # Adjacent, non-overlapping repetitions may be actual speech.
            text = " ".join(current[overlap:])
            if not text:
                continue
            cleaned[-1] = (prev_start, min(prev_end, start), prev_text)
        cleaned.append((start, end, text))
    return [Cue(i, round(s, 3), round(e, 3), t) for i, (s, e, t) in enumerate(cleaned)]


def parse_captions(content: str, extension: str):
    rows = []
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
        raise SkipVideo("Subtitle track has no usable timed text.")
    return cues


def caption_cards(cues, start, end, chars_per_line=18):
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


def write_clip_subtitles(cues, start, end, directory: Path, width=1080, height=1920):
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
        event = pysubs2.SSAEvent(start=left, end=right)
        event.plaintext = text
        subs.append(event)
    if not subs:
        raise SkipVideo("Selected interval contains no subtitles.")
    subs.save(str(directory / "captions.ass"), encoding="utf-8")
