"""One verified, cancellable resource path for UI and inference workers."""
from pathlib import Path
import threading
from PySide6 import QtCore as C
from .catalog import BY_ID
from .downloads import Downloader


class Task(C.QThread):
    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self.fn, self.error = fn, None

    def run(self):
        try:
            self.fn()
        except Exception as exc:
            self.error = exc


class ModelService(C.QObject):
    progress = C.Signal(str, str, object, object)
    busy = C.Signal(bool)
    error = C.Signal(str)

    def __init__(self, root, parent=None):
        super().__init__(parent)
        self.root = Path(root)
        self.cancelled = threading.Event()
        self.lock = threading.Lock()
        self.verified = {}
        self.active = 0

    def prepare(self, names, source=None):
        """Called from any thread. GUI callers keep the event loop responsive."""
        def work():
            with self.lock:
                if self.cancelled.is_set():
                    raise InterruptedError('已暂停，请重试')
                self.busy.emit(True)
                try:
                    resources = [BY_ID[name] for name in names]
                    needed = []
                    for r in resources:
                        path = r.path(self.root)
                        stat = path.stat() if path.exists() else None
                        stamp = (stat.st_size, stat.st_mtime_ns) if stat else None
                        if source or not stamp or self.verified.get(r.id) != stamp:
                            needed.append(r)
                    downloader = Downloader(self.root, self.cancelled, self.progress.emit)
                    if source:
                        downloader.import_models(needed, Path(source))
                    elif needed:
                        downloader.prepare(needed)
                    for r in resources:
                        st = r.path(self.root).stat()
                        self.verified[r.id] = (st.st_size, st.st_mtime_ns)
                finally:
                    self.busy.emit(False)
        if C.QThread.currentThread() == self.thread():
            task = Task(work, self)
            loop = C.QEventLoop()
            task.finished.connect(loop.quit)
            task.start()
            loop.exec()
            task.wait()
            error = task.error
            task.deleteLater()
            if error:
                raise error
        else:
            work()

    def ensure(self, name):
        if name not in BY_ID:
            # User-supplied UNet/DFM resources remain managed by the upstream loader.
            return
        self.prepare([name])
