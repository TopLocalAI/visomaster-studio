"""Real inference/export cancellation, process-tree cleanup, and asset replacement."""
import argparse
import json
import time
from pathlib import Path
import psutil
from PySide6 import QtCore as C, QtWidgets as W
from app.studio.window import StudioWindow
from app.studio.config import data_root

root = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser()
parser.add_argument('--output', default=str(root / 'benchmarks/studio-single-window/lifecycle'))
args = parser.parse_args()
out = Path(args.output).resolve()
out.mkdir(parents=True, exist_ok=True)
app = W.QApplication([])
w = StudioWindow(out/'session')
w.settings.model_dir = data_root()/'models'
w.settings.output_dir = out/'exports'
w.show()
start = time.monotonic()
state = 'check'
pids = []
result = {'ok': False}
export_started = 0
old_path = None
client = None

def tick():
    global state, export_started, old_path, client
    if state == 'aborting':
        if not w._retired and not w.worker:
            app.quit()
        return
    if time.monotonic()-start > 150:
        result['error'] = w.notice.text()
        if client:
            (out/'diagnostics.txt').write_text(client.diagnostics)
        state = 'aborting'
        w.close()
        return
    if state == 'check' and not w.worker:
        w.select_asset(str(root/'design/assets/synthetic-portrait.png'), True)
        w.select_asset(str(root/'benchmarks/studio-smoke/video-input/sample-short.mp4'))
        w.start_processing()
        client = w.process
        old_path = client.work
        state = 'cancel-start'
    elif state == 'cancel-start' and client.process.processId():
        pids.append(int(client.process.processId()))
        w.cancel_operation()
        state = 'wait-stop'
    elif state == 'wait-stop' and not w._retired:
        assert not old_path.exists()
        assert not any(psutil.pid_exists(pid) for pid in pids)
        result['startup_cancel'] = True
        # Start a new task; the old session must never update its result.
        w.select_asset(str(root/'benchmarks/studio-smoke/video-input/sample-short.mp4'))
        w.start_processing()
        client = w.process
        state = 'preview'
    elif state == 'preview' and w.export_action.isEnabled():
        w.set_preset(1)
        w.edge.setValue(15)
        w.seek.setValue(3)
        assert not w.export_action.isEnabled()
        w.start_processing()
        state = 'seek'
    elif state == 'seek' and w.export_action.isEnabled():
        result['seek_frame'] = w.seek.value()
        result['seek_preview_valid'] = w._valid_revision == w._revision
        result['parameters'] = w.options()
        w.export()
        export_started = time.monotonic()
        state = 'export'
    elif state == 'export':
        proc = psutil.Process(int(client.process.processId()))
        children = proc.children(recursive=True)
        if any('ffmpeg' in child.name().lower() for child in children) and time.monotonic()-export_started > 1:
            pids.extend([proc.pid, *[child.pid for child in children]])
            old_path = client.work
            w.cancel_operation()
            state = 'cancel-export'
    elif state == 'cancel-export' and not w._retired:
        assert not w._records
        assert not old_path.exists()
        live = [pid for pid in pids if psutil.pid_exists(pid) and psutil.Process(pid).status() != psutil.STATUS_ZOMBIE]
        assert not live, live
        result.update(ok=True, export_cancel=True, no_orphan_processes=True, no_published_partial_output=True,
                      elapsed_seconds=round(time.monotonic()-start,2))
        w.select_asset(str(root/'design/assets/synthetic-portrait.png'))
        assert w.start_button.isEnabled()
        assert not w.export_action.isEnabled()
        result['new_asset_ready'] = True
        w.grab().save(str(out/'after-cancel.png'))
        w.close()
        app.quit()

def guarded_tick():
    global state
    try:
        tick()
    except Exception:
        import traceback
        result['error'] = traceback.format_exc()
        state = 'aborting'
        w.close()


timer = C.QTimer()
timer.timeout.connect(guarded_tick)
timer.start(100)
app.exec()
(out/'result.json').write_text(json.dumps(result, indent=2))
print(json.dumps(result), flush=True)
raise SystemExit(0 if result['ok'] else 1)
