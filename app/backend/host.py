"""Headless host for Fusion's processing modules.

Fusion's processors expect a `MainWindow`. `HeadlessHost` supplies the small
surface they actually read (parameters, control, faces, model managers and four
view toggles) without creating widgets. Face state uses plain objects; the
embedding/KV merge reuses Fusion's implementation unchanged.
"""
from __future__ import annotations

import copy
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import numpy as np


class Toggle:
    """Stands in for the four checkable buttons the frame worker reads."""

    def __init__(self, value: bool = False):
        self.value = bool(value)

    def isChecked(self) -> bool:  # noqa: N802 - Qt-compatible name
        return self.value

    def setChecked(self, value: bool) -> None:  # noqa: N802
        self.value = bool(value)


class Signal:
    """Synchronous callback list compatible with the `emit` calls in processors."""

    def __init__(self):
        self._slots: list[Callable] = []

    def connect(self, slot: Callable) -> None:
        self._slots.append(slot)

    def emit(self, *args) -> None:
        for slot in list(self._slots):
            slot(*args)


class _Dialog:
    def show(self):
        pass

    def close(self):
        pass


@dataclass
class SourceFace:
    face_id: str
    media_path: str
    cropped_face: np.ndarray  # BGR crop, as on Fusion's InputFaceCardButton
    embedding_store: dict[str, np.ndarray]
    kv_map: dict | None = None

    def get_embedding(self, model: str) -> np.ndarray:
        return self.embedding_store.get(model, np.array([]))

    def set_embedding(self, model: str, embedding: np.ndarray) -> None:
        self.embedding_store[model] = embedding


class EmbeddingSet:
    """Saved/merged embedding, matching EmbeddingCardButton's data fields."""

    def __init__(self, embedding_id: str, name: str, embedding_store: dict, kv_map_list=None):
        self.embedding_id = embedding_id
        self.name = name
        self.embedding_store = embedding_store
        self.kv_map_list = kv_map_list or []
        self.kv_map = None

    def get_embedding(self, model: str) -> np.ndarray:
        return self.embedding_store.get(model, np.array([]))


def _fusion_merge():
    from app.ui.widgets.widget_components import TargetFaceCardButton

    return TargetFaceCardButton.calculate_assigned_input_embedding


def _fusion_target_embedding():
    from app.ui.widgets.widget_components import TargetFaceCardButton

    return TargetFaceCardButton.get_embedding


class TargetFace:
    def __init__(self, host: "HeadlessHost", face_id: str, media_path: str,
                 cropped_face: np.ndarray, embedding_store: dict[str, np.ndarray]):
        from app.processors.mouth_openness import MouthOpennessState

        self.main_window = host
        self.face_id = face_id
        self.media_path = media_path
        self.cropped_face = cropped_face
        self.embedding_store = embedding_store
        self.assigned_input_faces: dict[str, dict[str, np.ndarray]] = {}
        self.assigned_merged_embeddings: dict[str, dict[str, np.ndarray]] = {}
        self.assigned_input_embedding: dict[str, np.ndarray] = {}
        self.assigned_kv_map: dict | None = None
        self.aged_input_embedding: dict[str, np.ndarray] = {}
        self.aged_kv_map: dict | None = None
        self.kv_data_color_transferred = False
        self.mouth_openness_state = MouthOpennessState()

    def get_embedding(self, model: str) -> np.ndarray:
        stored = self.embedding_store.get(model)
        if stored is not None and np.asarray(stored).size:
            return stored
        # Precise: recognise again on the frame the face was found in, with its keypoints.
        provider = getattr(self.main_window, "frame_provider", None)
        kps = getattr(self, "kps_5", None)
        if provider is not None and kps is not None:
            try:
                frame = provider(self)
                if frame is not None:
                    embedding, _ = self.main_window.function_worker.run_recognize_direct(
                        self.main_window._tensor(frame), kps, "Auto", model)
                    if embedding is not None and np.asarray(embedding).size:
                        self.embedding_store[model] = embedding
                        return embedding
            except Exception as exc:  # noqa: BLE001
                print(f"[WARN] target embedding for {model} from frame failed: {exc}")
        # Fallback (live camera): Fusion estimates it from the crop.
        return _fusion_target_embedding()(self, model)

    def set_embedding(self, model: str, embedding: np.ndarray) -> None:
        self.embedding_store[model] = embedding

    def clone(self) -> "TargetFace":
        """Copy for an export job: later assignment changes do not affect it."""
        from app.processors.mouth_openness import MouthOpennessState

        twin = copy.copy(self)
        twin.embedding_store = dict(self.embedding_store)
        twin.assigned_input_faces = dict(self.assigned_input_faces)
        twin.assigned_merged_embeddings = dict(self.assigned_merged_embeddings)
        twin.assigned_input_embedding = dict(self.assigned_input_embedding)
        twin.aged_input_embedding = dict(self.aged_input_embedding)
        twin.mouth_openness_state = MouthOpennessState()
        return twin

    def calculate_assigned_input_embedding(self) -> None:
        # Mean/median merge, L2 normalisation and ReF-LDM K/V merge exactly as Fusion.
        _fusion_merge()(self)


class _VideoProcessorStub:
    """The frame worker only reads `file_type` and emits result signals."""

    def __init__(self):
        self.file_type = "image"
        self.ui_state_is_dirty = False
        self.single_frame_processed_signal = Signal()
        self.frame_processed_signal = Signal()
        self.webcam_frame_processed_signal = Signal()
        self.fatal_processing_error_signal = Signal()


@dataclass
class RenderOptions:
    swap: bool = True
    edit: bool = True
    compare: bool = False
    mask: bool = False


class ProcessingError(RuntimeError):
    pass


class HeadlessHost:
    """Owns models, parameters and face state for one workspace."""

    def __init__(self, models_dir: Path, work_dir: Path, schema: dict | None = None,
                 prepare_resource: Callable[[str], None] | None = None,
                 prepare_resources: Callable[[list[str]], None] | None = None,
                 device: str = ""):
        from app.helpers.miscellaneous import DFMModelManager, ParametersDict
        from app.processors.models_processor import ModelsProcessor
        from app.processors.workers.function_worker import FunctionWorker
        from .schema import build_schema

        self.models_dir = Path(models_dir)
        self.work_dir = Path(work_dir)
        dfm_dir = self.models_dir / "dfm_models"
        dfm_dir.mkdir(parents=True, exist_ok=True)
        self.dfm_model_manager = DFMModelManager(str(dfm_dir))
        self.schema = schema or build_schema(self.dfm_model_manager)

        # Interfaces that Fusion's processors read from MainWindow.
        self.control: dict[str, Any] = dict(self.schema["defaults"]["global"])
        self.default_parameters = ParametersDict(dict(self.schema["defaults"]["face"]), {})
        self.default_parameters._default_parameters = self.default_parameters.data
        self.parameters: dict[str, Any] = {}
        self.target_faces: dict[str, TargetFace] = {}
        self.input_faces: dict[str, SourceFace] = {}
        self.merged_embeddings: dict[str, EmbeddingSet] = {}
        self.markers: dict = {}
        self.parameter_widgets: dict = {}
        self.fixed_unet_model_name = "RefLDM_UNET_EXTERNAL_KV"
        self.current_kv_tensors_map = None
        self.selected_target_face_id: str | None = None
        self.current_widget_parameters: dict = {}
        self.cur_selected_target_face_button = None
        self._batch_update_in_progress = True  # Fusion's refresh_frame becomes a no-op
        self.gpu_id = 0
        self.swapfacesButton = Toggle(True)
        self.editFacesButton = Toggle(False)
        self.faceCompareCheckBox = Toggle(False)
        self.faceMaskCheckBox = Toggle(False)
        self.model_loading_signal = Signal()
        self.model_loaded_signal = Signal()
        self.display_messagebox_signal = Signal()
        self.model_load_dialog = _Dialog()
        if prepare_resource:
            self.prepare_model_resource = prepare_resource
        if prepare_resources:
            self.prepare_extra_resources = prepare_resources

        self.video_processor = _VideoProcessorStub()
        self.models_processor = ModelsProcessor(self, device)
        self._load_failures = threading.local()
        self._watch_model_loads()
        self.function_worker = FunctionWorker(self.models_processor)
        self.lock = threading.RLock()

        # Studio never substitutes the source frame for a failed result.
        self.control["StudioStrictProcessing"] = True
        self.control["StudioTempDir"] = str(self.work_dir / "work")

    def _watch_model_loads(self) -> None:
        """Fusion logs a failed model load and skips that stage. Record failures per
        thread so a request that hit one fails instead of returning partial output."""
        load = self.models_processor.load_model
        failures = self._load_failures

        def load_model(name, *args, **kwargs):
            session = load(name, *args, **kwargs)
            if not session:
                getattr(failures, "names", None) is None and setattr(failures, "names", [])
                failures.names.append(str(name))
            return session

        self.models_processor.load_model = load_model

    def _begin(self) -> None:
        self._load_failures.names = []

    def _check(self) -> None:
        names = getattr(self._load_failures, "names", None) or []
        if names:
            self._load_failures.names = []
            raise ProcessingError("模型加载失败：" + "、".join(dict.fromkeys(names)))

    # ----- parameters ---------------------------------------------------
    def face_parameters(self, face_id: str):
        from app.helpers.miscellaneous import ParametersDict

        if face_id not in self.parameters:
            # As Fusion: a new face starts from the selected face's values, else the
            # last values shown for any face, else defaults.
            inherited = self.parameters.get(self.selected_target_face_id or "") or self.current_widget_parameters
            self.parameters[face_id] = ParametersDict(copy.deepcopy(dict(inherited or {})), self.default_parameters.data)
        return self.parameters[face_id]

    def select_face(self, face_id: str | None) -> None:
        self.selected_target_face_id = face_id
        if face_id and face_id in self.parameters:
            self.current_widget_parameters = dict(self.parameters[face_id])

    def set_provider(self, provider: str | None = None) -> str:
        from app.processors.utils import platform_support

        supported = platform_support.available_execution_providers()
        provider = provider or str(self.control.get("ProvidersPrioritySelection", ""))
        if provider not in supported:
            provider = platform_support.default_execution_provider()
        self.control["ProvidersPrioritySelection"] = provider
        self.function_worker.switch_providers_priority(provider)
        return provider

    # ----- faces --------------------------------------------------------
    def _tensor(self, frame_bgr: np.ndarray):
        import torch

        rgb = np.ascontiguousarray(frame_bgr[..., ::-1])
        return torch.from_numpy(rgb.astype("uint8")).to(self.models_processor.device).permute(2, 0, 1)

    def detect(self, frame_bgr: np.ndarray, max_faces: int | None = None) -> list[tuple[np.ndarray, np.ndarray, np.ndarray]]:
        """Returns (kps_5, embedding, BGR crop) for each detected face."""
        from torchvision.transforms import v2

        control = dict(self.control)
        self._begin()
        img = self._tensor(frame_bgr)
        if control.get("ManualRotationEnableToggle", False):
            img = v2.functional.rotate(img, angle=control.get("ManualRotationAngleSlider", 0),
                                       interpolation=v2.InterpolationMode.BILINEAR, expand=True)
        _, kpss_5, _ = self.function_worker.run_detect(
            img,
            str(control.get("DetectorModelSelection", "RetinaFace")),
            max_num=int(max_faces if max_faces is not None else control.get("MaxFacesToDetectSlider", 1)),
            score=float(control.get("DetectorScoreSlider", 50)) / 100.0,
            input_size=(512, 512),
            use_landmark_detection=bool(control.get("LandmarkDetectToggle", False)),
            landmark_detect_mode=str(control.get("LandmarkDetectModelSelection", "203")),
            landmark_score=float(control.get("LandmarkDetectScoreSlider", 50)) / 100.0,
            from_points=bool(control.get("DetectFromPointsToggle", False)),
            rotation_angles=[0] if not control.get("AutoRotationToggle", False) else [0, 90, 180, 270],
        )
        self._check()
        model = str(control.get("RecognitionModelSelection", "Inswapper128ArcFace"))
        faces = []
        for kps in kpss_5 if kpss_5 is not None else []:
            if not np.asarray(kps).any():
                continue
            embedding, crop = self.function_worker.run_recognize_direct(img, kps, "Auto", model)
            if embedding is None:
                continue
            crop_bgr = np.ascontiguousarray(crop.cpu().numpy()[..., ::-1])
            faces.append((kps, embedding, crop_bgr))
        self._check()
        return faces

    def add_source(self, path: str, frame_bgr: np.ndarray) -> SourceFace | None:
        found = self.detect(frame_bgr, max_faces=1)
        if not found:
            return None
        kps, embedding, crop = found[0]
        model = str(self.control.get("RecognitionModelSelection", "Inswapper128ArcFace"))
        face = SourceFace(str(uuid.uuid4()), path, crop, {model: embedding, "kps_5": kps})
        with self.lock:
            self.input_faces[face.face_id] = face
        return face

    def find_targets(self, path: str, frame_bgr: np.ndarray, frame_index: int = 0) -> list[TargetFace]:
        """Adds faces not already known, using each face's own similarity threshold."""
        model = str(self.control.get("RecognitionModelSelection", "Inswapper128ArcFace"))
        added = []
        for kps, embedding, crop in self.detect(frame_bgr):
            known = False
            for target in self.target_faces.values():
                threshold = float(self.face_parameters(target.face_id).get("SimilarityThresholdSlider", 60))
                if self.function_worker.findCosineDistance(target.get_embedding(model), embedding) >= threshold:
                    known = True
                    break
            if known:
                continue
            face = TargetFace(self, str(uuid.uuid4()), path, crop, {model: embedding})
            face.kps_5 = np.asarray(kps)
            face.frame_index = int(frame_index)
            with self.lock:
                self.target_faces[face.face_id] = face
                self.face_parameters(face.face_id)
            added.append(face)
        return added

    def assign(self, target_id: str, source_ids: list[str], embedding_ids: list[str] | None = None) -> None:
        target = self.target_faces[target_id]
        with self.lock:
            target.assigned_input_faces = {sid: self.input_faces[sid].embedding_store
                                           for sid in source_ids if sid in self.input_faces}
            target.assigned_merged_embeddings = {eid: self.merged_embeddings[eid].embedding_store
                                                 for eid in (embedding_ids or []) if eid in self.merged_embeddings}
        target.calculate_assigned_input_embedding()

    def refresh_assignments(self) -> None:
        """Recompute merged embeddings after merge/denoiser settings change."""
        for target in list(self.target_faces.values()):
            if target.assigned_input_faces or target.assigned_merged_embeddings:
                target.calculate_assigned_input_embedding()

    def _source_embedding(self, face: SourceFace, model: str) -> bool:
        """Recognise a reference face with another recognition model, from its image and keypoints."""
        if model in face.embedding_store and np.asarray(face.embedding_store[model]).size:
            return True
        from .media import read_image

        try:
            frame = read_image(face.media_path)
            embedding, _ = self.function_worker.run_recognize_direct(self._tensor(frame), face.embedding_store["kps_5"],
                                                                     "Auto", model)
        except Exception as exc:  # noqa: BLE001
            print(f"[WARN] could not compute {model} embedding for {face.media_path}: {exc}")
            return False
        if embedding is None or not np.asarray(embedding).size:
            return False
        face.embedding_store[model] = embedding
        return True

    def prepare_embeddings(self, parameters: dict) -> None:
        """Each swapper needs its own recognition model (SimSwap, Ghost, CSCS). Fill in
        missing reference embeddings for the selected swapper before rendering."""
        from app.processors.models_data import arcface_mapping_model_dict

        for fid, target in list(self.target_faces.items()):
            p = parameters.get(fid) or self.default_parameters.data
            model = arcface_mapping_model_dict.get(str(p.get("SwapModelSelection", "Inswapper128")), "Inswapper128ArcFace")
            if model in target.assigned_input_embedding or not target.assigned_input_faces:
                continue
            with self.lock:
                changed = False
                for sid in list(target.assigned_input_faces):
                    face = self.input_faces.get(sid)
                    if face is not None and model not in face.embedding_store and self._source_embedding(face, model):
                        target.assigned_input_faces[sid] = face.embedding_store
                        changed = True
                if changed or model in next(iter(target.assigned_input_faces.values()), {}):
                    target.calculate_assigned_input_embedding()

    def remove_source(self, source_id: str) -> None:
        with self.lock:
            self.input_faces.pop(source_id, None)
            affected = [t for t in self.target_faces.values() if source_id in t.assigned_input_faces]
            for target in affected:
                target.assigned_input_faces.pop(source_id, None)
        for target in affected:
            target.calculate_assigned_input_embedding()

    def remove_target(self, target_id: str) -> None:
        with self.lock:
            self.target_faces.pop(target_id, None)
            self.parameters.pop(target_id, None)

    def clear_targets(self) -> None:
        with self.lock:
            if self.selected_target_face_id in self.parameters:
                self.current_widget_parameters = dict(self.parameters[self.selected_target_face_id])
            self.target_faces.clear()
            self.parameters.clear()
            self.selected_target_face_id = None

    # ----- rendering ----------------------------------------------------
    def snapshot(self) -> tuple[dict, dict]:
        with self.lock, self.models_processor.model_lock:
            parameters = copy.deepcopy(self.parameters)
            control = copy.deepcopy(self.control)
        for face_id in list(self.target_faces):
            if face_id not in parameters:
                parameters[face_id] = self.default_parameters.copy()
        return parameters, control

    def freeze(self) -> "HostView":
        """Independent copy of the workspace state for a queued export."""
        with self.lock, self.models_processor.model_lock:
            targets = {fid: t.clone() for fid, t in self.target_faces.items()}
            return HostView(self, targets, copy.deepcopy(self.parameters), copy.deepcopy(self.control),
                            copy.deepcopy(self.markers), self.swapfacesButton.isChecked(),
                            self.editFacesButton.isChecked())

    def new_worker(self, frame_rgb: np.ndarray | None = None, frame_number: int = 0):
        from app.processors.workers.frame_worker import FrameWorker

        return FrameWorker(self, frame=frame_rgb, frame_number=frame_number, is_single_frame=True)

    def render(self, frame_bgr: np.ndarray, frame_number: int = 0, options: RenderOptions | None = None,
               worker=None, state: tuple[dict, dict] | None = None, stop: threading.Event | None = None) -> np.ndarray:
        """Process one BGR frame. Errors propagate; the source is never returned as a result."""
        options = options or RenderOptions()
        parameters, control = state or self.snapshot()
        if options.swap:
            self.prepare_embeddings(parameters)
        control["swap_enabled"] = options.swap
        control["edit_enabled"] = options.edit
        needs = (options.swap or options.edit or control.get("FrameEnhancerEnableToggle", False)
                 or control.get("ModeEnableToggle", False) or options.compare or options.mask)
        if not needs:
            return frame_bgr.copy()
        frame_rgb = np.ascontiguousarray(frame_bgr[..., ::-1])
        worker = worker or self.new_worker(frame_rgb, frame_number)
        worker.frame = frame_rgb
        worker.frame_number = frame_number
        worker.parameters = parameters
        worker.local_control_state_from_feeder = control
        worker.is_view_face_compare = options.compare
        worker.is_view_face_mask = options.mask
        self._begin()
        try:
            result = worker.process_frame(control, stop or threading.Event())
            self._check()
        except ProcessingError:
            raise
        except Exception as exc:  # surface as a processing failure, never as output
            raise ProcessingError(str(exc) or exc.__class__.__name__) from exc
        if result is None:
            raise ProcessingError("处理未返回结果")
        return np.ascontiguousarray(result)


class HostView:
    """A job's own view of the workspace: frozen faces, parameters, control and
    markers; models, locks and everything else are shared with the host. Workers
    created from a view read only the frozen state."""

    def __init__(self, host: HeadlessHost, target_faces: dict, parameters: dict, control: dict,
                 markers: dict, swap: bool, edit: bool):
        self._host = host
        self.target_faces = target_faces
        self.parameters = parameters
        self.control = control
        self.markers = markers
        self.swapfacesButton = Toggle(swap)
        self.editFacesButton = Toggle(edit)
        self.faceCompareCheckBox = Toggle(False)
        self.faceMaskCheckBox = Toggle(False)
        self.lock = threading.RLock()

    def __getattr__(self, name):
        return getattr(self._host, name)

    snapshot = HeadlessHost.snapshot
    new_worker = HeadlessHost.new_worker
    render = HeadlessHost.render
    prepare_embeddings = HeadlessHost.prepare_embeddings
