"""Projects in Fusion's workspace JSON format.

Files written here open in Fusion/Studio 0.2 and Fusion workspaces open here:
target faces keep crop, embeddings, per-face parameters and assignments;
reference faces are stored by path and detected again on load (as Fusion does).
Window/dock state is not written; it is ignored when reading.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    from .service import Workspace

STUDIO_KEYS = ("StudioStrictProcessing", "StudioTempDir", "StudioSoftwareEncode", "OutputMediaFolder")


def _plain(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (np.floating, np.integer)):
        return value.item()
    if isinstance(value, dict) or hasattr(value, "items"):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


def _sanitise(values: dict, defaults: dict) -> dict:
    """Keep known keys whose stored value matches the default's type."""
    clean = {}
    for key, value in (values or {}).items():
        if key not in defaults:
            continue
        default = defaults[key]
        try:
            if isinstance(default, bool):
                clean[key] = bool(value)
            elif isinstance(default, int):
                clean[key] = int(round(float(value)))
            elif isinstance(default, float):
                clean[key] = float(value)
            else:
                clean[key] = str(value) if value is not None else default
        except (TypeError, ValueError):
            continue
    return clean


def save(ws: "Workspace", path: str) -> dict:
    host = ws._engine()
    target = Path(path).expanduser()
    if target.suffix.lower() != ".json":
        target = target.with_suffix(".json")
    media = [{"media_path": info.path, "file_type": info.kind, "media_id": mid, "is_webcam": False,
              "webcam_index": -1, "webcam_backend": -1} for mid, info in ws.media.items()]
    with host.lock:
        targets = {}
        for fid, face in host.target_faces.items():
            targets[fid] = {
                "cropped_face": face.cropped_face.tolist(),
                "embedding_store": {m: np.asarray(e).tolist() for m, e in face.embedding_store.items()},
                "parameters": _plain(dict(host.face_parameters(fid))),
                "assigned_input_faces": list(face.assigned_input_faces),
                "assigned_merged_embeddings": list(face.assigned_merged_embeddings),
                "assigned_input_embedding": {m: np.asarray(e).tolist() for m, e in face.assigned_input_embedding.items()},
                "assigned_kv_map": None,
                "media_path": face.media_path,
                # Studio extras (ignored by Fusion): precise re-recognition with other models.
                "kps_5": np.asarray(face.kps_5).tolist() if getattr(face, "kps_5", None) is not None else None,
                "frame_index": int(getattr(face, "frame_index", 0)),
            }
        data = {
            "control": _plain({k: v for k, v in host.control.items() if k not in STUDIO_KEYS[:3]}),
            "target_medias_data": media,
            "selected_media_id": ws.current_media or False,
            "selected_target_face_id": host.selected_target_face_id,
            "swap_faces_enabled": host.swapfacesButton.isChecked(),
            "edit_faces_enabled": host.editFacesButton.isChecked(),
            "input_faces_data": {fid: {"media_path": f.media_path, "kv_map": None} for fid, f in host.input_faces.items()},
            "target_faces_data": targets,
            "embeddings_data": {eid: {"embedding_name": e.name, "embedding_store": _plain(e.embedding_store), "kv_map": None}
                                for eid, e in host.merged_embeddings.items()},
            "markers": {str(frame): _plain(m) for frame, m in host.markers.items()},
            "job_marker_pairs": [list(r) for r in ws.segments],
            "issue_frames_by_face": {},
            "dropped_frames": [],
            "studio": {"version": 1, "app": __import__("app.backend.service", fromlist=["VERSION"]).VERSION},
        }
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, target)
    ws.project_path = str(target)
    return {"path": str(target)}


def load(ws: "Workspace", path: str) -> dict:
    from .host import EmbeddingSet, SourceFace, TargetFace
    from .media import read_image
    from .service import ApiError

    source = Path(path).expanduser()
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ApiError("无法读取项目文件") from exc
    if not isinstance(data, dict) or "target_faces_data" not in data and "control" not in data:
        raise ApiError("这不是 VisoMaster 项目文件")
    host = ws._engine()
    warnings: list[str] = []
    defaults_face = host.schema["defaults"]["face"]
    defaults_global = host.schema["defaults"]["global"]

    # Reset the workspace.
    for mid in list(ws.media):
        ws.remove_media(mid)
    with host.lock:
        host.input_faces.clear()
        host.merged_embeddings.clear()
        host.clear_targets()
        host.markers.clear()
    ws.segments = []

    control = _sanitise(data.get("control", {}), defaults_global)
    keep = {k: host.control[k] for k in STUDIO_KEYS if k in host.control}
    host.control.update(control)
    host.control.update(keep)
    if "ProvidersPrioritySelection" in control:
        with ws.engine_lock:
            host.set_provider(control["ProvidersPrioritySelection"])

    # Media (missing files are reported, not fatal).
    id_map = {}
    for item in data.get("target_medias_data", []):
        media_path = item.get("media_path")
        if item.get("is_webcam") or not media_path:
            continue
        if not Path(media_path).is_file():
            warnings.append(f"找不到素材：{Path(media_path).name}")
            continue
        added = ws.add_media([media_path])
        if added:
            id_map[item.get("media_id")] = added[0]["id"]
    selected = id_map.get(data.get("selected_media_id"))
    if selected is None and id_map:
        selected = next(iter(id_map.values()))
    if selected:
        ws.select_media(selected, detect=False)

    # Reference faces: detect again from the saved image paths, keeping their ids.
    for fid, item in data.get("input_faces_data", {}).items():
        media_path = item.get("media_path", "")
        try:
            frame = read_image(media_path)
            with ws.engine_lock:
                found = host.detect(frame, max_faces=1)
        except Exception:
            found = []
        if not found:
            warnings.append(f"参考脸不可用：{Path(media_path).name}")
            continue
        kps, embedding, crop = found[0]
        model = str(host.control.get("RecognitionModelSelection", "Inswapper128ArcFace"))
        host.input_faces[fid] = SourceFace(fid, media_path, crop, {model: embedding, "kps_5": kps})

    for eid, item in data.get("embeddings_data", {}).items():
        store = {m: np.asarray(v, dtype=np.float32) for m, v in item.get("embedding_store", {}).items()}
        host.merged_embeddings[eid] = EmbeddingSet(eid, item.get("embedding_name", eid), store)

    media_path = ws.media[selected].path if selected else ""
    for fid, item in data.get("target_faces_data", {}).items():
        try:
            crop = np.asarray(item["cropped_face"], dtype=np.uint8)
            store = {m: np.asarray(v, dtype=np.float32) for m, v in item.get("embedding_store", {}).items()}
        except (KeyError, ValueError, TypeError):
            warnings.append("一个目标人脸数据损坏，已跳过")
            continue
        face = TargetFace(host, fid, item.get("media_path", media_path), crop, store)
        if item.get("kps_5") is not None:
            face.kps_5 = np.asarray(item["kps_5"], dtype=np.float32)
            face.frame_index = int(item.get("frame_index", 0))
        host.target_faces[fid] = face
        params = host.face_parameters(fid)
        params.data.clear()
        params.data.update(copy.deepcopy(defaults_face))
        params.data.update(_sanitise(item.get("parameters", {}), defaults_face))
        face.assigned_input_faces = {s: host.input_faces[s].embedding_store for s in item.get("assigned_input_faces", [])
                                     if s in host.input_faces}
        face.assigned_merged_embeddings = {e: host.merged_embeddings[e].embedding_store
                                           for e in item.get("assigned_merged_embeddings", []) if e in host.merged_embeddings}
        if face.assigned_input_faces or face.assigned_merged_embeddings:
            with ws.engine_lock:
                face.calculate_assigned_input_embedding()

    for frame, marker in (data.get("markers") or {}).items():
        try:
            host.markers[int(frame)] = {
                "parameters": {fid: {**defaults_face, **_sanitise(p, defaults_face)}
                               for fid, p in (marker.get("parameters") or {}).items()},
                "control": _sanitise(marker.get("control") or {}, defaults_global),
            }
        except (TypeError, ValueError):
            continue
    for pair in data.get("job_marker_pairs") or []:
        if isinstance(pair, (list, tuple)) and len(pair) == 2 and pair[1] is not None:
            ws.segments.append((int(pair[0]), int(pair[1])))

    host.swapfacesButton.setChecked(bool(data.get("swap_faces_enabled", True)))
    host.editFacesButton.setChecked(bool(data.get("edit_faces_enabled", False)))
    sel = data.get("selected_target_face_id")
    host.select_face(sel if sel in host.target_faces else next(iter(host.target_faces), None))
    ws.project_path = str(source)
    return {"path": str(source), "warnings": warnings, **ws.state()}
