> Historical implementation notes (0.2.x and early 0.3 development). For the published 0.3.0 build, use [README.md](README.md) and [BUILDING.md](BUILDING.md). Statements below about unpublished or unfinished packaging are historical.

# VisoMaster Studio

Studio 0.2.0, based on Fusion v3.12.3 (`9f9dd96dafc2c8a13469566bf6ef16ae09106627`). GPL-3.0 and upstream attribution retained.

## Run

Use `启动 VisoMaster Studio.command`, or `.venv-studio/bin/python studio.py`.
The macOS Python 3.12 environment is pinned in `requirements_studio_macos_dev.lock`; FFmpeg/FFprobe are also required. `requirements_studio.txt` is only the old lightweight shell's dependency subset, not a complete inference environment. Windows has not been validated.

## Workspace

The default entry now uses `app/studio/workspace.py`, a PySide6 workspace over Fusion's complete `MainWindow` controller. Original parameter widgets and callbacks are reused, sharing the same per-face state with previews, exports, markers, jobs, presets and projects. Simplification must not remove processing capabilities.

The main window shows media, reference faces, target faces, viewer, timeline and export. A single target/reference pair is assigned automatically. Multiple faces require explicit assignment. Advanced controls, model downloads, runtime/output settings, presets, job queue, embedding editor and export history open inside the same window. Professional timeline controls are under More; the viewer retains its native zoom, pan and context-menu controls.

Restored features include all 427 native parameter controls: multiple swappers/DFM, restoration, upscaling, masks, color and blending, expression/pose, ReF-LDM, detection/tracking, VR, webcam/virtual-camera options, timeline markers/segments and batch jobs. This means access to the existing implementation, not validation of every model or platform. Webcam recording remains unsupported by the upstream controller; virtual-camera output requires an installed platform backend.

## Resources and environment

`catalog.py` pins 75 upstream resources plus the mouth-action detector and two ReF-LDM extraction checkpoints, including byte counts, SHA-256 and official source URLs. `model_service.py` prepares missing resources on demand, with cancellable progress. Existing verified resources are cached by file size/mtime; changed files are reverified. The shared downloader supports safe nested paths, strict resume, hash validation, atomic publication, import and source fallback. Most resources currently have one registered upstream URL; do not claim multiple independent mirrors have been deployed.

Small upstream geometry/reference tables and YAML configuration files (about 1 MB) are bundled under `app/studio/data` and copied with hash checks into the model directory. ONNX/PTH/checkpoint inference weights are not included in the app. TensorFlow and PyTorch Lightning are included in the full runtime for the previously inaccessible advanced features.

Models, jobs, presets, workspaces, thumbnails, temporary outputs and caches remain in writable user data, outside the signed app. The previous `exports.json` history is retained. Model location changes take effect after restart.

## Processing

Images export asynchronously and are checked before success is reported. Comparison views are excluded from image exports and restored afterward. Video export normally covers the whole clip; explicit segments and native output options remain available. Errors and cancellation are visible in the main window. Closing waits for owned resource/preview workers rather than destroying widgets while workers still run.

A Studio-specific guard separates queued single-frame previews from default recording. This fixes a batch transition race that could encode an extra preview frame. Segment bootstrap frames remain accepted.

The earlier `window.py` / offscreen `engine.py` implementation remains as a regression reference; `--engine` is retained for its automated tests. It is no longer the default user workspace.

## Validation and limits

Automated tests cover downloads/resume/integrity/path traversal, resource preparation responsiveness, queued preview isolation, export checks and prior engine regressions. Real-model smoke scripts are `studio_tests/smoke_complete.py` and `studio_tests/smoke_queue.py` (synthetic assets in the parent workspace).

Current macOS CPU verification includes base swapping, GFPGAN restoration, image export, multiple reference assignment, project save/restore, in-window advanced/embedding routes, full-length video with frame/audio validation and queued exports. Mouth-action TensorFlow and ReF-LDM extraction models have been loaded successfully. Full LivePortrait/PerformRecast/VR/DFM output coverage, physical cameras, Windows/NVIDIA/TensorRT and broader media/hardware matrices still require dedicated validation. No speed or quality superiority over upstream is claimed.

Mac builds are local artifacts, not website deployments or public releases. A package must pass signing, notarization and Gatekeeper checks before it is described as notarized. Model redistribution/commercial license review remains separate from application GPL compliance.

## 0.2.1 界面整理

紧凑工具栏、列表式素材和小型人脸卡片替代大标题与套框；右侧设置与预览并排，不遮挡画面。图片不显示视频控制，视频保留完整时间线、播放及片段工具。原有控制器、427项参数与模型清单不变。文件名省略显示，悬停可看完整路径；列表已有内容时隐藏空状态提示。

实际界面/导出验证位于工作区 `benchmarks/studio-ui-2026-10-06`。

## New desktop app (0.3, in development)

`studio-ui/` is the new single-window app (Tauri 2 + React + TypeScript). It drives `app/backend/`, a processing backend with no Qt widgets that reuses Fusion's processors through a headless host. The backend listens on 127.0.0.1 with a per-launch token and exits when the app closes.

- Run: `cd studio-ui && pnpm install && pnpm tauri dev` (uses `.venv-studio`).
- Tests: `studio_tests/test_backend_*.py`; UI flow `studio-ui/tests/ui-flow.mjs` (Playwright WebKit against a real backend).
- Not yet in the new app: projects/presets, markers UI, multi-segment ranges, issue scan, face library/embedding editor, DFM import, re-aging apply, webcam/virtual camera, packaging. The Qt workspace above remains the reference for those until migrated.
