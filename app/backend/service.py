"""Workspace service: the UI-independent API used by the desktop frontend.

All methods are synchronous and thread-safe; the server runs them on worker
threads and forwards `emit` events to connected clients. Long work (model
downloads, exports) runs as jobs with progress, cancellation and a final state.
"""
from __future__ import annotations

import copy
import itertools
import json
import os
import platform
import shutil
import subprocess
import sys
import threading
import time
import traceback
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import cv2
import numpy as np

VERSION = "0.3.0-dev"

Emit = Callable[[str, dict], None]


class ApiError(Exception):
    """Errors shown to the user: short, actionable text."""

    def __init__(self, message: str, code: str = "error"):
        super().__init__(message)
        self.code = code


def data_root() -> Path:
    from app.studio.config import data_root as root

    return root()


class ImageStore:
    """Small in-memory cache of encoded images served to the frontend."""

    def __init__(self, limit: int = 64):
        self.items: OrderedDict[str, tuple[str, bytes]] = OrderedDict()
        self.limit = limit
        self.lock = threading.Lock()

    def put(self, frame_bgr: np.ndarray, fmt: str = ".jpg", quality: int = 92, key: str | None = None) -> str:
        params = [cv2.IMWRITE_JPEG_QUALITY, quality] if fmt == ".jpg" else []
        ok, data = cv2.imencode(fmt, frame_bgr, params)
        if not ok:
            raise ApiError("图像编码失败")
        key = key or uuid.uuid4().hex
        mime = "image/jpeg" if fmt == ".jpg" else "image/png"
        with self.lock:
            self.items[key] = (mime, data.tobytes())
            self.items.move_to_end(key)
            while len(self.items) > self.limit:
                self.items.popitem(last=False)
        return key

    def get(self, key: str) -> tuple[str, bytes] | None:
        with self.lock:
            return self.items.get(key)


@dataclass
class Job:
    id: str
    kind: str
    title: str
    state: str = "queued"  # queued | running | done | failed | cancelled
    done: int = 0
    total: int = 0
    message: str = ""
    result: dict = field(default_factory=dict)
    created: float = field(default_factory=time.time)
    cancel: threading.Event = field(default_factory=threading.Event)

    def to_json(self) -> dict:
        return {"id": self.id, "kind": self.kind, "title": self.title, "state": self.state,
                "done": self.done, "total": self.total, "message": self.message,
                "result": self.result, "created": self.created}


class Settings:
    def __init__(self, root: Path):
        self.root = root
        self.path = root / "settings.json"
        try:
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.data = {}
        self.data.setdefault("model_dir", str(root / "models"))
        default_out = Path.home() / ("Videos" if sys.platform != "darwin" else "Movies") / "VisoMaster"
        self.data.setdefault("output_dir", str(default_out))

    @property
    def model_dir(self) -> Path:
        return Path(self.data["model_dir"])

    @property
    def output_dir(self) -> Path:
        return Path(self.data["output_dir"])

    def save(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"version": 1, **self.data}, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)


# Fusion processors require these to detect, recognise and swap with defaults.
BASE_MODELS = ("RetinaFace", "Inswapper128ArcFace", "Inswapper128")


class Workspace:
    def __init__(self, emit: Emit, root: Path | None = None):
        self.emit = emit
        self.root = root or data_root()
        self.root.mkdir(parents=True, exist_ok=True)
        self.settings = Settings(self.root)
        self.work_dir = self.root / "runtime"
        self.work_dir.mkdir(parents=True, exist_ok=True)
        # Fusion binds the model directory when models_data is first imported and
        # writes caches relative to the working directory. Changing the model
        # directory therefore takes effect after a restart.
        os.environ["VISOMASTER_MODELS_DIR"] = str(self.settings.model_dir)
        os.chdir(self.work_dir)
        self.images = ImageStore()
        self.lock = threading.RLock()
        self.engine_lock = threading.Lock()  # one inference user at a time
        self.host = None
        self.media: dict[str, Any] = {}
        self.readers: dict[str, Any] = {}
        self.current_media: str | None = None
        self.jobs: dict[str, Job] = {}
        self.job_queue: list[str] = []
        self.job_signal = threading.Condition()
        self.download_cancel = threading.Event()
        self.preview_serial = itertools.count(1)
        self.latest_preview = 0
        self.thumbs: dict[str, str] = {}
        self.segments: list[tuple[int, int]] = []  # Fusion "job marker pairs"
        self.project_path: str | None = None
        self._applied_marker: int | None = None
        self.issue_frames: dict[str, dict[str, list[int]]] = {}  # media id -> face id -> frames
        self.live = None
        threading.Thread(target=self._job_loop, name="jobs", daemon=True).start()

    # ------------------------------------------------------------------ app
    def hello(self) -> dict:
        from app.processors.utils import platform_support

        return {
            "version": VERSION,
            "platform": sys.platform,
            "machine": platform.machine(),
            "providers": list(platform_support.available_execution_providers()),
            "provider": self.host.control.get("ProvidersPrioritySelection") if self.host else None,
            "engine_ready": self.host is not None,
            "model_dir": str(self.settings.model_dir),
            "output_dir": str(self.settings.output_dir),
            "ffmpeg": bool(shutil.which("ffmpeg") and shutil.which("ffprobe")),
            "base_models_ready": not self._missing(BASE_MODELS),
        }

    def schema(self) -> dict:
        from .schema import build_schema

        if self.host is not None:
            return self.host.schema
        return build_schema()

    def get_settings(self) -> dict:
        return {"model_dir": str(self.settings.model_dir), "output_dir": str(self.settings.output_dir)}

    def set_settings(self, output_dir: str | None = None, model_dir: str | None = None) -> dict:
        restart = False
        if output_dir:
            path = Path(output_dir).expanduser()
            if not path.is_absolute():
                raise ApiError("请选择完整的文件夹路径")
            path.mkdir(parents=True, exist_ok=True)
            self.settings.data["output_dir"] = str(path)
            if self.host:
                self.host.control["OutputMediaFolder"] = str(path)
        if model_dir:
            path = Path(model_dir).expanduser()
            if not path.is_absolute():
                raise ApiError("请选择完整的文件夹路径")
            path.mkdir(parents=True, exist_ok=True)
            restart = Path(model_dir) != self.settings.model_dir and self.host is not None
            self.settings.data["model_dir"] = str(path)
        self.settings.save()
        return {**self.get_settings(), "restart_required": restart}

    # --------------------------------------------------------------- models
    def _resources(self):
        from app.studio.catalog import RESOURCES

        return RESOURCES

    def _missing(self, ids) -> list[str]:
        from app.studio.catalog import BY_ID

        root = self.settings.model_dir
        missing = []
        for rid in ids:
            r = BY_ID.get(rid)
            if r is None:
                continue
            path = root / r.filename
            if not path.is_file() or path.stat().st_size != r.size:
                missing.append(rid)
        return missing

    def models(self) -> dict:
        root = self.settings.model_dir
        items = []
        for r in self._resources():
            path = root / r.filename
            part = path.with_name(path.name + ".part")
            if path.is_file() and path.stat().st_size == r.size:
                state = "installed"
            elif part.is_file():
                state = "partial"
            else:
                state = "missing"
            items.append({"id": r.id, "name": r.name, "file": r.filename, "size": r.size,
                          "state": state, "partial": part.stat().st_size if state == "partial" else 0,
                          "sources": len(r.urls), "base": r.id in BASE_MODELS})
        usage = shutil.disk_usage(root if root.exists() else root.parent if root.parent.exists() else Path.home())
        return {"root": str(root), "free": usage.free, "items": items}

    def download_models(self, ids: list[str] | None = None) -> dict:
        ids = list(ids or BASE_MODELS)
        job = self._new_job("models", "下载模型", {"ids": ids})
        return job.to_json()

    def cancel_downloads(self) -> dict:
        for job in self.jobs.values():
            if job.kind == "models" and job.state in ("queued", "running"):
                job.cancel.set()
        return {"ok": True}

    def import_models(self, folder: str) -> dict:
        job = self._new_job("models", "导入模型", {"ids": [r.id for r in self._resources()], "source": folder})
        return job.to_json()

    def _ensure_resources(self, ids: list[str], cancel: threading.Event | None = None,
                          job: Job | None = None, source: str | None = None) -> None:
        from app.studio.catalog import BY_ID
        from app.studio.downloads import Downloader, DownloadError

        resources = [BY_ID[i] for i in ids if i in BY_ID]
        if source:
            resources = [r for r in resources if (Path(source) / r.filename).is_file()]
            if not resources:
                raise ApiError("该文件夹中没有可识别的模型")
        elif not job:
            resources = [r for r in resources if r.id in self._missing([r.id])]
        if not resources:
            return
        total = sum(r.size for r in resources)
        finished = {"bytes": 0}
        cancel = cancel or self.download_cancel

        def progress(rid, status, done, size):
            if job:
                job.done = finished["bytes"] + int(done or 0)
                job.total = total
                job.message = f"{BY_ID[rid].name} · {status}"
                self._job_event(job)
            self.emit("model.progress", {"id": rid, "status": status, "done": done, "total": size})
            if status == "已就绪":
                finished["bytes"] += int(size or 0)

        downloader = Downloader(self.settings.model_dir, cancel, progress)
        try:
            if source:
                downloader.import_models(resources, Path(source))
            else:
                downloader.prepare(resources)
        except InterruptedError:
            raise
        except DownloadError as exc:
            raise ApiError(str(exc), "download") from exc

    def _prepare_one(self, name: str) -> None:
        # Called by Fusion's model loader on a processing thread.
        from app.studio.catalog import BY_ID

        if name in BY_ID and self._missing([name]):
            self.emit("notice", {"text": f"正在下载 {name}…"})
            self._ensure_resources([name])

    def _prepare_many(self, names, source=None) -> None:
        self._ensure_resources([n for n in names], source=source)

    # --------------------------------------------------------------- engine
    def _engine(self):
        with self.lock:
            if self.host is not None:
                return self.host
            missing = self._missing(BASE_MODELS)
            if missing:
                raise ApiError("需要先下载基础模型", "models_missing")
            from app.studio.auxiliary import install_auxiliary

            self.settings.model_dir.mkdir(parents=True, exist_ok=True)
            install_auxiliary(self.settings.model_dir)
            from .host import HeadlessHost
            from app.processors.mouth_action_detector import MouthActionDetector

            self.emit("engine", {"state": "starting"})
            host = HeadlessHost(self.settings.model_dir, self.work_dir,
                                prepare_resource=self._prepare_one, prepare_resources=self._prepare_many)
            MouthActionDetector.prepare_resource = self._prepare_one
            provider = host.set_provider()
            host.control["OutputMediaFolder"] = str(self.settings.output_dir)
            # Hardware HEVC encoding is NVIDIA-only; elsewhere use the portable encoder.
            host.control["StudioSoftwareEncode"] = provider not in ("CUDA", "TensorRT", "TensorRT-Engine")
            host.frame_provider = self._frame_for_face
            self.host = host
            self.emit("engine", {"state": "ready", "provider": provider})
            return host

    def _frame_for_face(self, face):
        """Frame a target face was detected in (same input resize), for other recognition models."""
        from .media import input_height, resize_to_height

        info = next((m for mid, m in self.media.items() if m.path == face.media_path), None)
        if info is None:
            return None
        frame = self._reader(next(mid for mid, m in self.media.items() if m is info)).read(getattr(face, "frame_index", 0))
        return resize_to_height(frame, input_height(self.host.control))

    def start_engine(self) -> dict:
        self._engine()
        self._dev_preload()
        return self.hello()

    def _dev_preload(self) -> None:
        """Development/QA only: VISOMASTER_DEV_PRELOAD='{"media": [...], "sources": [...]}'."""
        raw = os.environ.pop("VISOMASTER_DEV_PRELOAD", "")
        if not raw:
            return
        spec = json.loads(raw)
        added = self.add_media(spec.get("media", []))
        if added:
            self.select_media(added[0]["id"])
        if spec.get("sources"):
            self.add_sources(spec["sources"])

    def state(self) -> dict:
        """Everything a (re)connecting window needs to rebuild its view."""
        host = self.host
        return {"media": self.list_media(), "current": self.current_media,
                "sources": self.sources(), "targets": self.targets(), "jobs": self.list_jobs(),
                "markers": self.markers(), "segments": [list(r) for r in self.segments],
                "embeddings": self.embeddings(), "project": self.project_path, "issues": self.issues(),
                "view": {"swap": host.swapfacesButton.isChecked(), "edit": host.editFacesButton.isChecked()} if host else None}

    # ---------------------------------------------------------------- media
    def add_media(self, paths: list[str]) -> list[dict]:
        from .media import probe, MediaError

        added = []
        errors = []
        for path in paths:
            try:
                info = probe(path)
            except MediaError as exc:
                errors.append(f"{Path(path).name}：{exc}")
                continue
            mid = uuid.uuid4().hex[:12]
            with self.lock:
                self.media[mid] = info
            added.append(self._media_json(mid))
        if errors and not added:
            raise ApiError("；".join(errors))
        if errors:
            self.emit("notice", {"text": "；".join(errors)})
        return added

    def _media_json(self, mid: str) -> dict:
        info = self.media[mid]
        return {"id": mid, "name": Path(info.path).name, **info.to_json(), "thumb": self._thumb(mid)}

    def _thumb(self, mid: str) -> str | None:
        if mid in self.thumbs:
            return self.thumbs[mid]
        try:
            frame = self._reader(mid).read(0)
        except Exception:
            return None
        h, w = frame.shape[:2]
        scale = 240 / max(h, w)
        thumb = cv2.resize(frame, (max(1, int(w * scale)), max(1, int(h * scale))), interpolation=cv2.INTER_AREA)
        self.thumbs[mid] = self.images.put(thumb, quality=85, key=f"thumb-{mid}")
        return self.thumbs[mid]

    def _reader(self, mid: str):
        from .media import FrameReader

        with self.lock:
            if mid not in self.media:
                raise ApiError("素材已移除")
            if mid not in self.readers:
                self.readers[mid] = FrameReader(self.media[mid])
            return self.readers[mid]

    def list_media(self) -> list[dict]:
        return [self._media_json(mid) for mid in list(self.media)]

    def remove_media(self, media_id: str) -> dict:
        with self.lock:
            self.media.pop(media_id, None)
            reader = self.readers.pop(media_id, None)
            if self.current_media == media_id:
                self.current_media = None
        if reader:
            reader.close()
        return {"ok": True}

    def select_media(self, media_id: str, detect: bool = True) -> dict:
        if media_id not in self.media:
            raise ApiError("素材已移除")
        changed = self.current_media != media_id
        self.current_media = media_id
        host = self._engine()
        host.video_processor.file_type = self.media[media_id].kind
        if changed:
            # Target faces belong to a media item, as in Fusion.
            host.clear_targets()
            host.markers.clear()
        targets = self.detect_targets(0) if detect and changed else self.targets()
        return {"media": self._media_json(media_id), "targets": targets, "issues": self.issues(media_id)}

    # ---------------------------------------------------------------- faces
    def _face_json(self, face, kind: str) -> dict:
        key = f"face-{face.face_id}"
        if not self.images.get(key):
            self.images.put(face.cropped_face, quality=90, key=key)
        data = {"id": face.face_id, "kind": kind, "image": key, "name": Path(face.media_path).name}
        if kind == "target":
            data["sources"] = list(face.assigned_input_faces)
            data["embeddings"] = list(face.assigned_merged_embeddings)
        return data

    def sources(self) -> list[dict]:
        host = self.host
        return [self._face_json(f, "source") for f in host.input_faces.values()] if host else []

    def targets(self) -> list[dict]:
        host = self.host
        return [self._face_json(f, "target") for f in host.target_faces.values()] if host else []

    def add_sources(self, paths: list[str]) -> dict:
        from .media import read_image, media_kind, MediaError

        host = self._engine()
        added, failed = [], []
        for path in paths:
            if media_kind(path) != "image":
                failed.append(f"{Path(path).name}：请使用图片")
                continue
            try:
                frame = read_image(path)
                with self.engine_lock:
                    face = host.add_source(path, frame)
            except MediaError as exc:
                failed.append(f"{Path(path).name}：{exc}")
                continue
            if face is None:
                failed.append(f"{Path(path).name}：未检测到人脸")
                continue
            added.append(self._face_json(face, "source"))
        self._auto_assign()
        return {"added": added, "failed": failed, "targets": self.targets()}

    def remove_source(self, face_id: str) -> dict:
        host = self._engine()
        with self.engine_lock:
            host.remove_source(face_id)
        return {"sources": self.sources(), "targets": self.targets()}

    def detect_targets(self, frame: int = 0) -> list[dict]:
        if not self.current_media:
            raise ApiError("请先选择素材")
        host = self._engine()
        from .media import input_height, resize_to_height

        image = resize_to_height(self._reader(self.current_media).read(frame), input_height(host.control))
        with self.engine_lock:
            added = host.find_targets(self.media[self.current_media].path, image, frame)
        self._auto_assign()
        result = self.targets()
        self.emit("faces", {"targets": result, "found": len(added)})
        return result

    def remove_target(self, face_id: str) -> list[dict]:
        self._engine().remove_target(face_id)
        return self.targets()

    def _auto_assign(self) -> None:
        # One target and one source: assign automatically. Otherwise the user decides.
        host = self.host
        if not host or len(host.target_faces) != 1 or len(host.input_faces) != 1:
            return
        target = next(iter(host.target_faces.values()))
        if target.assigned_input_faces or target.assigned_merged_embeddings:
            return
        with self.engine_lock:
            host.assign(target.face_id, list(host.input_faces))

    def assign(self, target_id: str, source_ids: list[str], embedding_ids: list[str] | None = None) -> list[dict]:
        host = self._engine()
        if target_id not in host.target_faces:
            raise ApiError("人脸已移除")
        if embedding_ids is None:
            embedding_ids = list(host.target_faces[target_id].assigned_merged_embeddings)
        with self.engine_lock:
            host.assign(target_id, source_ids, embedding_ids)
        return self.targets()

    # ------------------------------------------------------------ parameters
    REFRESH_KEYS = {"EmbMergeMethodSelection", "AverageKVToggle", "DenoiserUNetEnableBeforeRestorersToggle",
                    "DenoiserAfterFirstRestorerToggle", "DenoiserAfterRestorersToggle"}

    def get_parameters(self, face_id: str | None = None) -> dict:
        host = self._engine()
        if face_id and face_id in host.target_faces:
            host.select_face(face_id)
        face = dict(host.face_parameters(face_id)) if face_id else {}
        return {"face_id": face_id, "face": {**host.default_parameters.data, **face}, "global": dict(host.control)}

    def _coerce(self, key: str, value: Any) -> tuple[str, Any]:
        host = self._engine()
        field = next((f for s in host.schema["sections"] for f in s["fields"] if f["key"] == key), None)
        if field is None:
            if key in ("MaskShowSelection",):
                return "face", str(value)
            raise ApiError(f"未知参数 {key}")
        scope = next(s["scope"] for s in host.schema["sections"] if field in s["fields"])
        kind = field["type"]
        try:
            if kind == "toggle":
                value = bool(value)
            elif kind == "integer":
                value = int(round(float(value)))
                value = min(max(value, field["min"]), field["max"])
            elif kind == "decimal":
                value = round(min(max(float(value), field["min"]), field["max"]), field["decimals"])
            elif kind == "select":
                value = str(value)
                if field["options"] and value not in field["options"]:
                    raise ApiError("选项无效")
            else:
                value = str(value)
        except (TypeError, ValueError) as exc:
            raise ApiError("参数值无效") from exc
        return scope, value

    def set_parameters(self, values: dict, face_id: str | None = None, all_faces: bool = False) -> dict:
        host = self._engine()
        refresh = False
        for key, raw in values.items():
            scope, value = self._coerce(key, raw)
            if scope == "global":
                if key == "ProvidersPrioritySelection":
                    with self.engine_lock:
                        value = host.set_provider(value)
                host.control[key] = value
                refresh |= key in self.REFRESH_KEYS
            else:
                face_ids = list(host.target_faces) if (all_faces or not face_id) else [face_id]
                if not face_ids:
                    host.default_parameters.data[key] = value
                for fid in face_ids:
                    host.face_parameters(fid)[key] = value
                if face_id:
                    host.select_face(face_id)
        self._run_effects(host, values, face_id)
        if refresh:
            with self.engine_lock:
                host.refresh_assignments()
        return {"ok": True}

    def _run_effects(self, host, values: dict, face_id: str | None) -> None:
        """Fusion's resource side effects (unload a restorer when switched off, reset
        trackers, ...). Failures are logged; the parameter change itself stands."""
        from .schema import effect_for

        if face_id and face_id in host.target_faces:
            host.select_face(face_id)
            host.current_widget_parameters = host.face_parameters(face_id)
        for key, value in values.items():
            effect = effect_for(key)
            if effect is None:
                continue
            fn, args = effect
            try:
                with self.engine_lock:
                    fn(host, value, *args)
            except Exception as exc:  # noqa: BLE001
                print(f"[WARN] side effect for {key} failed: {exc}")

    def reset_parameters(self, face_id: str | None = None, keys: list[str] | None = None, scope: str = "face") -> dict:
        host = self._engine()
        defaults = host.schema["defaults"]["face" if scope == "face" else "global"]
        keys = keys or list(defaults)
        if scope == "face":
            for fid in ([face_id] if face_id else list(host.target_faces)):
                params = host.face_parameters(fid)
                for key in keys:
                    if key in defaults:
                        params[key] = copy.deepcopy(defaults[key])
        else:
            for key in keys:
                if key in defaults and key not in ("OutputMediaFolder",):
                    host.control[key] = copy.deepcopy(defaults[key])
        return self.get_parameters(face_id)

    def copy_parameters(self, from_face: str, to_faces: list[str] | None = None) -> dict:
        host = self._engine()
        source = dict(host.face_parameters(from_face))
        for fid in to_faces or [f for f in host.target_faces if f != from_face]:
            params = host.face_parameters(fid)
            params.data.update(copy.deepcopy(source))
        return {"ok": True}

    def set_view(self, swap: bool | None = None, edit: bool | None = None) -> dict:
        host = self._engine()
        if swap is not None:
            host.swapfacesButton.setChecked(swap)
        if edit is not None:
            host.editFacesButton.setChecked(edit)
        return {"swap": host.swapfacesButton.isChecked(), "edit": host.editFacesButton.isChecked()}

    # --------------------------------------------------------------- preview
    def preview(self, frame: int = 0, compare: bool = False, mask: bool = False,
                original: bool = False, max_side: int = 0, follow_markers: bool = False) -> dict:
        """Render the current media frame. Older queued requests are skipped."""
        from .host import RenderOptions, ProcessingError

        if not self.current_media:
            raise ApiError("请先选择素材")
        serial = next(self.preview_serial)
        self.latest_preview = serial
        host = self._engine()
        marker_applied = self._follow_markers(frame) if follow_markers else False
        from .media import input_height, resize_to_height

        image = resize_to_height(self._reader(self.current_media).read(frame), input_height(host.control))
        busy = self._busy_export()
        started = time.perf_counter()
        if original or busy:
            # The engine belongs to the running export; show the source frame, marked as such.
            result, original = image, True
        else:
            options = RenderOptions(swap=host.swapfacesButton.isChecked(), edit=host.editFacesButton.isChecked(),
                                    compare=compare, mask=mask)
            with self.engine_lock:
                if serial != self.latest_preview:
                    return {"skipped": True, "frame": frame}
                try:
                    result = host.render(image, frame, options)
                except ProcessingError as exc:
                    raise ApiError(f"处理失败：{exc}", "processing") from exc
        elapsed = time.perf_counter() - started
        h, w = result.shape[:2]
        if max_side and max(h, w) > max_side:
            scale = max_side / max(h, w)
            result = cv2.resize(result, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
        key = self.images.put(result, quality=92)
        return {"image": key, "frame": frame, "width": w, "height": h, "original": original,
                "ms": round(elapsed * 1000), "busy": self._busy_export(), "marker_applied": marker_applied}

    def _busy_export(self) -> bool:
        return any(j.kind == "export" and j.state == "running" for j in self.jobs.values())

    # ---------------------------------------------------------------- export
    def export_all(self) -> list[dict]:
        """Batch: every media item with the current faces and settings (faces are
        matched by recognition, as in Fusion's batch processing)."""
        host = self._engine()
        self._check_ready(host)
        view = host.freeze()
        jobs = []
        for mid, info in list(self.media.items()):
            jobs.append(self._new_job("export", f"导出 {Path(info.path).name}", {
                "media": mid, "kind": info.kind, "frame": 0, "start": None, "end": None, "ranges": None, "view": view,
            }).to_json())
        return jobs

    def _check_ready(self, host) -> None:
        if not host.target_faces:
            raise ApiError("没有检测到目标人脸")
        if not any(t.assigned_input_faces or t.assigned_merged_embeddings for t in host.target_faces.values()) \
                and host.swapfacesButton.isChecked():
            raise ApiError("请先为人脸选择参考脸")

    def export(self, kind: str | None = None, frame: int = 0, start: int | None = None,
               end: int | None = None, media_id: str | None = None, use_segments: bool = True) -> dict:
        media_id = media_id or self.current_media
        if not media_id or media_id not in self.media:
            raise ApiError("请先选择素材")
        host = self._engine()
        if not host.target_faces:
            raise ApiError("没有检测到目标人脸")
        if not any(t.assigned_input_faces or t.assigned_merged_embeddings for t in host.target_faces.values()) \
                and host.swapfacesButton.isChecked():
            raise ApiError("请先为人脸选择参考脸")
        info = self.media[media_id]
        kind = kind or info.kind
        name = Path(info.path).name
        # Freeze the workspace state now; later edits do not change a queued job.
        view = host.freeze()
        ranges = [tuple(r) for r in self.segments] if use_segments and self.segments and media_id == self.current_media else None
        job = self._new_job("export", f"导出 {name}", {"media": media_id, "kind": kind, "frame": frame,
                                                       "start": start, "end": end, "ranges": ranges, "view": view})
        return job.to_json()

    # ------------------------------------------------------------------ jobs
    def _new_job(self, kind: str, title: str, payload: dict) -> Job:
        job = Job(uuid.uuid4().hex[:12], kind, title)
        job.payload = payload  # type: ignore[attr-defined]
        with self.job_signal:
            self.jobs[job.id] = job
            self.job_queue.append(job.id)
            self.job_signal.notify_all()
        self._job_event(job)
        return job

    def list_jobs(self) -> list[dict]:
        return [j.to_json() for j in sorted(self.jobs.values(), key=lambda j: j.created)]

    def cancel_job(self, job_id: str) -> dict:
        job = self.jobs.get(job_id)
        if not job:
            raise ApiError("任务不存在")
        job.cancel.set()
        if job.state == "queued":
            job.state = "cancelled"
            job.message = "已取消"
            self._job_event(job)
        return job.to_json()

    def clear_jobs(self) -> list[dict]:
        with self.job_signal:
            for jid in [j.id for j in self.jobs.values() if j.state in ("done", "failed", "cancelled")]:
                self.jobs.pop(jid, None)
        return self.list_jobs()

    def _job_event(self, job: Job) -> None:
        self.emit("job", job.to_json())

    def _job_loop(self) -> None:
        while True:
            with self.job_signal:
                while not self.job_queue:
                    self.job_signal.wait()
                job = self.jobs.get(self.job_queue.pop(0))
            if job is None or job.state != "queued":
                continue
            job.state = "running"
            job.message = "开始"
            self._job_event(job)
            try:
                if job.kind == "models":
                    self._run_models(job)
                elif job.kind == "scan":
                    self._run_scan(job)
                else:
                    self._run_export(job)
                job.state = "done"
            except InterruptedError:
                job.state, job.message = "cancelled", "已取消"
            except Exception as exc:  # noqa: BLE001 - report every failure to the user
                from .export import ExportCancelled

                if isinstance(exc, ExportCancelled):
                    job.state, job.message = "cancelled", "已取消"
                else:
                    traceback.print_exc()
                    job.state, job.message = "failed", str(exc) or exc.__class__.__name__
            self._job_event(job)

    def _run_models(self, job: Job) -> None:
        payload = job.payload  # type: ignore[attr-defined]
        self._ensure_resources(payload["ids"], cancel=job.cancel, job=job, source=payload.get("source"))
        job.message = "完成"
        job.done = job.total
        self.emit("models", self.models())

    def _run_export(self, job: Job) -> None:
        from .export import ExportRequest, export_image, export_video
        from .media import FrameReader

        payload = job.payload  # type: ignore[attr-defined]
        info = self.media.get(payload["media"])
        if info is None:
            raise ApiError("素材已移除")
        view = payload["view"]
        output_dir = self._output_dir(view, info)
        request = ExportRequest(str(output_dir), start=payload.get("start") or 0, end=payload.get("end"),
                                ranges=payload.get("ranges"))
        started = time.perf_counter()
        if payload["kind"] == "image" or info.kind == "image":
            job.total = 1
            path = export_image(view, FrameReader(info), request, payload.get("frame") or 0)
            job.done = 1
        else:
            def progress(done, total):
                job.done, job.total = done, total
                job.message = f"{done}/{total} 帧"
                if done == total or done % 2 == 0:
                    self._job_event(job)

            path = export_video(view, info, request, job.cancel, progress)
        job.result = {"path": str(path), "seconds": round(time.perf_counter() - started, 2)}
        job.message = "已完成"
        self._record_history(job)

    def _output_dir(self, view, info) -> Path:
        """Fusion's output folder rules: next to the source, mirrored folder
        structure, and/or one sub-folder per reference face."""
        control = view.control
        out = Path(self.settings.output_dir)
        if control.get("OutputToTargetLocationToggle"):
            out = Path(info.path).parent
        elif control.get("PreserveOutputDirectoryStructureToggle") and len(self.media) > 1:
            try:
                root = Path(os.path.commonpath([str(Path(m.path).parent) for m in self.media.values()]))
                rel = Path(info.path).parent.relative_to(root)
                if str(rel) not in ("", "."):
                    out = out / rel
            except ValueError:
                pass
        if control.get("ClusterOutputBySourceToggle"):
            name = None
            for t in view.target_faces.values():
                if t.assigned_merged_embeddings:
                    eid = next(iter(t.assigned_merged_embeddings))
                    e = view.merged_embeddings.get(eid)
                    name = e.name if e else None
                elif t.assigned_input_faces:
                    sid = next(iter(t.assigned_input_faces))
                    s = view.input_faces.get(sid)
                    name = Path(s.media_path).stem if s else None
                if name:
                    break
            if name:
                out = out / "".join(c for c in name if c not in '\\/:*?"<>|')
        return out

    def _record_history(self, job: Job) -> None:
        path = self.root / "exports.json"
        try:
            history = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(history, list):
                history = []
        except (OSError, ValueError):
            history = []
        history.insert(0, {"path": job.result.get("path"), "time": time.time(), "seconds": job.result.get("seconds")})
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(history[:200], ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)

    # -------------------------------------------------------------- projects
    def save_project(self, path: str | None = None) -> dict:
        from . import project

        path = path or self.project_path
        if not path:
            raise ApiError("请选择保存位置")
        return project.save(self, path)

    def new_project(self) -> dict:
        if self._busy_export():
            raise ApiError("导出完成后再新建项目")
        host = self._engine()
        for mid in list(self.media):
            self.remove_media(mid)
        with host.lock:
            host.input_faces.clear()
            host.merged_embeddings.clear()
            host.clear_targets()
            host.markers.clear()
        self.segments = []
        self.project_path = None
        self._applied_marker = None
        return self.state()

    def open_project(self, path: str) -> dict:
        from . import project

        if self._busy_export():
            raise ApiError("导出完成后再打开项目")
        return project.load(self, path)

    # --------------------------------------------------------------- markers
    def markers(self) -> list[int]:
        return sorted(self.host.markers) if self.host else []

    def add_marker(self, frame: int) -> list[int]:
        host = self._engine()
        with host.lock:
            host.markers[int(frame)] = {"parameters": {fid: dict(p) for fid, p in host.parameters.items()},
                                        "control": dict(host.control)}
        self._applied_marker = int(frame)
        return self.markers()

    def remove_marker(self, frame: int) -> list[int]:
        host = self._engine()
        host.markers.pop(int(frame), None)
        if self._applied_marker == int(frame):
            self._applied_marker = None
        return self.markers()

    def _follow_markers(self, frame: int) -> bool:
        """Entering another marker's range loads that marker's settings, as Fusion does,
        so the preview shows what the export will render."""
        from .export import MarkerTimeline
        from app.helpers.miscellaneous import ParametersDict

        host = self.host
        if not host or not host.markers:
            return False
        frames = [f for f in sorted(host.markers) if f <= frame]
        current = frames[-1] if frames else None
        if current is None or current == self._applied_marker:
            return False
        params, control = MarkerTimeline(host.markers, host.snapshot(), dict(host.schema["defaults"]["global"])).state(frame)
        with host.lock:
            for fid, p in params.items():
                if fid in host.target_faces:
                    host.parameters[fid] = ParametersDict(dict(p), host.default_parameters.data)
            host.control.update({k: v for k, v in control.items() if k not in ("OutputMediaFolder",)})
        self._applied_marker = current
        return True

    # ------------------------------------------------------------------ live
    def live_start(self, source: str | int = 0, process: bool = True) -> dict:
        from .live import LiveSession

        host = self._engine()
        if self._busy_export():
            raise ApiError("导出完成后再开始实时处理")
        if self.live is None:
            self.live = LiveSession(host, self.engine_lock, self.emit)
        if self.current_media is not None:
            # Live faces are separate from the selected media's faces, as in Fusion.
            self.current_media = None
            host.clear_targets()
        host.video_processor.file_type = "webcam"
        return dict(self.live.start(source, process).__dict__)

    def live_stop(self) -> dict:
        if self.live is None:
            return {"running": False}
        stats = dict(self.live.stop().__dict__)
        if self.host:
            self.host.video_processor.file_type = "image"
        return stats

    def live_status(self) -> dict:
        return dict(self.live.stats.__dict__) if self.live else {"running": False}

    def live_detect(self) -> list[dict]:
        host = self._engine()
        if self.live is None or self.live.raw is None:
            raise ApiError("还没有摄像头画面")
        frame = self.live.raw.copy()
        with self.engine_lock:
            host.find_targets("camera", frame)
        self._auto_assign()
        return self.targets()

    # ------------------------------------------------------------ issue scan
    def scan_issues(self) -> dict:
        """Fusion's issue scan: frames where a target face is lost or not matched."""
        if not self.current_media or self.media[self.current_media].kind != "video":
            raise ApiError("问题帧扫描只适用于视频")
        host = self._engine()
        if not host.target_faces:
            raise ApiError("没有检测到目标人脸")
        view = host.freeze()
        info = self.media[self.current_media]
        job = self._new_job("scan", f"扫描 {Path(info.path).name}", {"media": self.current_media, "view": view,
                                                                     "ranges": [tuple(r) for r in self.segments]})
        return job.to_json()

    def _run_scan(self, job: Job) -> None:
        from app.processors.video_utils.issue_scanner import IssueScanner
        from app.processors.video_utils.sequential_detector import SequentialDetector

        payload = job.payload  # type: ignore[attr-defined]
        info = self.media.get(payload["media"])
        if info is None:
            raise ApiError("素材已移除")
        view = payload["view"]
        view.job_marker_pairs = list(payload["ranges"])
        view.dropped_frames = set()
        ranges = list(payload["ranges"]) or [(0, info.frames - 1)]
        scanner = IssueScanner(view, SequentialDetector(view), info.path, info.frames - 1, info.rotation)
        reason = scanner.get_issue_scan_unavailable_reason(view.control, scan_ranges=ranges, markers=view.markers,
                                                          fallback_control=view.control)
        if reason:
            raise ApiError(str(reason))
        job.total = sum(b - a + 1 for a, b in ranges)

        def progress(scanned, total, frame_number):
            job.done, job.total = int(scanned), int(total) or job.total
            job.message = f"{job.done}/{job.total} 帧"
            if job.done % 4 == 0:
                self._job_event(job)

        with self.engine_lock:
            result = scanner.scan_issue_frames(progress_callback=progress, is_cancelled=job.cancel.is_set,
                                               scan_ranges=ranges, base_control=view.control,
                                               base_params=view.parameters,
                                               control_defaults_snapshot=dict(view.schema["defaults"]["global"]))
        if not result or result.get("cancelled"):
            raise InterruptedError()
        frames = {fid: list(map(int, f)) for fid, f in result["issue_frames_by_face"].items()}
        self.issue_frames[payload["media"]] = frames
        count = len({f for v in frames.values() for f in v})
        job.result = {"issues": count, "faces": result.get("faces_with_issues", 0)}
        job.message = f"发现 {count} 个问题帧" if count else "没有发现问题帧"
        self.emit("issues", {"media": payload["media"], "frames": self.issues(payload["media"])})

    def issues(self, media_id: str | None = None) -> list[int]:
        frames = self.issue_frames.get(media_id or self.current_media or "", {})
        return sorted({f for v in frames.values() for f in v})

    # -------------------------------------------------------------- segments
    def add_segment(self, start: int, end: int) -> list[list[int]]:
        start, end = sorted((int(start), int(end)))
        self.segments.append((start, end))
        self.segments.sort()
        return [list(r) for r in self.segments]

    def remove_segment(self, index: int) -> list[list[int]]:
        if 0 <= int(index) < len(self.segments):
            self.segments.pop(int(index))
        return [list(r) for r in self.segments]

    def clear_segments(self) -> list[list[int]]:
        self.segments = []
        return []

    # --------------------------------------------------------------- presets
    def _presets_dir(self) -> Path:
        path = self.root / "presets"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def presets(self) -> list[str]:
        return sorted(p.stem for p in self._presets_dir().glob("*.json") if not p.stem.endswith("_ctl"))

    def save_preset(self, name: str, face_id: str | None = None) -> list[str]:
        from .project import _plain

        name = "".join(c for c in name.strip() if c not in '\\/:*?"<>|').strip()
        if not name:
            raise ApiError("请输入预设名称")
        host = self._engine()
        params = dict(host.face_parameters(face_id)) if face_id else dict(host.current_widget_parameters or host.default_parameters.data)
        folder = self._presets_dir()
        # Same pair of files as Fusion: <name>.json (face) and <name>_ctl.json (global).
        (folder / f"{name}.json").write_text(json.dumps(_plain(params), ensure_ascii=False, indent=2), encoding="utf-8")
        control = {k: v for k, v in host.control.items() if not k.startswith("Studio") and k != "OutputMediaFolder"}
        (folder / f"{name}_ctl.json").write_text(json.dumps(_plain(control), ensure_ascii=False, indent=2), encoding="utf-8")
        return self.presets()

    def apply_preset(self, name: str, face_id: str | None = None, include_control: bool = False) -> dict:
        from .project import _sanitise

        host = self._engine()
        folder = self._presets_dir()
        try:
            params = json.loads((folder / f"{name}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ApiError("预设文件无法读取") from exc
        clean = _sanitise(params, host.schema["defaults"]["face"])
        for fid in ([face_id] if face_id else list(host.target_faces)):
            host.face_parameters(fid).data.update(clean)
        if include_control and (folder / f"{name}_ctl.json").is_file():
            ctl = json.loads((folder / f"{name}_ctl.json").read_text(encoding="utf-8"))
            host.control.update(_sanitise(ctl, host.schema["defaults"]["global"]))
        with self.engine_lock:
            host.refresh_assignments()
        return self.get_parameters(face_id)

    def delete_preset(self, name: str) -> list[str]:
        folder = self._presets_dir()
        for p in (folder / f"{name}.json", folder / f"{name}_ctl.json"):
            p.unlink(missing_ok=True)
        return self.presets()

    # ------------------------------------------------------------ embeddings
    def embeddings(self) -> list[dict]:
        host = self.host
        return [{"id": eid, "name": e.name} for eid, e in host.merged_embeddings.items()] if host else []

    def create_embedding(self, name: str, source_ids: list[str]) -> list[dict]:
        """Merge reference faces into one saved face (Fusion merged embedding)."""
        from .host import EmbeddingSet

        host = self._engine()
        stores = [host.input_faces[s].embedding_store for s in source_ids if s in host.input_faces]
        if not stores:
            raise ApiError("请选择参考脸")
        method = host.control.get("EmbMergeMethodSelection", "Mean")
        merged = {}
        for model in {m for st in stores for m in st if m != "kps_5"}:
            vectors = [np.asarray(st[model]) for st in stores if model in st]
            vec = np.median(vectors, axis=0) if method == "Median" else np.mean(vectors, axis=0)
            norm = np.linalg.norm(vec)
            merged[model] = vec / norm if norm > 0 else vec
        eid = uuid.uuid4().hex
        host.merged_embeddings[eid] = EmbeddingSet(eid, name.strip() or f"合并人脸 {len(host.merged_embeddings) + 1}", merged)
        return self.embeddings()

    def remove_embedding(self, embedding_id: str) -> dict:
        host = self._engine()
        host.merged_embeddings.pop(embedding_id, None)
        for t in host.target_faces.values():
            if embedding_id in t.assigned_merged_embeddings:
                t.assigned_merged_embeddings.pop(embedding_id)
                with self.engine_lock:
                    t.calculate_assigned_input_embedding()
        return {"embeddings": self.embeddings(), "targets": self.targets()}

    def save_embeddings(self, path: str, ids: list[str] | None = None, fmt: str | None = None) -> dict:
        """Fusion JSON ([{name, embedding_store}]) or Rope text ("Name:" then one value per line)."""
        from .project import _plain

        host = self._engine()
        chosen = [e for eid, e in host.merged_embeddings.items() if ids is None or eid in ids]
        target = Path(path).expanduser()
        fmt = fmt or ("txt" if target.suffix.lower() == ".txt" else "json")
        if fmt == "txt":
            model = str(host.control.get("RecognitionModelSelection", "Inswapper128ArcFace"))
            lines = []
            for e in chosen:
                vector = e.embedding_store.get(model)
                if vector is None and e.embedding_store:
                    vector = next(iter(e.embedding_store.values()))
                lines.append(f"Name: {e.name}")
                lines += [repr(float(v)) for v in np.asarray(vector).ravel()] if vector is not None else []
            target.write_text("\n".join(lines) + "\n", encoding="utf-8")
        else:
            data = [{"name": e.name, "embedding_store": _plain(e.embedding_store), "kv_map": None} for e in chosen]
            target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"path": str(target), "count": len(chosen)}

    def load_embeddings(self, path: str, replace: bool = False, model: str | None = None) -> list[dict]:
        from .host import EmbeddingSet

        host = self._engine()
        source = Path(path).expanduser()
        entries: list[tuple[str, dict]] = []
        try:
            if source.suffix.lower() == ".txt":
                # Rope format: values belong to one recognition model.
                model = model or str(host.control.get("RecognitionModelSelection", "Inswapper128ArcFace"))
                name, values = None, []
                for line in source.read_text(encoding="utf-8").splitlines():
                    if line.startswith("Name:"):
                        if name is not None:
                            entries.append((name, {model: np.asarray(values, dtype=np.float32)}))
                        name, values = line.split(":", 1)[1].strip(), []
                    elif name is not None and line.strip():
                        values.append(float(line.strip()))
                if name is not None:
                    entries.append((name, {model: np.asarray(values, dtype=np.float32)}))
            else:
                for item in json.loads(source.read_text(encoding="utf-8")):
                    store = {m: np.asarray(v, dtype=np.float32) for m, v in item.get("embedding_store", {}).items()}
                    entries.append((str(item.get("name", "人脸")), store))
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            raise ApiError("人脸特征文件无法读取") from exc
        if not entries:
            raise ApiError("文件中没有人脸特征")
        if replace:
            for eid in list(host.merged_embeddings):
                self.remove_embedding(eid)
        for name, store in entries:
            eid = uuid.uuid4().hex
            host.merged_embeddings[eid] = EmbeddingSet(eid, name, store)
        return self.embeddings()

    def rename_embedding(self, embedding_id: str, name: str) -> list[dict]:
        host = self._engine()
        if embedding_id not in host.merged_embeddings or not name.strip():
            raise ApiError("名称无效")
        host.merged_embeddings[embedding_id].name = name.strip()
        return self.embeddings()

    def order_embeddings(self, ids: list[str]) -> list[dict]:
        host = self._engine()
        items = host.merged_embeddings
        ordered = {eid: items[eid] for eid in ids if eid in items}
        ordered.update({eid: e for eid, e in items.items() if eid not in ordered})
        host.merged_embeddings.clear()
        host.merged_embeddings.update(ordered)
        return self.embeddings()

    # --------------------------------------------------------------- re-aging
    def apply_reaging(self, face_id: str) -> dict:
        from app.ui.widgets.actions import control_actions

        host = self._engine()
        target = host.target_faces.get(face_id)
        if not target:
            raise ApiError("人脸已移除")
        if not target.assigned_input_faces:
            raise ApiError("请先为该人脸选择参考脸")
        params = host.face_parameters(face_id)
        if not params.get("FaceReagingEnableToggle", False):
            raise ApiError("请先开启年龄调整")
        host.cur_selected_target_face_button = target
        with self.engine_lock:
            control_actions.apply_face_reaging(host)
        if not target.aged_input_embedding:
            raise ApiError("年龄调整失败，请检查年龄模型")
        return {"ok": True}

    # ------------------------------------------------------------------ DFM
    def dfm_models(self) -> list[str]:
        host = self._engine()
        host.dfm_model_manager.refresh_models()
        return sorted(host.dfm_model_manager.get_models_data())

    def import_dfm(self, paths: list[str]) -> dict:
        host = self._engine()
        folder = Path(host.dfm_model_manager.models_path)
        folder.mkdir(parents=True, exist_ok=True)
        added, failed = [], []
        for path in paths:
            src = Path(path)
            if src.suffix.lower() not in (".dfm", ".onnx") or not src.is_file():
                failed.append(f"{src.name}：请选择 .dfm 或 .onnx 文件")
                continue
            dest = folder / src.name
            if dest.resolve() != src.resolve():
                tmp = dest.with_name(dest.name + ".import")
                shutil.copyfile(src, tmp)
                os.replace(tmp, dest)
            added.append(src.name)
        host.dfm_model_manager.refresh_models()
        from .schema import build_schema

        host.schema = build_schema(host.dfm_model_manager)
        return {"added": added, "failed": failed, "models": self.dfm_models()}

    def history(self) -> list[dict]:
        try:
            history = json.loads((self.root / "exports.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        return [h for h in history if isinstance(h, dict)][:100]

    def reveal(self, path: str) -> dict:
        target = Path(path)
        if not target.exists():
            raise ApiError("文件不存在")
        if sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(target)])
        elif sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", str(target)])
        else:
            subprocess.Popen(["xdg-open", str(target.parent)])
        return {"ok": True}

    def shutdown(self) -> None:
        if self.live is not None:
            self.live.stop()
        for job in self.jobs.values():
            job.cancel.set()
        for reader in list(self.readers.values()):
            reader.close()
