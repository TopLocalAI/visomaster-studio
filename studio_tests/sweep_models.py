"""Download every catalogued model, then render one image per model/feature.

Usage: .venv-studio/bin/python studio_tests/sweep_models.py <output dir> [--no-download]

Checks that each model downloads, verifies, loads and produces a processed image
without error. Writes result.json plus one JPEG per case. It does not judge
identity transfer quality: the synthetic target and reference are the same
fictional person.
"""
import json
import os
import sys
import threading
import time
from pathlib import Path

import cv2
import numpy as np

DESKTOP = Path(__file__).resolve().parents[1]
ROOT = DESKTOP.parent
OUT = Path(sys.argv[1]).resolve()
OUT.mkdir(parents=True, exist_ok=True)
DOWNLOAD = "--no-download" not in sys.argv
sys.path.insert(0, str(DESKTOP))
os.chdir(DESKTOP)

from app.backend.service import Workspace, ApiError  # noqa: E402

PORTRAIT = str(ROOT / "design/assets/synthetic-portrait.png")
REFERENCE = str(ROOT / "benchmarks/studio-complete-2026-10-06/second-reference.png")
log = open(OUT / "sweep.log", "a", encoding="utf-8")


def note(*parts):
    line = " ".join(str(p) for p in parts)
    print(line, flush=True)
    log.write(line + "\n")
    log.flush()


ws = Workspace(lambda e, d: None)
result = {"started": time.strftime("%Y-%m-%d %H:%M:%S"), "downloads": [], "cases": []}
RESUME = "--resume" in sys.argv
if RESUME and (OUT / "result.json").is_file():
    result = json.loads((OUT / "result.json").read_text())
done_cases = {(c["group"], c["name"]) for c in result["cases"]} if RESUME else set()

# ---------------------------------------------------------------- downloads
if DOWNLOAD:
    from app.studio.catalog import RESOURCES

    for r in RESOURCES:
        if not ws._missing([r.id]):
            continue
        t = time.time()
        try:
            ws._ensure_resources([r.id], cancel=threading.Event())
            status = "ok"
        except Exception as exc:  # noqa: BLE001 - record and continue
            status = f"failed: {exc}"
        result["downloads"].append({"id": r.id, "mb": round(r.size / 1e6), "seconds": round(time.time() - t, 1), "status": status})
        note("download", r.id, status, f"{round(time.time() - t, 1)}s")
        (OUT / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=1))

# -------------------------------------------------------------------- sweep
ws.start_engine()
host = ws.host
img = ws.add_media([PORTRAIT])[0]
ws.select_media(img["id"])
src = ws.add_sources([REFERENCE])["added"][0]
face_id = ws.targets()[0]["id"]
source = cv2.imread(PORTRAIT)
defaults_face = dict(host.schema["defaults"]["face"])
defaults_global = dict(host.control)
baseline = None


def case(group, name, face=None, control=None, after=None):
    global baseline
    if (group, name) in done_cases and group != "baseline":
        return
    if (group, name) in done_cases:
        result["cases"] = [c for c in result["cases"] if (c["group"], c["name"]) != (group, name)]
    host.face_parameters(face_id).data.clear()
    host.face_parameters(face_id).data.update(defaults_face)
    host.control.clear()
    host.control.update(defaults_global)
    if face:
        host.face_parameters(face_id).data.update(face)
    if control:
        host.control.update(control)
    with ws.engine_lock:
        host.refresh_assignments()
    entry = {"group": group, "name": name}
    t = time.perf_counter()
    try:
        if after:
            after()
        with ws.engine_lock:
            out = host.render(source, 0)
        entry["ms"] = round((time.perf_counter() - t) * 1000)
        entry["size"] = list(out.shape[:2])
        if out.shape == source.shape:
            entry["diff_source"] = round(float(np.abs(out.astype(int) - source).mean()), 3)
            if baseline is not None and out.shape == baseline.shape:
                entry["diff_baseline"] = round(float(np.abs(out.astype(int) - baseline).mean()), 3)
        h, w = out.shape[:2]
        scale = 900 / max(h, w)
        cv2.imwrite(str(OUT / f"{group}--{name}.jpg".replace(" ", "_").replace("/", "_")),
                    cv2.resize(out, (int(w * scale), int(h * scale))), [cv2.IMWRITE_JPEG_QUALITY, 88])
        entry["status"] = "ok"
        if group == "baseline":
            baseline = out
    except Exception as exc:  # noqa: BLE001
        entry["status"] = f"error: {str(exc)[:300]}"
        entry["ms"] = round((time.perf_counter() - t) * 1000)
    result["cases"].append(entry)
    note(group, name, entry["status"], entry.get("ms"), "ms", entry.get("diff_source", ""))
    (OUT / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=1))


field = {f["key"]: f for s in host.schema["sections"] for f in s["fields"]}
opts = lambda k: field[k]["options"]

case("baseline", "Inswapper128")
for m in opts("SwapModelSelection"):
    if m != "DeepFaceLive (DFM)":
        case("swapper", m, face={"SwapModelSelection": m})
for r in opts("FaceRestorerTypeSelection"):
    case("restorer", r, face={"FaceRestorerEnableToggle": True, "FaceRestorerTypeSelection": r})
for e in opts("FrameEnhancerTypeSelection"):
    case("frame-enhancer", e, control={"FrameEnhancerEnableToggle": True, "FrameEnhancerTypeSelection": e})
for d in ("RetinaFace", "Yolov8", "SCRFD", "Yunet"):
    case("detector", d, control={"DetectorModelSelection": d})
for lm in opts("LandmarkDetectModelSelection"):
    case("landmarks", lm, control={"LandmarkDetectToggle": True, "LandmarkDetectModelSelection": lm})
for rec in opts("RecognitionModelSelection"):
    case("recognition", rec, control={"RecognitionModelSelection": rec})
case("mask", "occluder", face={"OccluderEnableToggle": True})
case("mask", "xseg", face={"DFLXSegEnableToggle": True})
case("mask", "face-parser", face={"FaceParserEnableToggle": True})
case("mask", "clip-text", face={"ClipEnableToggle": True, "ClipText": "glasses"})
case("mask", "border", face={"BordermaskEnableToggle": True})
case("color", "texture-transfer", face={"TransferTextureEnableToggle": True})
case("color", "differencing", face={"DifferencingEnableToggle": True})
case("blend", "final-blend", face={"FinalBlendAdjEnableToggle": True, "FinalBlendAmountSlider": 50})
case("expression", "liveportrait", face={"FaceExpressionEnableBothToggle": True})
for mode in opts("FaceExpressionModeSelection") if "FaceExpressionModeSelection" in field else []:
    case("expression", f"mode-{mode}", face={"FaceExpressionEnableBothToggle": True, "FaceExpressionModeSelection": mode})
case("face-editor", "eyes-open", face={"FaceEditorEnableToggle": True, "EyesOpenRatioDecimalSlider": 0.5}, control=None)
case("face-editor", "makeup", face={"FaceMakeupEnableToggle": True})
case("denoiser", "ref-ldm-before", control={"DenoiserUNetEnableBeforeRestorersToggle": True})
case("strength", "likeness", face={"FaceLikenessEnableToggle": True})
case("reaging", "apply", face={"FaceReagingEnableToggle": True, "FaceReagingTargetAgeSlider": 70},
     after=lambda: ws.apply_reaging(face_id))

ok = sum(c["status"] == "ok" for c in result["cases"])
result["summary"] = {"cases": len(result["cases"]), "ok": ok, "errors": len(result["cases"]) - ok,
                     "download_failures": [d["id"] for d in result["downloads"] if d["status"] != "ok"]}
result["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")
(OUT / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=1))
note("summary", result["summary"])
ws.shutdown()
os._exit(0)
