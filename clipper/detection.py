"""Decode video samples and select a working face-detection backend."""

import subprocess
import tempfile
import threading
import time
from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path
from statistics import median

import cv2
import numpy as np

from .models import Clip, ClipsError


def sample_frames(
    source: Path, clip: Clip
) -> Generator[tuple[float, cv2.typing.MatLike], None, None]:
    filters = (
        "fps=5/2:start_time=0:round=up,scale=trunc(iw*sar/2)*2:ih,setsar=1,"
        "scale=640:640:force_original_aspect_ratio=decrease:force_divisible_by=2"
    )
    args = [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        str(clip.start),
        "-i",
        str(source.resolve()),
        "-t",
        str(clip.duration),
        "-an",
        "-sn",
        "-vf",
        filters,
        "-c:v",
        "ppm",
        "-pix_fmt",
        "rgb24",
        "-f",
        "image2pipe",
        "pipe:1",
    ]
    try:
        with (
            tempfile.TemporaryFile(mode="w+") as errors,
            subprocess.Popen(
                args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=errors
            ) as process,
        ):
            if process.stdout is None:
                process.kill()
                raise ClipsError("FFmpeg did not open its frame pipe.")
            timer = threading.Timer(max(180, clip.duration * 30), process.kill)
            timer.daemon = True
            timer.start()
            try:
                index = 0
                while header := process.stdout.readline():
                    if header != b"P6\n":
                        raise ClipsError("FFmpeg returned an invalid frame header.")
                    width, height = map(int, process.stdout.readline().split())
                    if process.stdout.readline() != b"255\n" or not (
                        0 < width <= 640 and 0 < height <= 640
                    ):
                        raise ClipsError("FFmpeg returned an unsupported frame format.")
                    pixels = process.stdout.read(width * height * 3)
                    if len(pixels) != width * height * 3:
                        raise ClipsError("Video decoding stopped partway through a frame.")
                    frame = np.frombuffer(pixels, dtype=np.uint8).reshape(height, width, 3)
                    yield index * 0.4, cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                    index += 1
                if process.wait():
                    errors.seek(0)
                    detail = errors.read()[-1500:].strip() or "Decoding timed out."
                    raise ClipsError("Could not decode frames for face tracking: " + detail)
            finally:
                timer.cancel()
                if process.poll() is None:
                    process.kill()
                process.wait()
    except (OSError, ValueError) as error:
        raise ClipsError("Could not read video frames for face tracking.") from error


@dataclass
class Detector:
    model: cv2.FaceDetectorYN
    label: str
    milliseconds: float = 0

    def detect(self, frame: cv2.typing.MatLike) -> cv2.typing.MatLike | None:
        self.model.setInputSize((frame.shape[1], frame.shape[0]))
        _, faces = self.model.detect(frame)
        return faces


def gpu_targets() -> list[tuple[int, int, str]]:
    cv2.ocl.setUseOpenCL(True)
    candidates = [
        (cv2.dnn.DNN_BACKEND_OPENCV, cv2.dnn.DNN_TARGET_OPENCL, "GPU · OpenCL"),
        (cv2.dnn.DNN_BACKEND_CUDA, cv2.dnn.DNN_TARGET_CUDA, "GPU · CUDA"),
    ]
    return [
        (backend, target, label)
        for backend, target, label in candidates
        if target in cv2.dnn.getAvailableTargets(backend)
    ]


def measure(detector: Detector, frame: cv2.typing.MatLike) -> cv2.typing.MatLike | None:
    faces = detector.detect(frame)
    timings = []
    for _ in range(5):
        started = time.perf_counter()
        detector.detect(frame)
        timings.append(time.perf_counter() - started)
    detector.milliseconds = median(timings) * 1000
    return faces


def choose_detector(frame: cv2.typing.MatLike) -> Detector:
    path = str(Path(__file__).with_name("assets") / "face_detection_yunet.onnx")

    def create(backend: int, target: int, label: str) -> Detector:
        return Detector(
            cv2.FaceDetectorYN.create(
                path, "", (frame.shape[1], frame.shape[0]), 0.75, 0.3, 5000, backend, target
            ),
            label,
        )

    best = create(cv2.dnn.DNN_BACKEND_OPENCV, cv2.dnn.DNN_TARGET_CPU, "CPU")
    candidates = gpu_targets()
    if not candidates:
        return best
    reference = measure(best, frame)
    for backend, target, label in candidates:
        try:
            candidate = create(backend, target, label)
            faces = measure(candidate, frame)
            if (faces is None) != (reference is None):
                continue
            if faces is not None and reference is not None:
                if len(faces) != len(reference):
                    continue
                if not all(
                    any(np.allclose(face[:4], other[:4], atol=3, rtol=0.03) for other in reference)
                    for face in faces
                ):
                    continue
            if candidate.milliseconds < best.milliseconds * 0.9:
                best = candidate
        except cv2.error:
            continue
    return best


def benchmark() -> tuple[Detector, bool]:
    frame = np.zeros((360, 640, 3), dtype=np.uint8)
    detector = choose_detector(frame)
    if not detector.milliseconds:
        measure(detector, frame)
    return detector, bool(gpu_targets())
