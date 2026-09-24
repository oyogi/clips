"""Sample a clip's visible faces and smoothly move FFmpeg's crop window."""

import math
from pathlib import Path

from .models import ClipsError


def face_commands(source, clip, width, height, destination, progress):
    import cv2

    model = Path(__file__).with_name("assets") / "face_detection_yunet.onnx"
    capture = cv2.VideoCapture(str(source))
    points, detections = [], 0
    try:
        if not capture.isOpened():
            raise ClipsError("Could not open the source for face tracking.")
        detector = cv2.FaceDetectorYN.create(str(model), "", (320, 320), 0.75, 0.3, 5000)
        fps = capture.get(cv2.CAP_PROP_FPS)
        if not math.isfinite(fps) or fps <= 0:
            fps = 30
        capture.set(cv2.CAP_PROP_POS_MSEC, clip.start * 1000)
        next_sample, last_seen = 0.0, -10.0
        previous, previous_gray = None, None
        smooth = (0.5, 0.5)
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
            frame = cv2.resize(frame, (max(32, round(frame.shape[1] * scale)),
                                       max(32, round(frame.shape[0] * scale))))
            frame_h, frame_w = frame.shape[:2]
            gray = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (32, 18))
            cut = previous_gray is not None and cv2.absdiff(gray, previous_gray).mean() > 40
            previous_gray = gray
            if cut:
                previous, last_seen = None, -10.0
            detector.setInputSize((frame_w, frame_h))
            _, faces = detector.detect(frame)
            if faces is not None and len(faces):
                candidates = [
                    ((float(face[0] + face[2] / 2) / frame_w,
                      float(face[1] + face[3] * 0.6) / frame_h), float(face[2] * face[3]))
                    for face in faces
                ]

                def score(candidate):
                    center, area = candidate
                    distance = math.dist(center, previous) if previous else 0
                    return area / (1 + distance * 8)

                target, _ = max(candidates, key=score)
                previous, last_seen = target, timestamp
                detections += 1
            else:
                # Hold briefly through a missed detection, then return to center.
                target = previous if previous and timestamp - last_seen <= 1 else (0.5, 0.5)
                if timestamp - last_seen > 1:
                    previous = None
            if not points or cut:
                smooth = target
            else:
                smooth = tuple(old + (new - old) * 0.55 for old, new in zip(smooth, target))
            points.append((timestamp, *smooth))
            if progress:
                progress("Tracking faces", min(1.0, timestamp / clip.duration))
    except cv2.error as error:
        raise ClipsError(f"Face tracking failed: {error}") from error
    finally:
        capture.release()

    if not detections:
        return False
    points[0] = (0.0, *points[0][1:])
    points.append((clip.duration + 1, *points[-1][1:]))
    commands = []
    for current, following in zip(points, points[1:]):
        start, x, y = current
        end, next_x, next_y = following
        # sendcmd evaluates TI from 0 to 1 for every frame in the interval.
        # Coordinates stay proportional after scaling, including non-square pixels.
        x_expr = f"clip(({x:.6f}+({next_x-x:.6f})*TI)*W-{width/2},0,W-{width})"
        y_expr = f"clip(({y:.6f}+({next_y-y:.6f})*TI)*H-{height/2},0,H-{height})"
        commands.append(
            f"{start:.6f}-{end:.6f} [expr] crop@face x '{x_expr}', "
            f"[expr] crop@face y '{y_expr}';"
        )
    destination.write_text("\n".join(commands) + "\n", encoding="utf-8")
    return True
