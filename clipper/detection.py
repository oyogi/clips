"""Select a working face-detection backend using measured inference latency."""

import time
from dataclasses import dataclass
from pathlib import Path
from statistics import median

import cv2
import numpy as np


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
