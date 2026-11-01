"""Exercise process lifetime and cancellation before a worker has a PID."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import time
import pytest
from PySide6 import QtWidgets, QtTest
from app.studio.engine_client import EngineClient


def test_cancel_during_starting_reaps_worker_and_private_output(tmp_path):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    client = EngineClient(tmp_path/'face.png', tmp_path/'video.mp4', tmp_path/'models', tmp_path, tmp_path/'out')
    staging = client.work
    client.cancel()
    deadline = time.monotonic()+5
    while not client.finished and time.monotonic() < deadline:
        QtTest.QTest.qWait(10)
    assert client.finished
    assert client.process.state() == client.process.ProcessState.NotRunning
    assert not staging.exists()
    client.deleteLater()
    app.processEvents()


@pytest.mark.skipif(os.name == "nt", reason="POSIX process groups")
def test_cleanup_waits_for_encoder_before_removing_work(tmp_path, monkeypatch):
    from PySide6 import QtCore
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    client = EngineClient.__new__(EngineClient)
    QtCore.QObject.__init__(client)
    client.work = tmp_path/'owned-session'
    client.work.mkdir()
    client._owned_group = 123456
    client._cleanup_attempts = 0
    client.diagnostics = ''
    client.finished = False
    calls = []
    def group_signal(pid, sig):
        calls.append(pid)
        if len(calls) > 1:
            raise ProcessLookupError()
    monkeypatch.setattr(os, 'killpg', group_signal)
    client.cleanup()
    assert client.work.is_dir() and not client.finished
    (client.work/'late-encoder-write.mp4').write_bytes(b'partial')
    deadline = time.monotonic()+2
    while not client.finished and time.monotonic() < deadline:
        QtTest.QTest.qWait(10)
    assert client.finished and not client.work.exists()
    client.deleteLater()
    app.processEvents()
