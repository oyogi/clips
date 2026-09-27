"""Detect visible faces, stabilize framing changes, and drive FFmpeg crops."""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Literal

from .models import Clip, ClipsError, ProgressCallback

type Point = tuple[float, float]
type View = Literal["black", "face", "split"]


@dataclass(frozen=True)
class Face:
    center: Point
    area: float


@dataclass(frozen=True)
class Sample:
    time: float
    faces: tuple[Face, ...]
    cut: bool = False

    @property
    def view(self) -> View:
        return "face" if len(self.faces) == 1 else "split" if len(self.faces) == 2 else "black"


@dataclass(frozen=True)
class Scene:
    start: float
    end: float
    view: View


@dataclass(frozen=True)
class FramingPlan:
    scenes: list[Scene]
    samples: list[Sample]

    @property
    def split_ranges(self) -> list[tuple[float, float]]:
        return [(scene.start, scene.end) for scene in self.scenes if scene.view == "split"]

    @property
    def summary(self) -> str:
        labels = {"black": "full picture", "face": "face tracking", "split": "two-person split"}
        return "Faces · " + ", ".join(
            labels[view] for view in dict.fromkeys(s.view for s in self.scenes)
        )


@dataclass(frozen=True)
class FaceScan:
    samples: list[Sample]
    engine: str


def sample_faces(source: Path, clip: Clip, progress: ProgressCallback | None) -> FaceScan:
    import cv2

    from .detection import Detector, choose_detector

    capture = cv2.VideoCapture(str(source))
    samples = []
    detector: Detector | None = None
    try:
        if not capture.isOpened():
            raise ClipsError("Could not open the source for face tracking.")
        fps = capture.get(cv2.CAP_PROP_FPS)
        if not math.isfinite(fps) or fps <= 0:
            fps = 30
        capture.set(cv2.CAP_PROP_POS_MSEC, clip.start * 1000)
        next_sample = 0.0
        previous_gray: cv2.typing.MatLike | None = None
        while capture.grab():
            timestamp = capture.get(cv2.CAP_PROP_POS_MSEC) / 1000 - clip.start
            if not math.isfinite(timestamp) or timestamp < -0.1:
                timestamp = (capture.get(cv2.CAP_PROP_POS_FRAMES) - 1) / fps - clip.start
            if timestamp >= clip.duration:
                break
            if timestamp + 0.001 < next_sample:
                continue
            ok, frame = capture.retrieve()
            if not ok:
                break
            timestamp = max(0.0, timestamp)
            next_sample = timestamp + 0.4
            scale = min(640 / frame.shape[1], 640 / frame.shape[0], 1.0)
            frame = cv2.resize(
                frame,
                (max(32, round(frame.shape[1] * scale)), max(32, round(frame.shape[0] * scale))),
            )
            frame_h, frame_w = frame.shape[:2]
            gray = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (32, 18))
            cut = previous_gray is not None and bool(cv2.absdiff(gray, previous_gray).mean() > 40)
            previous_gray = gray
            if detector is None:
                detector = choose_detector(frame)
            try:
                detected = detector.detect(frame)
            except cv2.error:
                if detector.label.startswith("CPU"):
                    raise
                model = Path(__file__).with_name("assets") / "face_detection_yunet.onnx"
                detector = Detector(
                    cv2.FaceDetectorYN.create(str(model), "", (frame_w, frame_h), 0.75, 0.3, 5000),
                    "CPU (GPU fallback)",
                )
                detected = detector.detect(frame)
            faces = (
                tuple(
                    Face(
                        (
                            float(face[0] + face[2] / 2) / frame_w,
                            float(face[1] + face[3] * 0.6) / frame_h,
                        ),
                        float(face[2] * face[3]),
                    )
                    for face in detected
                )
                if detected is not None
                else ()
            )
            samples.append(Sample(timestamp, faces, cut))
            if progress:
                progress(f"Faces · {detector.label}", min(1.0, timestamp / clip.duration))
    except cv2.error as error:
        raise ClipsError("Face detection failed; try Black framing.") from error
    finally:
        capture.release()
    if not samples or detector is None:
        raise ClipsError("Could not read frames for face tracking.")
    samples[0] = Sample(0, samples[0].faces, True)
    return FaceScan(samples, detector.label)


def plan_framing(samples: list[Sample], duration: float) -> FramingPlan:
    if not samples:
        return FramingPlan([Scene(0, duration, "black")], [])
    confirmation, minimum_hold = 2.0, 4.0
    opening = [sample.view for sample in samples if sample.time < confirmation]
    initial = max(opening, key=opening.count)
    if opening.count(initial) < len(opening) * 0.75:
        initial = "black"
    changes: list[tuple[float, View]] = [(0, initial)]
    candidate, since = initial, 0.0
    for sample in samples:
        if sample.view != candidate:
            candidate, since = sample.view, sample.time
        if candidate == changes[-1][1] or sample.time - since < confirmation - 0.001:
            continue
        start = max(since, changes[-1][0] + minimum_hold)
        if start <= sample.time and duration - start >= minimum_hold:
            changes.append((start, candidate))
    scenes = [
        Scene(start, changes[index + 1][0] if index + 1 < len(changes) else duration, view)
        for index, (start, view) in enumerate(changes)
    ]
    return FramingPlan(scenes, samples)


def crop_tracks(samples: Sequence[Sample]) -> tuple[list[Point], list[Point], list[Point]]:
    single: list[Point] = []
    top: list[Point] = []
    bottom: list[Point] = []
    last_seen = -10.0
    center = (0.5, 0.5)
    target = center
    pair = (center, center)
    for sample in samples:
        if sample.cut and sample.faces:
            target = center
        if sample.faces:
            previous = target
            target = max(
                sample.faces,
                key=lambda face: face.area / (1 + math.dist(face.center, previous) * 8),
            ).center
            last_seen = sample.time
        elif sample.time - last_seen > 3:
            target = center
        if len(sample.faces) == 2:
            ordered = sorted((face.center for face in sample.faces), key=lambda point: point[0])
            a, b = ordered
            if (
                not sample.cut
                and top
                and math.dist(a, pair[1]) + math.dist(b, pair[0])
                < math.dist(a, pair[0]) + math.dist(b, pair[1])
            ):
                a, b = b, a
            pair = a, b
        for track, point in zip((single, top, bottom), (target, *pair), strict=True):
            if not track or sample.cut:
                track.append(point)
            else:
                track.append(
                    (track[-1][0] * 0.7 + point[0] * 0.3, track[-1][1] * 0.7 + point[1] * 0.3)
                )
    return single, top, bottom


def write_commands(
    plan: FramingPlan, directory: Path, width: int, height: int, duration: float
) -> None:
    if not plan.samples:
        return
    tracks = crop_tracks(plan.samples)
    for name, track, crop_height in zip(
        ("face", "top", "bottom"), tracks, (height, height // 2, height // 2), strict=True
    ):
        points = [(sample.time, *point) for sample, point in zip(plan.samples, track, strict=True)]
        points.append((duration + 1, *track[-1]))
        commands = []
        for index, (current, following) in enumerate(pairwise(points)):
            start, x, y = current
            end, next_x, next_y = following
            if index + 1 < len(plan.samples) and plan.samples[index + 1].cut:
                next_x, next_y = x, y
            x_expr = f"clip(({x:.6f}+({next_x - x:.6f})*TI)*W-{width / 2},0,W-{width})"
            y_expr = f"clip(({y:.6f}+({next_y - y:.6f})*TI)*H-{crop_height / 2},0,H-{crop_height})"
            commands.append(
                f"{start:.6f}-{end:.6f} [expr] crop@{name} x '{x_expr}', [expr] crop@{name} y '{y_expr}';"
            )
        (directory / f"{name}.cmd").write_text("\n".join(commands) + "\n", encoding="utf-8")
