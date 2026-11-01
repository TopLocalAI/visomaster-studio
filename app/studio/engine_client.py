"""Asynchronous, cancellable owner of an offscreen processing session."""
import json
import os
from pathlib import Path
import signal
import sys
import tempfile
import shutil
from PySide6 import QtCore as C


class EngineClient(C.QObject):
    event = C.Signal(dict)
    stopped = C.Signal()

    def __init__(self, source, target, model_dir, root, output_dir, parent=None, frame=0):
        super().__init__(parent)
        self.root = Path(root)
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        self.work = Path(tempfile.mkdtemp(prefix='.studio-session-', dir=output_dir))
        self.process = C.QProcess(self)
        self.process.setWorkingDirectory(str(self.work))
        self.process.setProgram(sys.executable)
        self.process.setArguments([str(Path(__file__).resolve().parents[2] / 'studio.py'), '--engine', '--source', str(source), '--target', str(target), '--output', str(self.work), '--frame', str(frame)])
        env = C.QProcessEnvironment.systemEnvironment()
        env.insert('VISOMASTER_MODELS_DIR', str(model_dir))
        env.insert('VISOMASTER_STUDIO_HOME', str(root))
        env.insert('QT_QPA_PLATFORM', 'offscreen')
        self.process.setProcessEnvironment(env)
        self.buffer = bytearray()
        self.diagnostics = ''
        self.closing = False
        self.finished = False
        self._process_ended = False
        self._owned_group = 0
        self._cleanup_attempts = 0
        self.process.readyReadStandardOutput.connect(self.read)
        # Drain diagnostics without logging user media paths or bloating memory.
        self.process.readyReadStandardError.connect(self.read_diagnostics)
        self.process.finished.connect(self.ended)
        self.process.started.connect(self.started)
        self.process.errorOccurred.connect(self.error)
        self.watchdog = C.QTimer(self)
        self.watchdog.setSingleShot(True)
        self.watchdog.timeout.connect(self.timeout)
        self.process.start()
        self.watchdog.start(180000)

    def started(self):
        if self.closing:
            self.stop_process_tree()

    def read_diagnostics(self):
        self.diagnostics = (self.diagnostics + bytes(self.process.readAllStandardError()).decode('utf-8', errors='replace'))[-24000:]

    def send(self, command):
        if not self.closing and self.process.state() == C.QProcess.Running:
            self.process.write((json.dumps(command)+'\n').encode())
            self.watchdog.start(180000)

    def read(self):
        self.buffer.extend(bytes(self.process.readAllStandardOutput()))
        while b'\n' in self.buffer:
            line, _, self.buffer = self.buffer.partition(b'\n')
            if self.closing or not line.startswith(b'STUDIO:'):
                continue
            try:
                event = json.loads(line[7:])
            except ValueError:
                continue
            if os.name != 'nt' and not self._owned_group:
                pid = int(self.process.processId())
                try:
                    if pid and os.getpgid(pid) == pid:
                        self._owned_group = pid
                except ProcessLookupError:
                    pass
            self.watchdog.start(180000)
            if event.get('type') in ('ready', 'preview', 'exported', 'error'):
                self.watchdog.stop()
            self.event.emit(event)

    def timeout(self):
        self.event.emit({'type': 'error', 'text': '处理超时，请重试'})
        self.cancel()

    def error(self, error):
        if not self.closing:
            self.event.emit({'type': 'error', 'text': '处理环境无法启动，请重试' if error == C.QProcess.FailedToStart else '处理意外中断，请重试'})
        if self.process.state() == C.QProcess.NotRunning:
            self.ended(1)

    def cancel(self):
        if self.closing:
            return
        self.closing = True
        self.watchdog.stop()
        self.stop_process_tree()

    def stop_process_tree(self):
        pid = int(self.process.processId())
        if pid:
            if os.name == 'nt':
                import subprocess
                subprocess.Popen(['taskkill', '/PID', str(pid), '/T', '/F'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                try:
                    if os.getpgid(pid) == pid:
                        self._owned_group = pid
                        os.killpg(pid, signal.SIGTERM)
                    else:
                        self.process.terminate()
                except ProcessLookupError:
                    pass
            C.QTimer.singleShot(3000, self.force_stop)
        elif self.process.state() == C.QProcess.NotRunning:
            self.ended(0)
        # Starting has no PID yet: started() will cancel it before any work.

    def force_stop(self):
        if self.finished:
            return
        pid = int(self.process.processId())
        if pid and self.process.state() != C.QProcess.NotRunning:
            if os.name != 'nt':
                try:
                    if os.getpgid(pid) == pid:
                        os.killpg(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            self.process.kill()

    def ended(self, code=0, status=None):
        if self._process_ended:
            return
        self._process_ended = True
        self.watchdog.stop()
        if not self.closing:
            self.event.emit({'type': 'error', 'text': '处理已中断，请重试'})
        self.cleanup()

    def cleanup(self):
        # FFmpeg can outlive its Python parent briefly while handling SIGTERM.
        # Wait for the owned process group before deleting its working directory;
        # otherwise a late encoder write can recreate a supposedly cleaned file.
        self._cleanup_attempts += 1
        group_alive = False
        if self._owned_group and os.name != 'nt':
            try:
                os.killpg(self._owned_group, signal.SIGKILL)
                group_alive = True
            except ProcessLookupError:
                self._owned_group = 0
        if group_alive and self._cleanup_attempts < 60:
            C.QTimer.singleShot(50, self.cleanup)
            return
        shutil.rmtree(self.work, ignore_errors=True)
        if self.work.exists() and self._cleanup_attempts < 60:
            C.QTimer.singleShot(50, self.cleanup)
            return
        if self.work.exists():
            self.diagnostics += '\nSession temporary files could not be removed.'
        self.finished = True
        self.stopped.emit()
