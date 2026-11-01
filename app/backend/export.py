"""Image and video export without UI state.

Rules carried over from Studio's Qt fixes:
- results are rendered for the export itself, never taken from the preview;
- compare/mask views are never part of an export;
- any frame failure aborts the export instead of writing the source frame;
- output is written to a partial file and published only after validation.
"""
from __future__ import annotations

import bisect
import concurrent.futures as futures
import copy
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from .host import HeadlessHost, RenderOptions
from .media import FrameReader, MediaInfo, MediaError, input_height, resize_to_height


class ExportCancelled(Exception):
    pass


class ExportFailed(RuntimeError):
    pass


@dataclass
class ExportRequest:
    output_dir: str
    start: int = 0
    end: int | None = None  # inclusive
    file_name: str | None = None
    # Several (start, end) ranges joined into one output, like Fusion job segments.
    ranges: list[tuple[int, int]] | None = None


def normalise_ranges(info_frames: int, request: "ExportRequest") -> list[tuple[int, int]]:
    raw = request.ranges or [(request.start, info_frames - 1 if request.end is None else request.end)]
    ranges = []
    for start, end in sorted((max(0, int(a)), min(int(b), info_frames - 1)) for a, b in raw):
        if end < start:
            continue
        if ranges and start <= ranges[-1][1] + 1:
            ranges[-1] = (ranges[-1][0], max(ranges[-1][1], end))
        else:
            ranges.append((start, end))
    return ranges


Progress = Callable[[int, int], None]


def _output_path(info: MediaInfo, request: ExportRequest, kind: str, jpeg: bool) -> Path:
    from app.helpers.miscellaneous import get_output_file_path

    media_type = "video" if kind == "video" else ("jpegimage" if jpeg else "image")
    path = Path(get_output_file_path(info.path, request.output_dir, media_type=media_type,
                                     output_file_name=request.file_name))
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _partial(path: Path) -> Path:
    return path.with_name(f".{path.stem}.partial{path.suffix}")


def export_image(host: HeadlessHost, reader: FrameReader, request: ExportRequest,
                 frame_index: int = 0) -> Path:
    from PIL import Image

    frame = resize_to_height(reader.read(frame_index), input_height(host.control))
    result = host.render(frame, frame_index, RenderOptions(swap=host.swapfacesButton.isChecked(),
                                                           edit=host.editFacesButton.isChecked()))
    jpeg = bool(host.control.get("ImageFormatToggle", False))
    final = _output_path(reader.info, request, "image", jpeg)
    partial = _partial(final)
    image = Image.fromarray(np.ascontiguousarray(result[..., ::-1]))
    try:
        if jpeg:
            image.save(partial, "JPEG", quality=95)
        else:
            image.save(partial, "PNG")
        check = cv2.imread(str(partial))
        if check is None or check.shape[:2] != result.shape[:2]:
            raise ExportFailed("导出文件校验失败")
        os.replace(partial, final)
    finally:
        partial.unlink(missing_ok=True)
    return final


class MarkerTimeline:
    """Per-frame state from Fusion markers: the last marker at or before a frame wins.

    As in Fusion's media pipeline, a marker replaces face parameters and rebuilds
    global control from defaults plus the marker's saved control values.
    """

    KEEP = ("StudioStrictProcessing", "StudioTempDir", "StudioSoftwareEncode", "OutputMediaFolder")

    def __init__(self, markers: dict, base: tuple[dict, dict], control_defaults: dict):
        self.frames = sorted(int(k) for k in markers)
        self.markers = {int(k): v for k, v in markers.items()}
        self.base = base
        self.control_defaults = control_defaults

    def state(self, frame: int) -> tuple[dict, dict]:
        i = bisect.bisect_right(self.frames, frame) - 1
        if i < 0:
            return copy.deepcopy(self.base[0]), copy.deepcopy(self.base[1])
        data = self.markers[self.frames[i]]
        control = copy.deepcopy(self.control_defaults)
        control.update(copy.deepcopy(data.get("control") or {}))
        for key in self.KEEP:
            if key in self.base[1]:
                control[key] = self.base[1][key]
        return copy.deepcopy(data["parameters"]), control


def _count_frames(path: Path) -> int:
    import subprocess, json

    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
                          "-show_entries", "stream=nb_read_frames", "-of", "json", str(path)],
                         capture_output=True, text=True, timeout=600)
    data = json.loads(out.stdout or "{}")
    streams = data.get("streams") or [{}]
    return int(streams[0].get("nb_read_frames") or 0)


def export_video(host: HeadlessHost, info: MediaInfo, request: ExportRequest,
                 cancel: threading.Event, progress: Progress = lambda done, total: None) -> Path:
    from app.processors.video_utils.video_encoding import FFmpegEncoder

    ranges = normalise_ranges(info.frames, request)
    if not ranges:
        raise ExportFailed("导出范围无效")
    src_fps = info.fps or 25.0
    cap = float(host.control.get("OutputMaxFpsSlider", 30) or 0) if host.control.get("OutputFpsCapEnableToggle") else 0.0
    if cap and src_fps > cap:
        # Fusion's output FPS cap: sample source frames at the capped rate; duration is unchanged.
        indices = []
        for a, b in ranges:
            count = max(1, int(round((b - a + 1) * cap / src_fps)))
            indices += [min(b, a + int(round(k * src_fps / cap))) for k in range(count)]
        out_fps = cap
    else:
        indices = [i for a, b in ranges for i in range(a, b + 1)]
        out_fps = src_fps
    total = len(indices)
    start = indices[0]
    target_height = input_height(host.control)
    final = _output_path(info, request, "video", False)
    partial = _partial(final)
    video_only = partial.with_name(partial.stem + ".video" + partial.suffix)
    partial.unlink(missing_ok=True)
    video_only.unlink(missing_ok=True)

    base = host.snapshot()
    timeline = MarkerTimeline(copy.deepcopy(host.markers), base, dict(host.schema["defaults"]["global"]))
    options = RenderOptions(swap=host.swapfacesButton.isChecked(), edit=host.editFacesButton.isChecked())
    control = dict(base[1])
    threads = max(1, int(control.get("nThreadsSlider", 2) or 1))

    reader = FrameReader(info)
    first = resize_to_height(reader.read(start), target_height)
    probe_frame = host.render(first, start, options, state=timeline.state(start))
    height, width = probe_frame.shape[:2]

    encoder = FFmpegEncoder()
    fps = out_fps
    # Video first, audio muxed afterwards: `-shortest` in a single pass can drop
    # the final reordered frames when AAC ends first (fixed earlier in Studio).
    started = encoder.start_process(str(video_only), width, height, fps, control, media_path=info.path)
    if not started:
        raise ExportFailed("无法启动视频编码器（FFmpeg）")

    local = threading.local()

    def render(index: int, frame: np.ndarray) -> np.ndarray:
        if cancel.is_set():
            raise ExportCancelled()
        worker = getattr(local, "worker", None)
        if worker is None:
            worker = local.worker = host.new_worker()
        result = host.render(frame, index, options, worker=worker, state=timeline.state(index), stop=cancel)
        if result.shape[:2] != (height, width):
            raise ExportFailed(f"第 {index + 1} 帧尺寸异常")
        return result

    error: BaseException | None = None
    written = 0
    try:
        if not encoder.write_frame(probe_frame):
            raise ExportFailed("写入视频失败")
        written = 1
        progress(written, total)
        pending: list[futures.Future] = []
        with futures.ThreadPoolExecutor(max_workers=threads, thread_name_prefix="export") as pool:
            queue = iter(indices[1:])
            exhausted = False
            while written < total:
                while not exhausted and len(pending) < threads * 2:
                    if cancel.is_set():
                        raise ExportCancelled()
                    index = next(queue, None)
                    if index is None:
                        exhausted = True
                        break
                    frame = resize_to_height(reader.read(index), target_height)
                    pending.append(pool.submit(render, index, frame))
                result = pending.pop(0).result()
                if cancel.is_set():
                    raise ExportCancelled()
                if not encoder.write_frame(result):
                    raise ExportFailed("写入视频失败")
                written += 1
                progress(written, total)
    except BaseException as exc:  # includes cancellation
        error = exc
        cancel.set()
    finally:
        reader.close()
        if error is None:
            encoder.close_process()
        else:
            process = encoder.recording_sp
            if process is not None:
                try:
                    if process.stdin:
                        process.stdin.close()
                except OSError:
                    pass
                process.kill()
                process.wait(timeout=10)
    if error is not None:
        partial.unlink(missing_ok=True)
        video_only.unlink(missing_ok=True)
        if isinstance(error, ExportCancelled):
            raise error
        if isinstance(error, (ExportFailed, MediaError)):
            raise error
        raise ExportFailed(str(error) or error.__class__.__name__) from error

    try:
        if not video_only.is_file():
            raise ExportFailed("没有生成视频文件")
        _mux_audio(video_only, info, ranges, partial)
        frames = _count_frames(partial)
        if frames != total:
            raise ExportFailed(f"输出帧数 {frames}，应为 {total}")
        os.replace(partial, final)
    finally:
        partial.unlink(missing_ok=True)
        video_only.unlink(missing_ok=True)
    return final


def _mux_audio(video: Path, info: MediaInfo, ranges: list[tuple[int, int]], output: Path) -> None:
    import subprocess

    if not info.has_audio:
        os.replace(video, output)
        return
    fps = info.fps or 25.0
    args = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(video), "-i", info.path]
    whole = len(ranges) == 1 and ranges[0] == (0, info.frames - 1)
    if whole:
        args += ["-map", "0:v:0", "-map", "1:a:0?"]
    else:
        # Cut the source audio to the same frame ranges and join them in order.
        parts = [f"[1:a:0]atrim=start={a / fps:.6f}:end={(b + 1) / fps:.6f},asetpts=PTS-STARTPTS[a{i}]"
                 for i, (a, b) in enumerate(ranges)]
        joined = "".join(f"[a{i}]" for i in range(len(ranges)))
        graph = ";".join(parts) + f";{joined}concat=n={len(ranges)}:v=0:a=1[aout]"
        args += ["-filter_complex", graph, "-map", "0:v:0", "-map", "[aout]"]
    args += ["-c:v", "copy", "-c:a", "aac", str(output)]
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode:
        raise ExportFailed("合并音频失败：" + (result.stderr.strip().splitlines() or ["未知错误"])[-1])
