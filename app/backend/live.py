"""Live camera processing: capture -> Fusion pipeline -> preview stream / virtual camera.

The source is a camera index, or a video file (looped) for testing without a
camera. Faces and parameters are read live, so edits apply to the next frame.
Recording a live session is not provided (Fusion does not record webcams either).
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable

import cv2
import numpy as np

from .host import HeadlessHost, ProcessingError, RenderOptions


@dataclass
class LiveStats:
    running: bool = False
    source: str = ""
    width: int = 0
    height: int = 0
    fps: float = 0.0
    frames: int = 0
    error: str = ""
    virtual_camera: str = ""


class LiveSession:
    def __init__(self, host: HeadlessHost, engine_lock: threading.Lock, emit: Callable[[str, dict], None]):
        self.host = host
        self.engine_lock = engine_lock
        self.emit = emit
        self.stats = LiveStats()
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.frame_ready = threading.Condition()
        self.jpeg: bytes = b""
        self.raw: np.ndarray | None = None
        self.serial = 0
        self.process = True
        self.virtcam = None

    # ------------------------------------------------------------- control
    def start(self, source: str | int, process: bool = True) -> LiveStats:
        self.stop()
        self.stop_event.clear()
        self.process = process
        self.stats = LiveStats(running=True, source=str(source))
        self.thread = threading.Thread(target=self._loop, args=(source,), name="live", daemon=True)
        self.thread.start()
        return self.stats

    def stop(self) -> LiveStats:
        self.stop_event.set()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=5)
        self.thread = None
        self._close_virtcam()
        self.stats.running = False
        return self.stats

    # ------------------------------------------------------------- capture
    def _open(self, source: str | int):
        from app.ui.widgets.settings_layout_data import CAMERA_BACKENDS

        control = self.host.control
        if isinstance(source, int) or str(source).isdigit():
            backend = CAMERA_BACKENDS.get(str(control.get("WebcamBackendSelection", "Default")), cv2.CAP_ANY)
            cap = cv2.VideoCapture(int(source), backend)
            res = str(control.get("WebcamMaxResSelection", "1280x720"))
            if "x" in res:
                w, h = (int(v) for v in res.split("x", 1))
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
            cap.set(cv2.CAP_PROP_FPS, float(control.get("WebCamMaxFPSSelection", 30)))
            looping = False
        else:
            cap = cv2.VideoCapture(str(source))
            looping = True
        if not cap or not cap.isOpened():
            raise RuntimeError("无法打开摄像头。请在系统设置中允许 VisoMaster Studio 使用摄像头")
        return cap, looping

    def _loop(self, source: str | int) -> None:
        try:
            cap, looping = self._open(source)
        except Exception as exc:  # noqa: BLE001
            self.stats.running, self.stats.error = False, str(exc)
            self.emit("live", self._stats_json())
            return
        worker = None
        times: list[float] = []
        last_emit = 0.0
        file_fps = cap.get(cv2.CAP_PROP_FPS) if looping else 0
        try:
            while not self.stop_event.is_set():
                started = time.perf_counter()
                ok, frame = cap.read()
                if not ok or frame is None:
                    if looping:
                        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        continue
                    raise RuntimeError("摄像头没有画面")
                self.raw = frame
                out = frame
                if self.process and self.host.target_faces:
                    if worker is None:
                        worker = self.host.new_worker()  # one worker keeps tracking state between frames
                    options = RenderOptions(swap=self.host.swapfacesButton.isChecked(), edit=self.host.editFacesButton.isChecked())
                    with self.engine_lock:
                        out = self.host.render(frame, self.stats.frames, options, worker=worker)
                self._publish(out)
                self._virtual_camera(out)
                times.append(time.perf_counter())
                times = times[-30:]
                if len(times) > 1:
                    self.stats.fps = round((len(times) - 1) / (times[-1] - times[0]), 1)
                self.stats.frames += 1
                self.stats.height, self.stats.width = out.shape[:2]
                if self.stats.frames == 1 or time.perf_counter() - last_emit > 1.0:
                    last_emit = time.perf_counter()
                    self.emit("live", self._stats_json())
                if looping and file_fps > 0:
                    # Pace file sources like a camera so the stream looks real-time.
                    delay = 1.0 / file_fps - (time.perf_counter() - started)
                    if delay > 0:
                        self.stop_event.wait(delay)
        except ProcessingError as exc:
            self.stats.error = f"处理失败：{exc}"
        except Exception as exc:  # noqa: BLE001
            self.stats.error = str(exc)
        finally:
            cap.release()
            self._close_virtcam()
            self.stats.running = False
            self.emit("live", self._stats_json())

    def _publish(self, frame: np.ndarray) -> None:
        ok, data = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if not ok:
            return
        with self.frame_ready:
            self.jpeg = data.tobytes()
            self.serial += 1
            self.frame_ready.notify_all()

    def wait_frame(self, last: int, timeout: float = 2.0) -> tuple[int, bytes]:
        with self.frame_ready:
            self.frame_ready.wait_for(lambda: self.serial != last or self.stop_event.is_set(), timeout=timeout)
            return self.serial, self.jpeg

    # ------------------------------------------------------- virtual camera
    def _virtual_camera(self, frame: np.ndarray) -> None:
        control = self.host.control
        if not control.get("SendVirtCamFramesEnableToggle", False):
            self._close_virtcam()
            return
        h, w = frame.shape[:2]
        if self.virtcam is not None and (self.virtcam.width != w or self.virtcam.height != h):
            self._close_virtcam()
        if self.virtcam is None:
            try:
                import pyvirtualcam

                fps = int(float(control.get("WebCamMaxFPSSelection", 30)))
                self.virtcam = pyvirtualcam.Camera(width=w, height=h, fps=fps, fmt=pyvirtualcam.PixelFormat.BGR,
                                                   backend=str(control.get("VirtCamBackendSelection", "obs")))
                self.stats.virtual_camera = self.virtcam.device
            except Exception as exc:  # noqa: BLE001
                control["SendVirtCamFramesEnableToggle"] = False
                self.stats.virtual_camera = ""
                self.stats.error = f"虚拟摄像头不可用：{exc}"
                self.emit("live", self._stats_json())
                return
        try:
            self.virtcam.send(np.ascontiguousarray(frame))
        except Exception as exc:  # noqa: BLE001
            self.stats.error = f"虚拟摄像头输出失败：{exc}"
            self._close_virtcam()

    def _close_virtcam(self) -> None:
        if self.virtcam is not None:
            try:
                self.virtcam.close()
            except Exception:  # noqa: BLE001
                pass
            self.virtcam = None
            self.stats.virtual_camera = ""

    def _stats_json(self) -> dict:
        return dict(self.stats.__dict__)
