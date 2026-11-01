"""Single-window Studio workspace. Model processing stays off the UI thread."""
import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import uuid

from PySide6 import QtCore as C, QtGui as G, QtWidgets as W
from .shell_base import BaseStudioWindow, ModelWorker, AssetButton, button, label, panel, IMAGES, VIDEOS
from .resources import BASIC_RESOURCES
from .engine_client import EngineClient


class Preview(W.QWidget):
    selected = C.Signal(str)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setMinimumSize(280, 240)
        self.setSizePolicy(W.QSizePolicy.Expanding, W.QSizePolicy.Expanding)
        self.original = G.QImage()
        self.result = G.QImage()
        self.mode = 'original'
        self.split = .5

    def pixmap(self):
        return G.QPixmap.fromImage(self.result if self.mode != 'original' and not self.result.isNull() else self.original)

    def paintEvent(self, event):
        p = G.QPainter(self)
        p.fillRect(self.rect(), G.QColor('#111518'))
        if self.original.isNull():
            p.setPen(G.QColor('#82919b'))
            p.drawText(self.rect(), C.Qt.AlignCenter, '＋\n\n拖入照片或视频')
            return
        size = self.original.size().scaled(self.size(), C.Qt.KeepAspectRatio)
        rect = C.QRect((self.width()-size.width())//2, (self.height()-size.height())//2, size.width(), size.height())
        p.setRenderHint(G.QPainter.SmoothPixmapTransform)
        p.drawImage(rect, self.original)
        if self.mode != 'original' and not self.result.isNull():
            if self.mode == 'compare':
                x = rect.left() + int(rect.width()*self.split)
                p.save()
                p.setClipRect(C.QRect(x, rect.top(), rect.right()-x+1, rect.height()))
                p.drawImage(rect, self.result)
                p.restore()
                p.setPen(G.QPen(G.QColor('#75e0c1'), 2))
                p.drawLine(x, rect.top(), x, rect.bottom())
                p.setBrush(G.QColor('#75e0c1'))
                p.drawEllipse(C.QPoint(x, rect.center().y()), 10, 10)
                p.setPen(G.QColor('#ffffff'))
                p.drawText(rect.adjusted(12, 10, -12, -10), C.Qt.AlignLeft | C.Qt.AlignTop, '原始')
                p.drawText(rect.adjusted(12, 10, -12, -10), C.Qt.AlignRight | C.Qt.AlignTop, '处理后')
            else:
                p.drawImage(rect, self.result)

    def mousePressEvent(self, event):
        self.mouseMoveEvent(event)

    def mouseMoveEvent(self, event):
        if self.mode == 'compare' and event.buttons() & C.Qt.LeftButton and not self.original.isNull():
            size = self.original.size().scaled(self.size(), C.Qt.KeepAspectRatio)
            self.split = max(0., min(1., (event.position().x()-(self.width()-size.width())/2)/size.width()))
            self.update()

    def dragEnterEvent(self, event):
        urls = event.mimeData().urls()
        if len(urls) == 1 and urls[0].isLocalFile():
            event.acceptProposedAction()

    def dropEvent(self, event):
        self.selected.emit(event.mimeData().urls()[0].toLocalFile())
        event.acceptProposedAction()


class MediaCard(W.QToolButton):
    selected = C.Signal(str)
    choose = AssetButton.choose
    dragEnterEvent = AssetButton.dragEnterEvent
    dropEvent = AssetButton.dropEvent

    def __init__(self, text, source=False):
        super().__init__()
        self.source = source
        self.setText(text)
        self.setObjectName('mediaCard')
        self.setToolButtonStyle(C.Qt.ToolButtonTextUnderIcon)
        self.setSizePolicy(W.QSizePolicy.Expanding, W.QSizePolicy.Fixed)
        self.setMinimumHeight(128)
        self.setIconSize(C.QSize(158, 108))
        self.setAcceptDrops(True)
        self.clicked.connect(self.choose)


class StudioWindow(BaseStudioWindow):
    def __init__(self, root=None):
        self._revision = 0
        self._valid_revision = -1
        self._busy_preview = False
        self._engine_ready = False
        self._exporting = False
        self._retired = []
        self._closing = False
        self._active_record = None
        self._records = []
        self._fps = 1.
        self._frames = 1
        self._media_generation = 0
        self._player = None
        self._has_preview = False
        super().__init__(root)
        self.source_button.setAccessibleName('添加参考人脸照片')
        self.target_button.setAccessibleName('导入照片或视频')
        self.start_button.setShortcut(G.QKeySequence('Ctrl+Return'))
        self.export_action.setShortcut(G.QKeySequence.Save)
        self._load_history()

    def build_editor(self):
        page = W.QWidget()
        layout = W.QVBoxLayout(page)
        layout.setContentsMargins(24, 26, 24, 24)
        layout.setSpacing(20)
        header = W.QHBoxLayout()
        title = W.QVBoxLayout()
        self.project_title = label('VisoMaster Studio', 'title')
        title.addWidget(self.project_title)
        self.media_name = label('照片与视频', 'muted')
        title.addWidget(self.media_name)
        header.addLayout(title, 1)
        self.history_action = button('最近导出', lambda: self.show_page(2))
        self.history_action.setObjectName('segment')
        header.addWidget(self.history_action)
        self.settings_action = button('设置', lambda: self.show_page(3))
        self.settings_action.setObjectName('segment')
        header.addWidget(self.settings_action)
        self.export_action = button('导出', self.export, True)
        self.export_action.setMinimumWidth(128)
        self.export_action.setEnabled(False)
        header.addWidget(self.export_action)
        layout.addLayout(header)
        columns = W.QHBoxLayout()
        columns.setSpacing(16)
        assets, items = panel()
        assets.setFixedWidth(200)
        items.setContentsMargins(14, 18, 14, 18)
        items.addWidget(label('素材'))
        self.target_button = MediaCard('＋ 导入素材')
        self.target_button.selected.connect(lambda p: self.select_asset(p))
        items.addWidget(self.target_button)
        self.media_info = label('', 'muted')
        self.media_info.setWordWrap(True)
        items.addWidget(self.media_info)
        items.addSpacing(20)
        self.divider(items)
        items.addWidget(label('参考人脸'))
        self.source_button = MediaCard('＋ 添加人脸照片', True)
        self.source_button.selected.connect(lambda p: self.select_asset(p, True))
        items.addWidget(self.source_button)
        items.addStretch()
        columns.addWidget(assets)
        center = W.QVBoxLayout()
        center.setSpacing(12)
        frame, view = panel()
        view.setContentsMargins(0, 0, 0, 12)
        view.setSpacing(8)
        tabs = W.QHBoxLayout()
        tabs.setContentsMargins(12, 8, 12, 0)
        tabs.addWidget(label('预览'), 1)
        self.view_buttons = {}
        group = W.QButtonGroup(self)
        for key, text in [('original', '原始'), ('processed', '处理后'), ('compare', '对比')]:
            b = button(text, lambda checked=False, key=key: self.set_view(key))
            b.setObjectName('segment')
            b.setCheckable(True)
            b.setChecked(key == 'original')
            b.setEnabled(key == 'original')
            group.addButton(b)
            tabs.addWidget(b)
            self.view_buttons[key] = b
        view.addLayout(tabs)
        self.preview = Preview()
        self.preview.selected.connect(lambda p: self.select_asset(p))
        view.addWidget(self.preview, 1)
        transport = W.QHBoxLayout()
        transport.setContentsMargins(12, 0, 12, 0)
        self.play_button = button('▶', self.play)
        self.play_button.setObjectName('segment')
        self.play_button.setToolTip('播放原视频 / 暂停')
        self.play_button.setEnabled(False)
        transport.addWidget(self.play_button)
        self.time_label = label('00:00 / 00:00', 'muted')
        transport.addWidget(self.time_label)
        transport.addStretch()
        self.frame_label = label('适应窗口', 'muted')
        transport.addWidget(self.frame_label)
        view.addLayout(transport)
        center.addWidget(frame, 1)
        timeline, t = panel()
        t.setContentsMargins(12, 8, 12, 10)
        self.seek = W.QSlider(C.Qt.Horizontal)
        self.seek.setAccessibleName('视频时间轴')
        self.seek.setRange(0, 0)
        self.seek.sliderPressed.connect(self.pause_playback)
        self.seek.sliderReleased.connect(self.seek_video)
        self.seek.valueChanged.connect(self.seek_changed)
        t.addWidget(self.seek)
        center.addWidget(timeline)
        faces, f = panel()
        f.setContentsMargins(12, 12, 12, 12)
        f.addWidget(label('替换对象'))
        row = W.QHBoxLayout()
        self.face_choice = W.QComboBox()
        self.face_choice.setMinimumHeight(44)
        self.face_choice.setIconSize(C.QSize(38, 38))
        self.face_choice.addItem('添加素材后自动检测')
        self.face_choice.setEnabled(False)
        self.face_choice.currentIndexChanged.connect(self.face_changed)
        row.addWidget(self.face_choice, 1)
        self.assignment = label('→  参考人脸', 'muted')
        row.addWidget(self.assignment)
        f.addLayout(row)
        center.addWidget(faces)
        columns.addLayout(center, 1)
        inspector, controls = panel()
        inspector.setFixedWidth(264)
        controls.setContentsMargins(18, 18, 18, 18)
        controls.addWidget(label('处理设置'))
        controls.addSpacing(4)
        controls.addWidget(label('处理预设', 'muted'))
        presets = W.QHBoxLayout()
        self.preset_buttons = []
        self.preset_group = W.QButtonGroup(self)
        for i, name in enumerate(['快速', '均衡', '精细']):
            b = button(name, lambda checked=False, i=i: self.set_preset(i))
            b.setObjectName('segment')
            b.setCheckable(True)
            b.setChecked(i == 0)
            self.preset_group.addButton(b, i)
            self.preset_buttons.append(b)
            presets.addWidget(b)
        controls.addLayout(presets)
        self.divider(controls)
        self.edge = self.slider(controls, '边缘柔化', 0, 50, 5)
        self.edge.valueChanged.connect(self.invalidate)
        self.advanced = W.QGroupBox('高级参数')
        advanced = W.QVBoxLayout(self.advanced)
        self.similarity = self.slider(advanced, '人脸匹配阈值', 1, 100, 60)
        self.similarity.valueChanged.connect(self.invalidate)
        controls.addStretch()
        self.notice = label('添加素材和人脸照片', 'muted')
        self.notice.setWordWrap(True)
        controls.addWidget(self.notice)
        self.operation_progress = W.QProgressBar()
        self.operation_progress.setRange(0, 100)
        self.operation_progress.setTextVisible(False)
        self.operation_progress.hide()
        controls.addWidget(self.operation_progress)
        self.cancel_button = button('取消', self.cancel_operation)
        self.cancel_button.hide()
        controls.addWidget(self.cancel_button)
        self.start_button = button('预览当前帧', self.start_processing, True)
        self.start_button.setEnabled(False)
        controls.addWidget(self.start_button)
        columns.addWidget(inspector)
        layout.addLayout(columns, 1)
        return page

    @staticmethod
    def divider(layout):
        line = W.QFrame()
        line.setObjectName('divider')
        line.setFixedHeight(1)
        layout.addWidget(line)

    def slider(self, layout, title, low, high, value):
        row = W.QHBoxLayout()
        row.addWidget(label(title), 1)
        number = label(str(value), 'muted')
        row.addWidget(number)
        layout.addLayout(row)
        slider = W.QSlider(C.Qt.Horizontal)
        slider.setAccessibleName(title)
        slider.setRange(low, high)
        slider.setValue(value)
        slider.valueChanged.connect(lambda v: number.setText(str(v)))
        layout.addWidget(slider)
        return slider

    def build_queue(self):
        page, layout = self.page('导出记录')
        self.queue = W.QListWidget()
        self.queue.setSpacing(8)
        self.queue.itemDoubleClicked.connect(self.open_record)
        layout.addWidget(self.queue, 1)
        row = W.QHBoxLayout()
        self.queue_status = label('尚无导出', 'muted')
        row.addWidget(self.queue_status, 1)
        row.addWidget(button('打开选中结果', lambda: self.open_record(self.queue.currentItem())))
        row.addWidget(button('打开导出文件夹', self.open_output))
        layout.addLayout(row)
        return page

    def change_directory(self, key):
        if self._busy_preview or self._exporting or self.worker:
            return
        path = W.QFileDialog.getExistingDirectory(self, '选择保存位置', str(getattr(self.settings, key)))
        if not path or not self.apply_directory(key, Path(path)):
            return
        self.retire_engine()
        self.invalidate()
        if key == 'model_dir':
            self.ready.clear()
            self.run_models('check')
        self.refresh_controls()

    def open_output(self):
        try:
            self.settings.output_dir.mkdir(parents=True, exist_ok=True)
            opened = G.QDesktopServices.openUrl(C.QUrl.fromLocalFile(str(self.settings.output_dir)))
        except OSError:
            opened = False
        if not opened:
            self.queue_status.setText('无法打开导出位置，请在设置中更改')

    def open_record(self, item):
        if item and item.data(C.Qt.UserRole):
            path = Path(item.data(C.Qt.UserRole))
            if path.is_file():
                G.QDesktopServices.openUrl(C.QUrl.fromLocalFile(str(path)))
            else:
                self.queue_status.setText('文件已移动或删除')

    def _load_history(self):
        try:
            data = json.loads((self.root / 'exports.json').read_text())
            for record in data[-100:]:
                if isinstance(record, dict) and isinstance(record.get('path'), str):
                    self._records.append(record)
                    item = W.QListWidgetItem(f"{record.get('name', Path(record['path']).name)}    ·    已完成")
                    item.setData(C.Qt.UserRole, record['path'])
                    self.queue.insertItem(0, item)
            if self._records:
                self.queue_status.setText(f'{len(self._records)} 个结果')
        except (OSError, ValueError, TypeError):
            pass

    def select_asset(self, filename, source=False):
        if self._exporting:
            self.notice.setText('正在导出，可先取消')
            return
        path = Path(filename).expanduser().resolve()
        if not path.is_file() or path.suffix.lower() not in (IMAGES if source else IMAGES | VIDEOS):
            self.notice.setText('请选择有效的图片' if source else '请选择有效的照片或视频')
            return
        image = G.QImage()
        fps, frames = 1., 1
        if path.suffix.lower() in IMAGES:
            reader = G.QImageReader(str(path))
            reader.setAutoTransform(True)
            size = reader.size()
            if size.isValid():
                reader.setScaledSize(size.scaled(1600, 1000, C.Qt.KeepAspectRatio))
            image = reader.read()
        else:
            try:
                probe = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_streams', '-show_format', '-of', 'json', str(path)], capture_output=True, timeout=8)
                metadata = json.loads(probe.stdout)
                stream = metadata['streams'][0]
                rate = stream.get('avg_frame_rate', '0/1')
                if rate in ('0/0', '0/1'):
                    rate = stream.get('r_frame_rate', '0/1')
                num, den = rate.split('/')
                fps = float(num)/float(den)
                if fps <= 0:
                    raise ValueError('fps')
                count = str(stream.get('nb_frames', ''))
                duration = stream.get('duration') or metadata.get('format', {}).get('duration')
                frames = int(count) if count.isdigit() else max(1, round(float(duration)*fps))
                frame = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(path), '-frames:v', '1', '-vf', 'scale=1280:720:force_original_aspect_ratio=decrease', '-f', 'image2pipe', '-vcodec', 'png', '-'], capture_output=True, timeout=10)
                image.loadFromData(frame.stdout)
            except (OSError, subprocess.SubprocessError, ValueError, TypeError, KeyError, IndexError, ZeroDivisionError, OverflowError):
                self.notice.setText('视频无法打开，请检查文件或视频组件')
                return
        if image.isNull():
            self.notice.setText('图片无法打开，请换一张' if path.suffix.lower() in IMAGES else '视频无法打开，请更换素材')
            return
        self.pause_playback()
        self.retire_engine()
        self._engine_ready = False
        self._busy_preview = False
        self._has_preview = False
        self.face_choice.setEnabled(False)
        with C.QSignalBlocker(self.face_choice):
            self.face_choice.clear()
            self.face_choice.addItem('预览时自动检测')
        if source:
            self.source = path
            widget = self.source_button
        else:
            self.target = path
            widget = self.target_button
            self._fps, self._frames = fps, frames
            self.preview.original = image
            self.project_title.setText(self.fontMetrics().elidedText(path.stem, C.Qt.ElideMiddle, 480))
            self.media_name.setText(path.name)
            self.media_name.setToolTip(str(path))
            dimensions = (stream['width'], stream['height']) if path.suffix.lower() in VIDEOS else (size.width(), size.height())
            self.media_info.setText(f'{dimensions[0]} × {dimensions[1]}' + (f'\n{self.format_time(round(frames/fps*1000))} · {fps:g} fps' if path.suffix.lower() in VIDEOS else ''))
            with C.QSignalBlocker(self.seek):
                self.seek.setRange(0, max(0, frames-1))
                self.seek.setValue(0)
            self.time_changed(0)
            self.play_button.setEnabled(path.suffix.lower() in VIDEOS)
            self.setup_player(path if path.suffix.lower() in VIDEOS else None)
        widget.setText(widget.fontMetrics().elidedText(path.name, C.Qt.ElideMiddle, 160))
        widget.setIcon(G.QIcon(G.QPixmap.fromImage(image)))
        widget.setToolTip(str(path))
        self.invalidate()
        self.notice.setText('点击预览' if self.source and self.target else '添加素材' if self.source else '添加人脸照片')
        self.refresh_controls()

    def setup_player(self, path):
        self._media_generation += 1
        if not path and not self._player:
            return
        if not self._player:
            from PySide6.QtMultimedia import QMediaPlayer, QVideoSink, QAudioOutput
            self._player = QMediaPlayer(self)
            self._audio = QAudioOutput(self)
            self._player.setAudioOutput(self._audio)
            self._player.positionChanged.connect(self.player_position)
            self._player.playbackStateChanged.connect(lambda state: self.play_button.setText('Ⅱ' if state == QMediaPlayer.PlaybackState.PlayingState else '▶'))
            self._player.errorOccurred.connect(lambda *args: self.notice.setText('视频播放失败，仍可选择帧进行处理'))
        from PySide6.QtMultimedia import QVideoSink
        old_sink = getattr(self, '_sink', None)
        self._sink = QVideoSink(self)
        self._sink.videoFrameChanged.connect(lambda frame, generation=self._media_generation: self.video_frame(frame, generation))
        self._player.setVideoSink(self._sink)
        if old_sink:
            old_sink.deleteLater()
        self._player.setSource(C.QUrl.fromLocalFile(str(path)) if path else C.QUrl())

    def video_frame(self, frame, generation=None):
        if not self.target or self.target.suffix.lower() not in VIDEOS:
            return
        if generation is not None and generation != self._media_generation:
            return
        if self.preview.mode == 'original' and not self._busy_preview and not self._exporting:
            image = frame.toImage()
            if not image.isNull():
                self.preview.original = image
                self.preview.update()

    def player_position(self, ms):
        if self._player and self._player.playbackState() == self._player.PlaybackState.PlayingState:
            with C.QSignalBlocker(self.seek):
                self.seek.setValue(min(self._frames-1, round(ms*self._fps/1000)))
            self.time_changed(self.seek.value())

    def play(self):
        if not self._player or self._busy_preview or self._exporting:
            return
        if self._player.playbackState() == self._player.PlaybackState.PlayingState:
            self.pause_playback()
        else:
            self.invalidate()
            self._player.play()

    def pause_playback(self):
        if self._player:
            self._player.pause()

    def seek_changed(self, value):
        self.time_changed(value)
        self.seek_video()

    def seek_video(self):
        if self._exporting:
            return
        self.pause_playback()
        self.invalidate()
        if self._player:
            self._player.setPosition(round(self.seek.value()/self._fps*1000))
        self.notice.setText('点击预览当前帧')

    @staticmethod
    def format_time(ms):
        seconds = int(ms)//1000
        return f'{seconds//60:02d}:{seconds%60:02d}'

    def time_changed(self, value):
        self.time_label.setText(f'{self.format_time(value/self._fps*1000)} / {self.format_time(self._frames/self._fps*1000) if self._frames > 1 else "00:00"}')
        self.frame_label.setText(f'第 {value+1} 帧' if self._frames > 1 else '适应窗口')

    def set_view(self, mode):
        if mode != 'original' and self.preview.result.isNull():
            return
        self.pause_playback()
        self.preview.mode = mode
        self.view_buttons[mode].setChecked(True)
        self.preview.update()

    def set_preset(self, index):
        self.preset_buttons[index].setChecked(True)
        self.invalidate()

    def options(self):
        return {'resolution': ('128', '256', '512')[max(0, self.preset_group.checkedId())],
                'edge': self.edge.value(), 'similarity': self.similarity.value()}

    def invalidate(self, *args):
        self._revision += 1
        self._valid_revision = -1
        self.preview.result = G.QImage()
        self.view_buttons['processed'].setEnabled(False)
        self.view_buttons['compare'].setEnabled(False)
        self.set_view('original')
        self.export_action.setEnabled(False)
        if self.source and self.target:
            self.notice.setText('点击预览更新效果')

    def face_changed(self, index):
        if self._engine_ready and index >= 0:
            self.invalidate()
            self.start_processing()

    def refresh_controls(self):
        busy = self._busy_preview or self._exporting
        self.start_button.setEnabled(bool(self.source and self.target) and not busy and (not self._engine_ready or self.face_choice.currentIndex() >= 0))
        self.start_button.setText('正在预览…' if self._busy_preview else '预览当前帧')
        self.export_action.setEnabled(self._valid_revision == self._revision and not busy)
        self.cancel_button.setVisible(busy)
        self.operation_progress.setVisible(busy)
        if self._busy_preview:
            self.operation_progress.setRange(0, 0)
        else:
            self.operation_progress.setRange(0, 100)
        for w in (self.edge, self.similarity, *self.preset_buttons, self.seek, self.play_button):
            w.setEnabled(not busy and (w is not self.play_button or bool(self.target and self.target.suffix.lower() in VIDEOS)))
        self.face_choice.setEnabled(self._engine_ready and not busy and self.face_choice.count() > 1)
        self.source_button.setEnabled(not self._exporting)
        self.target_button.setEnabled(not self._exporting)
        for widget in (self.download_button, self.import_button):
            widget.setEnabled(not self.worker and not self.process)
        for widget in self.path_buttons:
            widget.setEnabled(not self.worker and not busy)
        self.pause_button.setEnabled(bool(self.worker))

    def models_finished(self):
        super().models_finished()
        if self.pending_preview and not self._worker_error and not self._closing and not self.worker and not self.process:
            self.run_models('download')
        self.refresh_controls()

    def start_processing(self):
        if not self.source or not self.target or self._busy_preview or self._exporting:
            return
        self.pause_playback()
        if self.process and self._engine_ready:
            self.request_preview()
            return
        if len(self.ready) != len(BASIC_RESOURCES):
            self.pending_preview = True
            self.show_page(1)
            self.model_notice.setText('准备完成后自动预览')
            if not self.worker:
                self.run_models('download')
            return
        self.launch_editor()

    def launch_editor(self):
        # Historic name retained for the base model-preparation callback.
        if self.process or not self.source or not self.target:
            return
        try:
            self.settings.save(self.root)
            client = EngineClient(self.source, self.target, self.settings.model_dir, self.root, self.settings.output_dir, self, frame=self.seek.value())
        except OSError:
            self.notice.setText('无法创建处理缓存，请检查磁盘空间')
            return
        self.process = client
        self._engine_ready = False
        self._busy_preview = True
        self._has_preview = False
        client.event.connect(lambda event, client=client: self.engine_event(client, event))
        client.stopped.connect(lambda client=client: self.engine_stopped(client))
        self.notice.setText('正在准备预览…')
        self.show_page(0)
        self.refresh_controls()

    def request_preview(self):
        self._busy_preview = True
        self._valid_revision = -1
        self.notice.setText('正在预览…')
        self.refresh_controls()
        self.process.send({'action': 'preview', 'request': self._revision, 'frame': self.seek.value(),
                           'face': max(0, self.face_choice.currentIndex()), 'options': self.options()})

    def engine_event(self, client, event):
        if client is not self.process:
            return
        kind = event.get('type')
        if kind == 'status':
            self.notice.setText(event.get('text', ''))
        elif kind == 'ready':
            self._engine_ready = event.get('sources') == 1 and bool(event.get('faces'))
            with C.QSignalBlocker(self.face_choice):
                self.face_choice.clear()
                for i, face in enumerate(event.get('faces', [])):
                    image = G.QImage.fromData(base64.b64decode(face['image']))
                    self.face_choice.addItem(G.QIcon(G.QPixmap.fromImage(image)), f'人脸 {i+1}')
                if not self.face_choice.count():
                    self.face_choice.addItem('未检测到人脸')
                elif self.face_choice.count() > 1:
                    self.face_choice.setPlaceholderText('选择要替换的人脸')
                    self.face_choice.setCurrentIndex(-1)
            self.engine_status.setText(f"已就绪 · {event.get('provider', '')}")
            if event.get('source_image'):
                source_image = G.QImage.fromData(base64.b64decode(event['source_image']))
                self.source_button.setIcon(G.QIcon(G.QPixmap.fromImage(source_image)))
            if self._engine_ready and self.face_choice.count() == 1:
                self.request_preview()
            else:
                if self._engine_ready:
                    self.notice.setText('选择要替换的人脸')
                self._busy_preview = False
                self.refresh_controls()
        elif kind == 'preview':
            # Worker initial detection uses request 0. Always wait for a preview
            # of the exact UI revision, including selected frame and parameters.
            if event.get('request') != self._revision:
                return
            result = G.QImage.fromData(base64.b64decode(event.get('image', '')))
            original = G.QImage.fromData(base64.b64decode(event.get('original', '')))
            if result.isNull() or original.isNull():
                self.fail('预览失败，请重试')
                return
            self.preview.result, self.preview.original = result, original
            self._valid_revision = self._revision
            self._has_preview = True
            self._busy_preview = False
            self.view_buttons['processed'].setEnabled(True)
            self.view_buttons['compare'].setEnabled(True)
            self.set_view('processed')
            self.notice.setText('已就绪')
            self.refresh_controls()
        elif kind == 'exporting':
            self.operation_progress.setValue(event.get('progress', 0))
            self.notice.setText(f"正在导出 {event.get('progress', 0)}%")
            if self._active_record:
                self._active_record.setText(f"{self.target.name}    ·    正在导出 {event.get('progress', 0)}%")
        elif kind == 'exported':
            self.complete_export(client, event['path'])
        elif kind == 'error':
            self.fail(event.get('text', '处理失败，请重试'))

    def export(self):
        if not self.process or self._valid_revision != self._revision or self._exporting:
            return
        try:
            self.settings.output_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            self.notice.setText('导出位置无法写入，请在设置中更改')
            return
        self.pause_playback()
        self._exporting = True
        self._active_record = W.QListWidgetItem(f'{self.target.name}    ·    正在导出')
        self.queue.insertItem(0, self._active_record)
        self.queue_status.setText('正在导出')
        self.refresh_controls()
        self.process.send({'action': 'export'})

    def complete_export(self, client, filename):
        path = Path(filename).resolve()
        if not self._exporting or path.parent != client.work.resolve() or not path.is_file():
            self.fail('导出文件无效，请重试')
            return
        dest = self.settings.output_dir / f'{self.target.stem}_{uuid.uuid4().hex[:8]}{path.suffix}'
        try:
            # Session output lives on the destination volume: publish atomically
            # without a long copy on the UI thread or overwriting prior exports.
            os.replace(path, dest)
        except OSError:
            self.fail('保存失败，请检查导出位置和磁盘空间')
            return
        self._exporting = False
        self._active_record.setText(f'{self.target.name}    ·    已完成')
        self._active_record.setData(C.Qt.UserRole, str(dest))
        self._active_record.setToolTip(str(dest))
        self._active_record = None
        self._records.append({'name': self.target.name, 'path': str(dest)})
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            tmp = self.root / 'exports.json.tmp'
            tmp.write_text(json.dumps(self._records[-100:], ensure_ascii=False), encoding='utf-8')
            os.replace(tmp, self.root / 'exports.json')
        except OSError:
            pass  # A history write failure cannot invalidate a verified output.
        self.notice.setText('已导出 · 在导出记录中打开')
        self.queue_status.setText(f'{len(self._records)} 个结果')
        self.refresh_controls()

    def fail(self, text):
        if self._active_record:
            self._active_record.setText(f'{self.target.name}    ·    失败，可重新导出')
            self._active_record = None
        self._busy_preview = self._exporting = False
        self._valid_revision = -1
        self.notice.setText(text)
        self.queue_status.setText(text)
        self.retire_engine()
        self.refresh_controls()

    def cancel_operation(self):
        if self._active_record:
            self._active_record.setText(f'{self.target.name}    ·    已取消')
            self._active_record = None
        self._busy_preview = self._exporting = False
        self._valid_revision = -1
        self.retire_engine()
        self.notice.setText('已取消')
        self.queue_status.setText('已取消')
        self.refresh_controls()

    def retire_engine(self):
        self.pending_preview = False
        if self.process:
            client, self.process = self.process, None
            self._retired.append(client)
            client.cancel()
        self._engine_ready = False

    def engine_stopped(self, client):
        if client in self._retired:
            self._retired.remove(client)
        if client is self.process:
            self.process = None
            self._engine_ready = False
        client.deleteLater()
        if self._closing:
            C.QTimer.singleShot(0, self.close)

    def render_preview(self):
        self.preview.update()

    def closeEvent(self, event):
        self._closing = True
        self.pause_playback()
        self.retire_engine()
        if self.worker:
            self.worker.cancelled.set()
        if self.worker or self._retired:
            event.ignore()
            C.QTimer.singleShot(100, self.close)
            return
        event.accept()
