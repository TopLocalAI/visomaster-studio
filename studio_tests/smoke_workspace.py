"""Explicit real-model check of the one-visible-window workflow."""
import argparse
import json
import time
from pathlib import Path
from PySide6 import QtCore as C, QtWidgets as W
from app.studio.window import StudioWindow
from app.studio.config import data_root

parser = argparse.ArgumentParser()
parser.add_argument('--source', required=True)
parser.add_argument('--target', required=True)
parser.add_argument('--output', required=True)
parser.add_argument('--width', type=int, default=1440)
parser.add_argument('--height', type=int, default=940)
parser.add_argument('--frame', type=int, default=0)
args = parser.parse_args()
out = Path(args.output).resolve()
out.mkdir(parents=True, exist_ok=True)
app = W.QApplication([])
w = StudioWindow(out / 'session')
w.settings.model_dir = data_root() / 'models'
w.settings.output_dir = out / 'exports'
w.resize(args.width, args.height)
w.show()
start = time.monotonic()
state = 'check'
result = {'ok': False, 'max_visible_windows': 0, 'ui_ticks': 0}
last_client = None

def tick():
    global state, last_client
    if state == 'aborting':
        if not w._retired and not w.worker:
            app.quit()
        return
    result['ui_ticks'] += 1
    visible = sum(1 for widget in app.topLevelWidgets() if widget.isVisible() and isinstance(widget, W.QMainWindow))
    result['max_visible_windows'] = max(visible, result['max_visible_windows'])
    if w.process:
        last_client = w.process
    if time.monotonic()-start > 210 or (state not in ('check', 'done') and not w._busy_preview and not w._exporting and not w.process):
        result['error'] = w.notice.text()
        if last_client:
            (out / 'diagnostics.txt').write_text(last_client.diagnostics)
        state = 'aborting'
        w.close()
        return
    if state == 'check' and not w.worker:
        w.select_asset(args.source, True)
        w.select_asset(args.target)
        w.seek.setValue(args.frame)
        w.start_processing()
        state = 'preview'
    elif state == 'preview' and w.export_action.isEnabled():
        result['faces'] = w.face_choice.count()
        result['preview_dimensions'] = [w.preview.result.width(), w.preview.result.height()]
        result['provider'] = w.engine_status.text()
        w.set_view('compare')
        w.grab().save(str(out/'workspace.png'))
        w.preview.result.save(str(out/'processed.png'))
        w.preview.original.save(str(out/'original.png'))
        state = 'export'
        w.export()
    elif state == 'export' and w._records and not w._exporting:
        if last_client:
            (out/'diagnostics.txt').write_text(last_client.diagnostics)
        result.update(ok=True, elapsed_seconds=round(time.monotonic()-start,2), output=w._records[-1]['path'])
        w.show_page(2)
        w.grab().save(str(out/'exports.png'))
        state = 'done'
        w.close()
    elif state == 'done' and not w._retired:
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
(out/'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
print(json.dumps(result, ensure_ascii=False), flush=True)
raise SystemExit(0 if result['ok'] else 1)
