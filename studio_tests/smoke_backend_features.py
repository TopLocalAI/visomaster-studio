"""Real-model check of workspace features through the service API (synthetic media only).

Usage: .venv-studio/bin/python studio_tests/smoke_backend_features.py <output dir>
Models come from the installed model folder via symlinks in a temporary model
directory, so imported test files never touch the user's real model folder.
"""
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

DESKTOP = Path(__file__).resolve().parents[1]
ROOT = DESKTOP.parent
REAL_MODELS = Path(os.environ.get("VISOMASTER_TEST_MODELS", Path.home() / "Library/Application Support/VisoMasterStudio/models"))
OUT = Path(sys.argv[1]).resolve()
OUT.mkdir(parents=True, exist_ok=True)
tmp = Path(tempfile.mkdtemp(prefix="studio-features-"))
models = tmp / "models"
models.mkdir()
for item in REAL_MODELS.iterdir():
    if not item.name.startswith("."):
        (models / item.name).symlink_to(item)
(models / "dfm_models").unlink()
(models / "dfm_models").mkdir()
(tmp / "home").mkdir()
(tmp / "home/settings.json").write_text(json.dumps({"model_dir": str(models), "output_dir": str(tmp / "exports")}))
os.environ["VISOMASTER_STUDIO_HOME"] = str(tmp / "home")
sys.path.insert(0, str(DESKTOP))
os.chdir(DESKTOP)

from app.backend.service import Workspace, ApiError  # noqa: E402
from app.backend.export import _count_frames  # noqa: E402

PORTRAIT = str(ROOT / "design/assets/synthetic-portrait.png")
REFERENCE = str(ROOT / "benchmarks/studio-complete-2026-10-06/second-reference.png")
VIDEO = str(ROOT / "benchmarks/studio-regression-2026-10-06/eight-seconds.mp4")
events = []
ws = Workspace(lambda e, d: events.append(e))
result = {"steps": []}


def step(name, **data):
    result["steps"].append({"name": name, **data})
    print("✓", name, data if data else "")


def wait(job_ids):
    while any(ws.jobs[j].state in ("queued", "running") for j in job_ids):
        time.sleep(0.2)
    return [ws.jobs[j] for j in job_ids]


try:
    ws.start_engine()
    img, vid = ws.add_media([PORTRAIT, VIDEO])
    ws.select_media(img["id"])
    src = ws.add_sources([REFERENCE])["added"][0]
    face = ws.targets()[0]
    assert face["sources"] == [src["id"]]
    ws.set_parameters({"FaceRestorerEnableToggle": True, "SimilarityThresholdSlider": 55}, face_id=face["id"])

    # Presets (Fusion's two-file format)
    ws.save_preset("测试预设", face_id=face["id"])
    assert (tmp / "home/presets/测试预设.json").is_file() and (tmp / "home/presets/测试预设_ctl.json").is_file()
    ws.set_parameters({"FaceRestorerEnableToggle": False}, face_id=face["id"])
    applied = ws.apply_preset("测试预设", face_id=face["id"])
    assert applied["face"]["FaceRestorerEnableToggle"] is True
    step("preset save/apply", presets=ws.presets())

    # Merged embedding from a reference face, assigned in addition to the source
    emb = ws.create_embedding("合并测试", [src["id"]])
    ws.assign(face["id"], [], [emb[0]["id"]])
    assert ws.targets()[0]["embeddings"] == [emb[0]["id"]] and ws.targets()[0]["sources"] == []
    ws.save_embeddings(str(tmp / "embeddings.json"))
    ws.remove_embedding(emb[0]["id"])
    assert ws.load_embeddings(str(tmp / "embeddings.json"))[0]["name"] == "合并测试"
    # Rope text format round trip, subset save, rename and order
    ws.create_embedding("第二个", [src["id"]])
    ids = [e["id"] for e in ws.embeddings()]
    ws.rename_embedding(ids[0], "改名后")
    ws.save_embeddings(str(tmp / "rope.txt"), ids=[ids[0]], fmt="txt")
    assert (tmp / "rope.txt").read_text().startswith("Name: 改名后")
    loaded_rope = ws.load_embeddings(str(tmp / "rope.txt"), replace=True)
    assert [e["name"] for e in loaded_rope] == ["改名后"]
    ws.create_embedding("A", [src["id"]])
    order = [e["id"] for e in ws.embeddings()][::-1]
    assert [e["id"] for e in ws.order_embeddings(order)] == order
    step("face library: rope format, rename, order")
    ws.assign(face["id"], [src["id"]], [])
    prev = ws.preview(0)
    assert not prev["original"]
    step("embedding create/assign/save/load")

    # Project round trip
    proj = tmp / "project.json"
    ws.save_project(str(proj))
    saved = json.loads(proj.read_text())
    assert set(saved) >= {"control", "target_faces_data", "input_faces_data", "markers", "target_medias_data"}
    loaded = ws.open_project(str(proj))
    assert len(loaded["media"]) == 2 and len(loaded["targets"]) == 1 and loaded["targets"][0]["sources"]
    p = ws.get_parameters(loaded["targets"][0]["id"])["face"]
    assert p["FaceRestorerEnableToggle"] is True and p["SimilarityThresholdSlider"] == 55
    step("project save/open (Fusion format)", warnings=loaded["warnings"])

    # Old Studio 0.2 / Fusion workspace file, if available
    legacy = ROOT / "benchmarks/studio-complete-2026-10-06/project.json"
    if legacy.is_file():
        old = ws.open_project(str(legacy))
        step("open Studio 0.2 workspace", media=len(old["media"]), targets=len(old["targets"]), warnings=old["warnings"])
        ws.open_project(str(proj))

    # Video: markers + segments + batch
    ws.select_media(next(m["id"] for m in ws.list_media() if m["kind"] == "video"))
    fid = ws.targets()[0]["id"]
    ws.set_parameters({"FaceRestorerEnableToggle": False}, face_id=fid)
    ws.add_marker(0)
    ws.set_parameters({"FaceRestorerEnableToggle": True}, face_id=fid)
    ws.add_marker(10)
    assert ws.markers() == [0, 10]
    ws.preview(2, follow_markers=True)
    assert ws.get_parameters(fid)["face"]["FaceRestorerEnableToggle"] is False
    ws.preview(12, follow_markers=True)
    assert ws.get_parameters(fid)["face"]["FaceRestorerEnableToggle"] is True
    step("markers follow on seek")
    ws.add_segment(2, 4)
    ws.add_segment(10, 14)
    job = ws.export()
    (done,) = wait([job["id"]])
    assert done.state == "done", done.message
    frames = _count_frames(Path(done.result["path"]))
    assert frames == 8, frames
    step("multi-segment export", frames=frames, seconds=done.result["seconds"])
    ws.clear_segments()
    jobs = ws.export_all()
    finished = wait([j["id"] for j in jobs])
    assert all(j.state == "done" for j in finished), [j.message for j in finished]
    step("batch export all media", outputs=[Path(j.result["path"]).name for j in finished])

    # DFM import into the temporary model folder
    fake = tmp / "custom.dfm"
    fake.write_bytes(b"not a real model")
    r = ws.import_dfm([str(fake), str(tmp / "nope.txt")])
    assert r["added"] == ["custom.dfm"] and r["failed"] and "custom.dfm" in r["models"]
    options = next(f for s in ws.schema()["sections"] for f in s["fields"] if f["key"] == "DFMModelSelection")["options"]
    assert "custom.dfm" in options
    step("DFM import lists the model")

    # Re-aging requires its model; report instead of failing when it is absent.
    ws.set_parameters({"FaceReagingEnableToggle": True}, face_id=fid)
    try:
        ws.apply_reaging(fid)
        step("re-aging apply")
    except ApiError as exc:
        step("re-aging apply not verified", reason=str(exc))
    result["ok"] = True
except Exception as exc:  # noqa: BLE001
    import traceback

    traceback.print_exc()
    result.update(ok=False, error=repr(exc))
finally:
    ws.shutdown()
    (OUT / "features.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    shutil.rmtree(tmp, ignore_errors=True)
sys.exit(0 if result.get("ok") else 1)
