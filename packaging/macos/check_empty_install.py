"""No-model, clean-settings UI check with the packaged interpreter."""
import json
import os
from pathlib import Path
import sys
import tempfile
from PySide6 import QtCore as C, QtWidgets as W
from app.studio.window import StudioWindow
out=Path(sys.argv[sys.argv.index('--output')+1]);out.mkdir(parents=True,exist_ok=True)
with tempfile.TemporaryDirectory(prefix='studio-clean-install-') as tmp:
    app=W.QApplication([]);w=StudioWindow(Path(tmp));w.show()
    def check():
        if w.worker:return
        assert not w.ready
        assert not w.export_action.isEnabled()
        assert len([x for x in app.topLevelWidgets() if isinstance(x,W.QMainWindow) and x.isVisible()])==1
        w.show_page(1)
        w.grab().save(str(out/'models.png'))
        (out/'result.json').write_text(json.dumps({'ok':True,'no_models':True,'single_window':True,'export_disabled':True,'python_bundled':'.app/Contents/' in sys.executable}))
        w.close();app.quit()
    timer=C.QTimer();timer.timeout.connect(check);timer.start(100)
    C.QTimer.singleShot(15000,app.quit)
    app.exec()
    assert (out/'result.json').exists()
