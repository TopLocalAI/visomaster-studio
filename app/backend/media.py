"""Media inspection and frame access without UI state."""
from __future__ import annotations

import json
import subprocess
import threading
from dataclasses import dataclass, asdict
from pathlib import Path

import cv2
import numpy as np

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".jfif"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".mkv", ".avi", ".webm", ".wmv", ".mpg", ".mpeg", ".flv", ".ts"}


class MediaError(ValueError):
    pass


def media_kind(path: str | Path) -> str | None:
    suffix = Path(path).suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        return "image"
    if suffix in VIDEO_EXTENSIONS:
        return "video"
    return None


@dataclass
class MediaInfo:
    path: str
    kind: str
    width: int
    height: int
    fps: float = 0.0
    frames: int = 1
    duration: float = 0.0
    has_audio: bool = False
    rotation: int = 0

    def to_json(self) -> dict:
        return asdict(self)


def _ffprobe(path: Path) -> dict:
    try:
        result = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
                                capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise MediaError("无法读取视频信息") from exc
    if result.returncode:
        raise MediaError("无法读取视频")
    return json.loads(result.stdout or "{}")


def _rate(text: str | None) -> float:
    if not text or text in ("0/0", "0"):
        return 0.0
    if "/" in text:
        num, den = text.split("/", 1)
        return float(num) / float(den) if float(den) else 0.0
    return float(text)


def read_image(path: str | Path) -> np.ndarray:
    from app.helpers.miscellaneous import read_image_file

    frame = read_image_file(str(path))
    if frame is None:
        raise MediaError("无法打开图片")
    return frame


def probe(path: str | Path) -> MediaInfo:
    path = Path(path)
    if not path.is_file():
        raise MediaError("文件不存在")
    kind = media_kind(path)
    if kind == "image":
        frame = read_image(path)
        h, w = frame.shape[:2]
        return MediaInfo(str(path), "image", w, h)
    if kind != "video":
        raise MediaError("不支持的文件类型")
    from app.helpers.miscellaneous import get_video_rotation

    data = _ffprobe(path)
    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    if not video:
        raise MediaError("没有视频画面")
    audio = any(s.get("codec_type") == "audio" for s in data.get("streams", []))
    capture = cv2.VideoCapture(str(path))
    try:
        if not capture.isOpened():
            raise MediaError("无法打开视频")
        frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = capture.get(cv2.CAP_PROP_FPS) or _rate(video.get("avg_frame_rate")) or _rate(video.get("r_frame_rate"))
        rotation = get_video_rotation(str(path))
        ok, frame = capture.read()
        if not ok or frame is None:
            raise MediaError("无法解码视频")
        h, w = frame.shape[:2]
        if rotation in (90, 270):
            w, h = h, w
    finally:
        capture.release()
    duration = float(video.get("duration") or data.get("format", {}).get("duration") or (frames / fps if fps else 0))
    return MediaInfo(str(path), "video", w, h, float(fps), max(frames, 1), duration, audio, rotation)


def input_height(control: dict) -> int | None:
    """Fusion's global input resize (e.g. "720p"), or None when off."""
    if not control.get("GlobalInputResizeToggle", False):
        return None
    try:
        return int(str(control.get("GlobalInputResizeSizeSelection", "720p")).rstrip("p"))
    except ValueError:
        return None


def resize_to_height(frame: np.ndarray, height: int | None) -> np.ndarray:
    """Same rule as Fusion's read_frame: keep aspect, even width, Lanczos up / area down."""
    if not height or frame.shape[0] == height:
        return frame
    h, w = frame.shape[:2]
    width = int(height * w / h)
    width += width % 2
    method = cv2.INTER_LANCZOS4 if height > h else cv2.INTER_AREA
    return cv2.resize(frame, (width, height), interpolation=method)


class FrameReader:
    """Thread-safe random access for previews; sequential reads for export."""

    def __init__(self, info: MediaInfo):
        self.info = info
        self.lock = threading.Lock()
        self.capture = None
        self.position = -1
        self.image = read_image(info.path) if info.kind == "image" else None

    def read(self, index: int = 0) -> np.ndarray:
        if self.image is not None:
            return self.image.copy()
        from app.helpers.miscellaneous import read_frame

        index = max(0, min(int(index), self.info.frames - 1))
        with self.lock:
            if self.capture is None:
                self.capture = cv2.VideoCapture(self.info.path)
                self.position = 0
            if index != self.position:
                self.capture.set(cv2.CAP_PROP_POS_FRAMES, index)
            ok, frame = read_frame(self.capture, self.info.rotation)
            if not ok or frame is None:
                self.position = -1
                raise MediaError(f"无法读取第 {index + 1} 帧")
            self.position = index + 1
            return frame

    def close(self) -> None:
        with self.lock:
            if self.capture is not None:
                self.capture.release()
                self.capture = None
