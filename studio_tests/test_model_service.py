import hashlib
import threading
from pathlib import Path
import pytest
from PySide6 import QtCore, QtWidgets
from app.studio.resources import Resource
from app.studio.model_service import ModelService
from app.studio import model_service


@pytest.fixture(scope='module')
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_gui_resource_wait_keeps_event_loop_alive_and_caches_integrity(tmp_path, app, monkeypatch):
    data=b'pinned model'; resource=Resource('unit','unit','nested/model.onnx',len(data),hashlib.sha256(data).hexdigest(),('https://example.com/model',))
    monkeypatch.setitem(model_service.BY_ID,resource.id,resource)
    calls=[]
    def transfer(self,r,url,path):
        import time
        calls.append(threading.get_ident());time.sleep(.06);path.write_bytes(data)
    monkeypatch.setattr(model_service.Downloader,'_transfer',transfer)
    service=ModelService(tmp_path)
    ticks=[];timer=QtCore.QTimer();timer.timeout.connect(lambda:ticks.append(True));timer.start(5)
    service.ensure('unit');timer.stop()
    assert len(ticks)>=2
    assert calls[0] != threading.get_ident()
    service.ensure('unit');assert len(calls)==1
    # Tampering invalidates the remembered verification stamp.
    resource.path(tmp_path).write_bytes(b'broken')
    service.ensure('unit');assert len(calls)==2
    service.cancelled.set()
    with pytest.raises(InterruptedError):service.ensure('unit')
    service.cancelled.clear();service.ensure('unit')


def test_auxiliary_files_are_hash_verified_and_outside_bundle(tmp_path):
    from app.studio.auxiliary import install_auxiliary,HASHES
    install_auxiliary(tmp_path)
    for name, expected in HASHES.items():
        assert hashlib.sha256((tmp_path/name).read_bytes()).hexdigest()==expected
