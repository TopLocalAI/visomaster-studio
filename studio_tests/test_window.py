import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import subprocess
import sys
import time
from pathlib import Path

from PySide6 import QtGui, QtWidgets, QtTest
import pytest
from app.studio.window import StudioWindow


@pytest.fixture(scope='module')
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def window(tmp_path, app):
    w = StudioWindow(tmp_path)
    w.show()
    deadline = time.monotonic() + 5
    app.processEvents()
    while w.worker and time.monotonic() < deadline:
        QtTest.QTest.qWait(10)
    assert w.worker is None
    yield w
    if w.worker:
        w.worker.cancelled.set()
        w.worker.wait(2000)
        app.processEvents()
    w.close()


def test_shell_import_does_not_load_inference_or_request_network():
    code = '''
import sys
import socket
socket.socket.connect = lambda *args: (_ for _ in ()).throw(AssertionError('unexpected network'))
from app.studio.window import StudioWindow
assert not any(m in sys.modules for m in ('torch','onnxruntime','cv2'))
'''
    subprocess.run([sys.executable, '-c', code], check=True)


def test_import_two_images_enables_action_and_invalid_file_does_not_replace(window, tmp_path):
    source = tmp_path / '人脸 照片.png'
    target = tmp_path / 'target.png'
    img = QtGui.QImage(64, 64, QtGui.QImage.Format_RGB32)
    img.fill(QtGui.QColor('teal'))
    assert img.save(str(source)) and img.save(str(target))
    assert not window.start_button.isEnabled()
    window.select_asset(str(source), True)
    assert not window.start_button.isEnabled()
    window.select_asset(str(target))
    assert window.start_button.isEnabled()
    assert not window.preview.pixmap().isNull()
    broken = tmp_path / 'broken.png'
    broken.write_bytes(b'bad image')
    window.select_asset(str(broken))
    assert window.target == target
    assert '无法打开' in window.notice.text()


def test_missing_models_are_not_marked_ready(window):
    assert window.ready == set()
    assert all(status.text() == '未准备' for status, _ in window.model_rows.values())
    assert not window.pause_button.isEnabled()


def test_navigation_preserves_selected_media(window, tmp_path):
    video = tmp_path / 'clip.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=blue:s=64x64:r=4:d=1', '-c:v', 'libx264', '-y', str(video)], check=True)
    window.select_asset(str(video))
    window.show_page(1)
    window.show_page(2)
    window.show_page(0)
    assert window.target == video
    assert window.target_button.text() == 'clip.mp4'


def test_corrupt_video_does_not_replace_existing_media(window, tmp_path):
    path = tmp_path / 'bad.mp4'
    path.write_bytes(b'not a video')
    window.select_asset(str(path))
    assert window.target is None
    assert '无法打开' in window.notice.text()


def test_parameter_change_invalidates_export_and_comparison(window):
    image = QtGui.QImage(20, 20, QtGui.QImage.Format_RGB32)
    image.fill(QtGui.QColor('red'))
    window.preview.original = image
    window.preview.result = image
    window._valid_revision = window._revision
    window.export_action.setEnabled(True)
    window.view_buttons['compare'].setEnabled(True)
    window.set_view('compare')
    window.edge.setValue(15)
    assert not window.export_action.isEnabled()
    assert window.preview.mode == 'original'
    assert window.preview.result.isNull()
    assert not window.view_buttons['compare'].isEnabled()


def test_old_session_and_revision_cannot_replace_current_preview(window):
    class Client:
        pass
    old, current = Client(), Client()
    window.process = current
    window.engine_event(old, {'type': 'error', 'text': 'old failure'})
    assert window.process is current
    window.engine_event(current, {'type': 'preview', 'request': -1, 'image': 'bad'})
    assert window.preview.result.isNull()
    window.process = None


def test_compare_and_navigation_never_create_another_window(window, app):
    for index in range(4):
        window.show_page(index)
    windows = [w for w in app.topLevelWidgets() if w.isVisible() and isinstance(w, QtWidgets.QMainWindow)]
    assert windows == [window]


def test_video_plays_and_keyboard_seek_invalidates_result(window, tmp_path):
    video = tmp_path / 'play.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc=size=64x64:rate=8:duration=2', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-y', str(video)], check=True)
    window.select_asset(str(video))
    window.play()
    QtTest.QTest.qWait(600)
    assert window._player.position() > 0
    assert window.seek.value() > 0
    window.pause_playback()
    window._valid_revision = window._revision
    window.export_action.setEnabled(True)
    window.seek.setValue(1)
    assert window._valid_revision != window._revision
    assert not window.export_action.isEnabled()


def test_multiple_faces_wait_for_explicit_selection(window):
    class Client:
        def send(self, command):
            raise AssertionError('Must not select a face automatically')
    client = Client()
    window.process = client
    window.engine_event(client, {'type': 'ready', 'sources': 1,
        'faces': [{'id': 'a', 'image': ''}, {'id': 'b', 'image': ''}]})
    assert window.face_choice.currentIndex() == -1
    assert window.face_choice.isEnabled()
    assert not window.start_button.isEnabled()
    assert not window.export_action.isEnabled()
    window.process = None


def test_cancel_directory_picker_preserves_preview_and_engine(window, monkeypatch):
    class Client:
        cancelled = False
        def cancel(self):
            self.cancelled = True
    client = Client()
    window.process = client
    window._valid_revision = window._revision
    monkeypatch.setattr(QtWidgets.QFileDialog, 'getExistingDirectory', lambda *a: '')
    try:
        window.change_directory('output_dir')
        assert window.process is client
        assert not client.cancelled
        assert window._valid_revision == window._revision
    finally:
        window.process = None
        window._retired.clear()


def test_missing_video_duration_is_reported_without_exception(window, tmp_path, monkeypatch):
    video = tmp_path / 'stream.mp4'
    video.write_bytes(b'stream')
    response = subprocess.CompletedProcess([], 0, b'{"streams":[{"avg_frame_rate":"4/1"}],"format":{}}')
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: response)
    window.select_asset(str(video))
    assert window.target is None
    assert '视频无法打开' in window.notice.text()


def test_delayed_video_frame_cannot_overwrite_a_new_image(window, tmp_path):
    still = QtGui.QImage(20, 20, QtGui.QImage.Format_RGB32)
    still.fill(QtGui.QColor('green'))
    path = tmp_path / 'new-image.png'
    still.save(str(path))
    window.select_asset(str(path))
    class LateFrame:
        def toImage(self):
            old = still.copy()
            old.fill(QtGui.QColor('red'))
            return old
    window.video_frame(LateFrame())
    assert window.preview.original.pixelColor(0, 0) == QtGui.QColor('green')


def test_open_output_handles_unwritable_location(window, tmp_path):
    blocked = tmp_path / 'is-a-file'
    blocked.write_text('keep')
    window.settings.output_dir = blocked
    window.open_output()
    assert blocked.read_text() == 'keep'
    assert '无法打开' in window.queue_status.text()


def test_settings_keyboard_focus_stays_in_drawer(window, app):
    from PySide6 import QtCore
    window.settings_action.click()
    for _ in range(30):
        QtTest.QTest.keyClick(app.focusWidget() or window, QtCore.Qt.Key_Tab)
        assert window.settings_drawer.isAncestorOf(app.focusWidget())
    QtTest.QTest.keyClick(window, QtCore.Qt.Key_Escape)
    assert not window.settings_drawer.isVisible()
