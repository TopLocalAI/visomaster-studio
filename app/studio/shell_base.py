"""Shared window navigation, model preparation, and persistent paths."""
from pathlib import Path
import threading

from PySide6 import QtCore as C, QtGui as G, QtWidgets as W
from .config import Settings, data_root
from .downloads import Downloader, DownloadError
from .resources import BASIC_RESOURCES, verify
from .theme import STYLE

IMAGES = {'.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tif', '.tiff'}
VIDEOS = {'.mp4', '.mov', '.mkv', '.avi', '.webm', '.m4v'}
ROOT = Path(__file__).resolve().parents[2]


class ModelWorker(C.QThread):
    status = C.Signal(str, str, int, int)
    outcome = C.Signal(str)

    def __init__(self, directory, operation, source=None, parent=None):
        super().__init__(parent)
        self.directory, self.operation, self.source = directory, operation, source
        self.cancelled = threading.Event()

    def run(self):
        try:
            downloader = Downloader(self.directory, self.cancelled, self.status.emit)
            if self.operation == 'download':
                downloader.prepare(BASIC_RESOURCES)
            elif self.operation == 'import':
                downloader.import_models(BASIC_RESOURCES, self.source)
            else:
                for r in BASIC_RESOURCES:
                    if self.cancelled.is_set():
                        raise InterruptedError()
                    self.status.emit(r.id, '校验中', 0, r.size)
                    ok = verify(r, r.path(self.directory), self.cancelled.is_set)
                    self.status.emit(r.id, '已就绪' if ok else '未准备', r.size if ok else 0, r.size)
            self.outcome.emit('')
        except InterruptedError:
            self.outcome.emit('已暂停')
        except DownloadError as exc:
            self.outcome.emit(str(exc))
        except (OSError, ValueError):
            self.outcome.emit('无法读取或写入文件，请检查保存位置')
        except Exception:
            self.outcome.emit('准备未完成，请重试')


def button(text, slot=None, primary=False):
    widget = W.QPushButton(text)
    if primary:
        widget.setObjectName('primary')
    if slot:
        widget.clicked.connect(slot)
    return widget


def label(text='', style=''):
    widget = W.QLabel(text)
    widget.setTextFormat(C.Qt.PlainText)
    if style:
        widget.setObjectName(style)
    return widget


def panel():
    frame = W.QFrame()
    frame.setObjectName('panel')
    layout = W.QVBoxLayout(frame)
    layout.setContentsMargins(20, 20, 20, 20)
    layout.setSpacing(16)
    return frame, layout


class AssetButton(W.QPushButton):
    selected = C.Signal(str)

    def __init__(self, text, source=False):
        super().__init__(text)
        self.source = source
        self.setObjectName('asset')
        self.setAcceptDrops(True)
        self.clicked.connect(self.choose)

    def choose(self):
        formats = '图片 (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff)'
        if not self.source:
            formats = '照片与视频 (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff *.mp4 *.mov *.mkv *.avi *.webm *.m4v)'
        path, _ = W.QFileDialog.getOpenFileName(self, self.text(), '', formats)
        if path:
            self.selected.emit(path)

    def dragEnterEvent(self, event):
        urls = event.mimeData().urls()
        if len(urls) == 1 and urls[0].isLocalFile():
            event.acceptProposedAction()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if len(urls) == 1 and urls[0].isLocalFile():
            self.selected.emit(urls[0].toLocalFile())
            event.acceptProposedAction()


class BaseStudioWindow(W.QMainWindow):
    def __init__(self, root=None):
        super().__init__()
        self.root = Path(root) if root else data_root()
        self.settings = Settings.load(self.root)
        self.source = self.target = None
        self.worker = None
        self.process = None
        self.ready = set()
        self.pending_preview = False
        self._worker_error = ''
        self.setWindowTitle('VisoMaster Studio')
        self.resize(1440, 940)
        self.setMinimumSize(1000, 720)
        self.setStyleSheet(STYLE)
        self.engine_status = label('准备开始', 'muted')
        self.editor = self.build_editor()
        self.setCentralWidget(self.editor)

        # Secondary tools are an in-window drawer. The editor never goes away
        # and no permanent navigation column consumes the preview area.
        self.settings_drawer = W.QFrame(self.editor)
        self.settings_drawer.setObjectName('settingsBackdrop')
        self.settings_drawer.installEventFilter(self)
        overlay = W.QHBoxLayout(self.settings_drawer)
        overlay.setContentsMargins(16, 16, 16, 16)
        overlay.addStretch()
        drawer = W.QFrame()
        drawer.setObjectName('settingsDrawer')
        drawer.setFixedWidth(620)
        content = W.QVBoxLayout(drawer)
        content.setContentsMargins(20, 20, 20, 20)
        heading = W.QHBoxLayout()
        heading.addWidget(label('设置', 'title'), 1)
        self.close_settings_button = button('完成', lambda: self.show_page(0))
        heading.addWidget(self.close_settings_button)
        content.addLayout(heading)
        self.settings_tabs = W.QTabWidget()
        self.settings_tabs.addTab(self.build_settings(), '常规')
        self.settings_tabs.addTab(self.build_models(), '模型')
        self.settings_tabs.addTab(self.build_queue(), '导出记录')
        content.addWidget(self.settings_tabs, 1)
        overlay.addWidget(drawer)
        self.settings_drawer.hide()
        self.dismiss_settings = G.QShortcut(G.QKeySequence('Escape'), self)
        self.dismiss_settings.activated.connect(lambda: self.show_page(0))
        self.show_page(0)
        C.QTimer.singleShot(0, lambda: self.run_models('check'))

    def page(self, title):
        widget = W.QWidget()
        layout = W.QVBoxLayout(widget)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(20)
        layout.addWidget(label(title, 'title'))
        return widget, layout

    def build_models(self):
        page, layout = self.page('模型')
        card, contents = panel()
        self.model_rows = {}
        for r in BASIC_RESOURCES:
            row = W.QHBoxLayout()
            row.addWidget(label(r.name), 1)
            row.addWidget(label(f'{r.size / 1024**2:.0f} MB', 'muted'))
            status = label('待检查', 'muted')
            status.setMinimumWidth(92)
            row.addWidget(status)
            contents.addLayout(row)
            progress = W.QProgressBar()
            progress.setRange(0, 1000)
            progress.setValue(0)
            progress.setTextVisible(False)
            contents.addWidget(progress)
            self.model_rows[r.id] = (status, progress)
        layout.addWidget(card)
        self.model_notice = label('', 'notice')
        self.model_notice.setWordWrap(True)
        layout.addWidget(self.model_notice)
        actions = W.QHBoxLayout()
        size = sum(r.size for r in BASIC_RESOURCES) / 1024**2
        self.download_button = button(f'开始准备 · {size:.0f} MB', lambda: self.run_models('download'), True)
        self.import_button = button('导入已有模型', self.import_models)
        self.pause_button = button('暂停', self.pause)
        self.pause_button.setEnabled(False)
        for b in [self.download_button, self.import_button, self.pause_button]:
            actions.addWidget(b)
        actions.addStretch()
        layout.addLayout(actions)
        layout.addStretch()
        return page

    def build_settings(self):
        page, layout = self.page('保存位置')
        card, rows = panel()
        self.path_labels = {}
        self.path_buttons = []
        for key, title in [('model_dir', '模型位置'), ('output_dir', '导出位置')]:
            rows.addWidget(label(title))
            line = W.QHBoxLayout()
            value = label(str(getattr(self.settings, key)), 'muted')
            value.setWordWrap(True)
            line.addWidget(value, 1)
            change = button('更改', lambda checked=False, key=key: self.change_directory(key))
            line.addWidget(change)
            self.path_labels[key] = value
            self.path_buttons.append(change)
            rows.addLayout(line)
        layout.addWidget(card)
        layout.addWidget(self.advanced)
        layout.addWidget(self.engine_status)
        layout.addStretch()
        return page

    def show_page(self, index):
        # Preserve internal destinations used by preparation/export callbacks.
        # 0 closes the drawer; other destinations are tabs inside Settings.
        if index == 0:
            self.settings_drawer.hide()
            if hasattr(self, 'settings_action'):
                self.settings_action.setFocus()
            return
        self.pause_playback()
        self.settings_tabs.setCurrentIndex({1: 1, 2: 2, 3: 0}[index])
        self.settings_drawer.setGeometry(self.editor.rect())
        self.settings_drawer.show()
        self.settings_drawer.raise_()
        self.close_settings_button.setFocus()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'settings_drawer'):
            self.settings_drawer.setGeometry(self.editor.rect())

    def focusNextPrevChild(self, forward):
        drawer = getattr(self, 'settings_drawer', None)
        if drawer is None or not drawer.isVisible():
            return super().focusNextPrevChild(forward)
        # The inline settings surface is modal for keyboard navigation as well
        # as pointer input. Tab must not reach covered workspace controls.
        candidate = self.focusWidget() or self.close_settings_button
        for _ in range(300):
            candidate = candidate.nextInFocusChain() if forward else candidate.previousInFocusChain()
            if (drawer.isAncestorOf(candidate) and candidate.isVisibleTo(drawer)
                    and candidate.isEnabled() and candidate.focusPolicy() & C.Qt.TabFocus):
                candidate.setFocus(C.Qt.TabFocusReason if forward else C.Qt.BacktabFocusReason)
                return True
        return False

    def eventFilter(self, obj, event):
        if obj is getattr(self, 'settings_drawer', None) and event.type() == C.QEvent.MouseButtonPress:
            self.show_page(0)
            return True
        return super().eventFilter(obj, event)

    def change_directory(self, key):
        if self.worker or self.process:
            return
        path = W.QFileDialog.getExistingDirectory(self, '选择保存位置', str(getattr(self.settings, key)))
        if not path:
            return
        self.apply_directory(key, Path(path))

    def apply_directory(self, key, path):
        """Persist a confirmed directory; return whether the setting changed."""
        old = getattr(self.settings, key)
        path = Path(path)
        if path == old:
            return False
        try:
            setattr(self.settings, key, path)
            self.settings.save(self.root)
        except OSError:
            setattr(self.settings, key, old)
            W.QMessageBox.warning(self, '无法保存', '请检查文件夹权限')
            return False
        self.path_labels[key].setText(str(path))
        return True

    def run_models(self, operation, source=None):
        if self.worker or self.process:
            return
        self._worker_error = ''
        self.model_notice.clear()
        self.worker = ModelWorker(self.settings.model_dir, operation, source, self)
        self.worker.status.connect(self.model_status)
        self.worker.outcome.connect(self.model_outcome)
        self.worker.finished.connect(self.models_finished)
        self.set_busy(True)
        self.worker.start()

    def set_busy(self, busy):
        for b in [self.download_button, self.import_button, *self.path_buttons]:
            b.setEnabled(not busy)
        self.pause_button.setEnabled(busy)

    def model_status(self, key, state, done, total):
        text, progress = self.model_rows[key]
        text.setText(state)
        progress.setValue(round(done / total * 1000) if total else 0)
        if state == '已就绪':
            self.ready.add(key)
        else:
            self.ready.discard(key)
        self.engine_status.setText('已就绪' if len(self.ready) == len(BASIC_RESOURCES) else '准备中' if self.worker else '准备开始')

    def model_outcome(self, error):
        self._worker_error = error
        self.model_notice.setText(error)

    def models_finished(self):
        self.worker.deleteLater()
        self.worker = None
        self.set_busy(False)
        ready = len(self.ready) == len(BASIC_RESOURCES)
        self.engine_status.setText('已就绪' if ready else '需要准备')
        if self._worker_error:
            for key, (status, _) in self.model_rows.items():
                if key not in self.ready:
                    status.setText('待继续')
            self.download_button.setText('继续准备')
        elif ready:
            self.download_button.setText('重新检查')
        if self.pending_preview and ready:
            self.pending_preview = False
            self.launch_editor()
        elif self._worker_error:
            self.pending_preview = False

    def pause(self):
        if self.worker:
            self.worker.cancelled.set()
            self.pause_button.setEnabled(False)
            self.model_notice.setText('正在暂停…')

    def import_models(self):
        path = W.QFileDialog.getExistingDirectory(self, '选择已有模型文件夹')
        if path:
            self.run_models('import', Path(path))

