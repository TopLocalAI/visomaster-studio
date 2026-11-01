"""Real-model recovery, settings, repeated export and persisted history checks."""
import hashlib
import json
import sys
import time
from pathlib import Path
from unittest.mock import patch
from PySide6 import QtCore as C, QtGui as G, QtWidgets as W, QtTest
from app.studio.window import StudioWindow
from app.studio.config import data_root

root = Path(__file__).resolve().parents[2]
out = root/'benchmarks/studio-regression-2026-10-06/recovery'
out.mkdir(parents=True, exist_ok=True)
app = W.QApplication([])
app.setQuitOnLastWindowClosed(False)
errors = []
sys.excepthook = lambda kind, value, tb: errors.append(f'{kind.__name__}: {value}')
checks = []
window = None
start = time.monotonic()


def wait(predicate, timeout=75):
    deadline = time.monotonic()+timeout
    while not predicate():
        QtTest.QTest.qWait(50)
        if errors:
            raise AssertionError(errors)
        if time.monotonic() >= deadline:
            raise AssertionError(f'Timeout: {window.notice.text()}')


def close_window():
    window.close()
    wait(lambda: not window.worker and not window._retired, 10)
    QtTest.QTest.qWait(30)


def open_window():
    global window
    window = StudioWindow(out/'session')
    window.settings.model_dir = data_root()/'models'
    window.settings.output_dir = out/'exports'
    window.show()
    QtTest.QTest.qWait(50)
    wait(lambda: not window.worker)


result = {'ok': False, 'checks': checks}
try:
    blank = G.QImage(320, 240, G.QImage.Format_RGB32)
    blank.fill(G.QColor('#555555'))
    blank.save(str(out/'no-face.png'))
    portrait = root/'design/assets/synthetic-portrait.png'
    original_hash = hashlib.sha256(portrait.read_bytes()).hexdigest()
    open_window()
    # Real no-face failures must recover without a restart or a phantom result.
    window.select_asset(str(out/'no-face.png'), True)
    window.select_asset(str(portrait))
    window.start_processing()
    wait(lambda: not window._busy_preview and not window.process)
    assert not window.export_action.isEnabled()
    assert '人脸' in window.notice.text()
    wait(lambda: not window._retired)
    checks.append('no-face reference rejected')
    window.select_asset(str(portrait), True)
    window.select_asset(str(out/'no-face.png'))
    window.start_processing()
    wait(lambda: not window._busy_preview and not window.process)
    assert not window.export_action.isEnabled()
    wait(lambda: not window._retired)
    checks.append('no-face target rejected')

    window.select_asset(str(portrait))
    window.start_processing()
    wait(lambda: window.export_action.isEnabled())
    assert len([w for w in app.topLevelWidgets() if w.isVisible() and isinstance(w, W.QMainWindow)]) == 1
    engine = window.process
    revision = window._valid_revision
    window.settings_action.click()
    assert window.settings_drawer.isVisible() and window.editor.isVisible()
    assert not window.findChildren(W.QFrame, 'rail')
    with patch.object(W.QFileDialog, 'getExistingDirectory', return_value=''):
        window.change_directory('output_dir')
    assert window.process is engine and window._valid_revision == revision
    window.settings_tabs.setCurrentIndex(1)
    assert window.model_rows and not window.advanced.isVisible()
    window.settings_tabs.setCurrentIndex(0)
    assert window.advanced.isVisible()
    window.similarity.setValue(61)
    assert not window.export_action.isEnabled()
    QtTest.QTest.keyClick(window, C.Qt.Key_Escape)
    assert not window.settings_drawer.isVisible()
    window.start_processing()
    wait(lambda: window.export_action.isEnabled())
    checks.append('recovery + settings drawer preserves task; changed advanced parameter requires preview')
    window.set_view('compare')
    window.resize(1000, 720)
    QtTest.QTest.qWait(30)
    window.grab().save(str(out/'workspace.png'))
    # Confirm two independent outputs, not the old output being reused as success.
    before = len(window._records)
    for i in range(2):
        window.export()
        wait(lambda: len(window._records) == before+i+1 and not window._exporting)
    paths = [Path(record['path']) for record in window._records[-2:]]
    assert paths[0] != paths[1] and all(p.is_file() for p in paths)
    expected = G.QImageReader(str(portrait)).size()
    assert all(G.QImageReader(str(path)).size() == expected for path in paths)
    assert hashlib.sha256(portrait.read_bytes()).hexdigest() == original_hash
    checks.append('repeated exports are unique, full resolution, original input unchanged')
    close_window()
    open_window()
    assert all(str(path) in [r['path'] for r in window._records] for path in paths)
    window.history_action.click()
    assert window.settings_tabs.currentIndex() == 2
    item = window.queue.item(0)
    with patch.object(G.QDesktopServices, 'openUrl', return_value=True) as opener:
        window.open_record(item)
        assert opener.call_count == 1
    # Move only this test's own output to check the missing-file UI.
    moved = Path(item.data(C.Qt.UserRole))
    moved.rename(moved.with_suffix('.moved.png'))
    window.open_record(item)
    assert '移动或删除' in window.queue_status.text()
    checks.append('history survives restart; open action dispatches; missing result reported')
    window.grab().save(str(out/'history.png'))
    result.update(ok=True, elapsed_seconds=round(time.monotonic()-start,2), outputs=[str(p) for p in paths])
except Exception:
    import traceback
    result['error'] = traceback.format_exc()
    if window and window.process:
        (out/'diagnostics.txt').write_text(window.process.diagnostics)
finally:
    if window:
        close_window()
(out/'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
print(json.dumps(result, ensure_ascii=False), flush=True)
raise SystemExit(0 if result['ok'] else 1)
