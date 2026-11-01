"""Single-window Studio workspace over the complete Fusion controller.

The native controls are reused, not copied: per-face parameters, markers, jobs,
projects and the preview/export pipeline retain the same state and callbacks.
"""
import os
from pathlib import Path
from PySide6 import QtCore as C, QtGui as G, QtWidgets as W
from .config import Settings, data_root

# Set paths before importing Fusion's model registry.
STATE = data_root()
SETTINGS = Settings.load(STATE)
os.environ.setdefault('VISOMASTER_MODELS_DIR', str(SETTINGS.model_dir))
RUNTIME = STATE / 'runtime'
RUNTIME.mkdir(parents=True, exist_ok=True)
os.chdir(RUNTIME)

from .auxiliary import install_auxiliary
install_auxiliary(Path(os.environ['VISOMASTER_MODELS_DIR']))

os.environ['OPENBLAS_NUM_THREADS'] = '1'
import torch
torch.set_grad_enabled(False)
from app.ui.main_ui import MainWindow
from app.ui.widgets.actions import list_view_actions as lists
from app.ui.widgets.actions import control_actions as controls
from app.ui.widgets.actions import common_actions as common
from app.ui.widgets.actions import save_load_actions as projects
from app.ui.widgets.actions import video_control_actions as video
from app.helpers.miscellaneous import DFMModelManager
from .shell_base import button, label
from .presentation import STYLE, ElidedLabel, icon, tool, small_button
from .model_service import ModelService
from .catalog import RESOURCES


class StudioWorkspace(MainWindow):
    def initialize_variables(self):
        super().initialize_variables()
        self.project_root_path = RUNTIME
        self.last_workspace_path = STATE / 'complete-workspace.json'
        self.settings = SETTINGS
        self.model_service = ModelService(Path(os.environ['VISOMASTER_MODELS_DIR']), self)
        self.prepare_model_resource = self.model_service.ensure
        self.studio_inline_notice = self.notice
        self.prepare_extra_resources = self.model_service.prepare
        from app.processors.mouth_action_detector import MouthActionDetector
        MouthActionDetector.prepare_resource = self.model_service.ensure
        dfm_path = self.model_service.root / 'dfm_models'
        dfm_path.mkdir(parents=True, exist_ok=True)
        self.dfm_model_manager = DFMModelManager(str(dfm_path))
        self.model_loading_signal.disconnect()
        self.model_loaded_signal.disconnect()
        self.model_loading_signal.connect(lambda: self.notice('正在加载模型…'))
        self.model_loaded_signal.connect(lambda: self.notice('就绪'))
        self.display_messagebox_signal.disconnect()
        self.display_messagebox_signal.connect(lambda title, text, parent: self.notice(f'{title}：{text}'))

    def load_last_workspace(self):
        # Preserve upstream parameters. Only choose safe platform defaults on first run.
        import torch
        provider = 'CUDA' if torch.cuda.is_available() else 'CPU'
        defaults = {'ProvidersPrioritySelection': provider,
                    'RecognitionModelSelection': 'Inswapper128ArcFace',
                    'DetectorModelSelection': 'RetinaFace', 'LandmarkDetectToggle': False,
                    'AutoSwapToggle': False, 'EnableMediaToastToggle': False,
                    'OutputMediaFolder': str(self.settings.output_dir)}
        for name, value in defaults.items():
            self.control[name] = value
            widget = self.parameter_widgets.get(name)
            if widget is not None:
                with C.QSignalBlocker(widget):
                    if hasattr(widget, 'setChecked'):
                        widget.setChecked(value)
                    elif hasattr(widget, 'setCurrentText'):
                        widget.setCurrentText(str(value))
        controls.change_execution_provider(self)
        self._studio_processing_defaults()
        self.settings.output_dir.mkdir(parents=True, exist_ok=True)
        self.outputFolderLineEdit.setText(str(self.settings.output_dir))
        with C.QSignalBlocker(self.targetVideosFilterWebcamsCheckBox):
            self.targetVideosFilterWebcamsCheckBox.setChecked(False)
        # Restore after construction so all drawer/model progress handlers exist.
        if self.last_workspace_path.is_file():
            C.QTimer.singleShot(0, self.restore_workspace)

    def _studio_processing_defaults(self):
        self.control.update({'StudioStrictProcessing': True,
                             'StudioTempDir': str(RUNTIME / 'work')})
        # Honour the user's encoder selection; upstream chooses available hardware.

    def restore_workspace(self):
        try:
            projects.load_saved_workspace(self, str(self.last_workspace_path))
            self._studio_processing_defaults()
        except Exception as exc:
            self.notice(f'项目恢复失败：{exc}')

    def __init__(self):
        super().__init__()
        self.setWindowTitle('VisoMaster Studio')
        self._base_window_title = 'VisoMaster Studio'
        self.setMinimumSize(980, 640)
        self.resize(1280, 820)
        self.setStyleSheet(STYLE)
        self._native_central = self.takeCentralWidget()
        self._native_central.setParent(self)
        self._native_central.hide()
        for dock in self.findChildren(W.QDockWidget):
            dock.setFeatures(W.QDockWidget.NoDockWidgetFeatures)
            self.removeDockWidget(dock)
            dock.hide()
        self.menuBar().hide()
        self.root_widget = W.QWidget()
        self.setCentralWidget(self.root_widget)
        root = W.QVBoxLayout(self.root_widget)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.toolbar = W.QWidget()
        self.toolbar.setObjectName('studioToolbar')
        self.toolbar.setFixedHeight(48)
        top = W.QHBoxLayout(self.toolbar)
        top.setContentsMargins(12, 0, 12, 0)
        top.setSpacing(6)
        project = tool('项目', 'folder')
        menu = W.QMenu(project)
        menu.addAction('打开项目…', lambda: projects.load_saved_workspace(self))
        menu.addAction('保存项目…', lambda: projects.save_current_workspace(self))
        project.setMenu(menu)
        top.addWidget(project)
        top.addWidget(tool('添加素材', 'plus', self.add_targets))
        top.addStretch()
        top.addWidget(tool('任务', 'queue', lambda: self.open_settings('批量任务')))
        self.settings_button = tool('设置', 'sliders', self.toggle_settings)
        top.addWidget(self.settings_button)
        self.export_button = tool('导出', 'export', self.export_current, primary=True)
        top.addWidget(self.export_button)
        root.addWidget(self.toolbar)
        self.workspace_body = W.QWidget()
        body = W.QHBoxLayout(self.workspace_body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        self.body_layout = body
        self._build_assets(body)
        self._build_canvas(body)
        root.addWidget(self.workspace_body, 1)
        self.status_strip = W.QWidget()
        self.status_strip.setObjectName('statusStrip')
        self.status_strip.setFixedHeight(32)
        footer = W.QHBoxLayout(self.status_strip)
        footer.setContentsMargins(12, 0, 10, 0)
        footer.setSpacing(10)
        self.status_label = ElidedLabel('添加素材开始')
        self.status_label.setObjectName('muted')
        footer.addWidget(self.status_label, 1)
        self.progress_bar = W.QProgressBar()
        self.progress_bar.setFixedWidth(140)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.hide()
        footer.addWidget(self.progress_bar)
        self.cancel_button = button('取消', self.cancel_active)
        self.cancel_button.hide()
        footer.addWidget(self.cancel_button)
        self.retry_button = button('重试', self.retry_processing)
        self.retry_button.hide()
        footer.addWidget(self.retry_button)
        footer.addWidget(tool('结果文件夹', 'folder', lambda: G.QDesktopServices.openUrl(C.QUrl.fromLocalFile(self.control['OutputMediaFolder']))))
        root.addWidget(self.status_strip)
        self._records = []
        self._record_snapshot = None
        self._build_drawer()
        from .labels import apply_labels
        apply_labels(self)
        self.model_service.progress.connect(self.model_progress)
        self.model_service.busy.connect(self.model_busy)
        self.video_processor.fatal_processing_error_signal.connect(self.processing_error)
        self.video_processor.processing_started_signal.connect(self.processing_started)
        self.video_processor.processing_stopped_signal.connect(self.processing_stopped)
        self.video_processor.processing_heartbeat_signal.connect(self.processing_progress)
        self._models_busy = False
        self._exporting = False
        self._image_export_pending = False
        self.video_processor.single_frame_processed_signal.connect(self.finish_image_export)
        shortcut = G.QShortcut(G.QKeySequence('Escape'), self)
        shortcut.activated.connect(self.close_settings)
        save = G.QShortcut(G.QKeySequence.StandardKey.Save, self)
        save.activated.connect(lambda: projects.save_current_workspace(self))
        # The original row rearranger assumes the old dock layout.
        self.notice('添加素材开始')
        self._auto_busy = False
        self._auto_seen = None
        self.guide_timer = C.QTimer(self)
        self.guide_timer.timeout.connect(self.guide_inputs)
        self.guide_timer.start(350)
        self._fit_timer = C.QTimer(self)
        self._fit_timer.setSingleShot(True)
        self._fit_timer.timeout.connect(lambda: video.fit_view_to_current_image(self))
        self.graphicsViewFrame.installEventFilter(self)
        self.presentation_timer = C.QTimer(self)
        self.presentation_timer.timeout.connect(self.sync_presentation)
        self.presentation_timer.start(150)
        self._presentation_key = None
        self.sync_presentation()
        self._style_parameters()

    def _build_assets(self, body):
        self.assets_panel = W.QFrame()
        self.assets_panel.setObjectName('assetsPanel')
        self.assets_panel.setFixedWidth(236)
        shell = W.QVBoxLayout(self.assets_panel)
        shell.setContentsMargins(0,0,0,0)
        scroll = W.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(C.Qt.ScrollBarAlwaysOff)
        content = W.QWidget()
        scroll.setWidget(content); shell.addWidget(scroll)
        a = W.QVBoxLayout(content)
        a.setContentsMargins(12, 8, 12, 12)
        a.setSpacing(8)
        self.section_counts = {}
        for title, view, fn, kind in [
            ('素材', self.targetVideosList, self.add_targets, 'media'),
            ('参考人脸', self.inputFacesList, self.add_sources, 'source'),
            ('替换对象', self.targetFacesList, None, 'target'),
        ]:
            if kind != 'media':
                rule = W.QFrame(); rule.setObjectName('sectionRule'); rule.setFixedHeight(1)
                a.addWidget(rule)
            head = W.QHBoxLayout(); head.setSpacing(6)
            head.addWidget(label(title, 'sectionTitle'))
            count = label('0', 'sectionCount'); self.section_counts[kind] = count
            head.addWidget(count); head.addStretch()
            if fn:
                head.addWidget(small_button('plus', '添加' + title, fn))
            else:
                self.findTargetFacesButton.setText('识别')
                self.findTargetFacesButton.setObjectName('toolAction')
                self.findTargetFacesButton.setFixedHeight(26)
                head.addWidget(self.findTargetFacesButton)
                self.findTargetFacesButton.show()
            a.addLayout(head)
            view.setMinimumSize(0, 0)
            view.setMaximumSize(16777215, 16777215)
            view.setSpacing(4)
            view.setFrameShape(W.QFrame.NoFrame)
            view.setHorizontalScrollBarPolicy(C.Qt.ScrollBarAlwaysOff)
            view.setVerticalScrollMode(W.QAbstractItemView.ScrollPerPixel)
            view.setResizeMode(W.QListView.Adjust)
            view.setGridSize(C.QSize())
            if kind == 'media':
                view.setViewMode(W.QListView.ListMode)
                view.setFlow(W.QListView.TopToBottom)
                view.setWrapping(False)
                view.setFixedHeight(142)
            else:
                view.setViewMode(W.QListView.IconMode)
                view.setFlow(W.QListView.LeftToRight)
                view.setWrapping(True)
                view.setFixedHeight(90)
            a.addWidget(view)
            view.show()
            if hasattr(view, 'placeholder_label'):
                view.placeholder_label.setText('拖入图片或视频' if kind == 'media' else '添加参考人脸')
                view.placeholder_label.setAlignment(C.Qt.AlignCenter)
                view.placeholder_label.setStyleSheet('color: #787e87; font-size: 12px; font-weight: normal; background: transparent;')
        self.mapping_label = label('识别素材中的人脸', 'muted')
        a.addWidget(self.mapping_label)
        self.swapfacesButton.setText('启用换脸')
        self.swapfacesButton.setIcon(G.QIcon())
        self.swapfacesButton.setFixedHeight(30)
        self.swapfacesButton.setToolTip('保留当前人脸分配，开启或关闭换脸效果')
        a.addWidget(self.swapfacesButton); self.swapfacesButton.show()
        a.addStretch(1)
        a.addWidget(tool('人脸库与批量处理', 'queue', lambda: self.open_settings('人脸库与批量图片')))
        body.addWidget(self.assets_panel)

    def _build_canvas(self, body):
        self.facesPanelGroupBox.setParent(self)
        self.facesPanelGroupBox.hide()
        self.mediaLayout.hide()
        self.canvas_panel = W.QWidget()
        self.canvas_panel.setObjectName('canvasPanel')
        layout = W.QVBoxLayout(self.canvas_panel)
        layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(0)
        head_widget = W.QWidget(); head_widget.setObjectName('canvasHeader'); head_widget.setFixedHeight(42)
        head = W.QHBoxLayout(head_widget); head.setContentsMargins(16, 0, 12, 0); head.setSpacing(16)
        self.document_title = ElidedLabel('预览'); self.document_title.setObjectName('documentTitle')
        head.addWidget(self.document_title, 1)
        self.faceCompareCheckBox.setText('对比')
        self.faceMaskCheckBox.setText('遮罩')
        for w in (self.faceCompareCheckBox, self.faceMaskCheckBox):
            head.addWidget(w); w.show()
        self.faceCompareCheckBox.toggled.connect(lambda value: self._set_compare_mode('compare', value))
        self.faceMaskCheckBox.toggled.connect(lambda value: self._set_compare_mode('mask', value))
        head.addWidget(small_button('fit', '适应窗口', lambda: video.fit_view_to_current_image(self)))
        layout.addWidget(head_widget)
        self.canvas_stack = W.QStackedWidget()
        self.empty_canvas = W.QWidget(); self.empty_canvas.setObjectName('canvasPanel')
        empty = W.QVBoxLayout(self.empty_canvas); empty.setAlignment(C.Qt.AlignCenter); empty.setSpacing(14)
        mark = W.QLabel(); mark.setPixmap(icon('image', '#696f79').pixmap(40,40)); mark.setAlignment(C.Qt.AlignCenter)
        empty.addWidget(mark)
        text = label('添加图片或视频'); text.setAlignment(C.Qt.AlignCenter); empty.addWidget(text)
        add = tool('选择文件', 'plus', self.add_targets); add.setFixedWidth(112); empty.addWidget(add,0,C.Qt.AlignHCenter)
        self.canvas_stack.addWidget(self.empty_canvas)
        self.canvas_host = W.QFrame(); self.canvas_host.setObjectName('canvasHost')
        canvas = W.QVBoxLayout(self.canvas_host); canvas.setContentsMargins(22,22,22,22)
        canvas.addWidget(self.graphicsViewFrame); self.graphicsViewFrame.show()
        self.canvas_stack.addWidget(self.canvas_host)
        layout.addWidget(self.canvas_stack, 1)
        self.video_strip = W.QWidget(); self.video_strip.setObjectName('transport')
        vl = W.QVBoxLayout(self.video_strip); vl.setContentsMargins(16,8,16,8); vl.setSpacing(4)
        self.timelineScrollArea.setMinimumHeight(36); self.timelineScrollArea.setMaximumHeight(170)
        vl.addWidget(self.timelineScrollArea)
        row = W.QHBoxLayout(); row.setSpacing(6)
        for w, symbol, tip in [(self.frameRewindButton,'previous','上一帧'), (self.buttonMediaPlay,'play','播放 / 暂停'),
                               (self.frameAdvanceButton,'next','下一帧'), (self.liveSoundButton,'sound','播放声音')]:
            w.setIcon(icon(symbol)); w.setText(''); w.setObjectName('toolAction')
            w.setIconSize(C.QSize(16,16)); w.setFixedSize(30,28); w.setToolTip(tip); w.setAccessibleName(tip)
            row.addWidget(w); w.show()
        row.addSpacing(6)
        row.addWidget(self.videoTimeLineEdit); self.videoTimeLineEdit.setFixedWidth(60)
        row.addStretch()
        row.addWidget(label('帧', 'muted')); row.addWidget(self.videoSeekLineEdit)
        row.addWidget(label('FPS', 'muted')); row.addWidget(self.videoFpsLineEdit)
        row.addWidget(small_button('dots', '时间线与片段', lambda: self.open_settings('时间线与片段')))
        vl.addLayout(row); layout.addWidget(self.video_strip)
        self.video_strip.hide()
        body.addWidget(self.canvas_panel, 1)

    def _style_parameters(self):
        from app.ui.widgets.widget_components import ToggleButton
        for toggle in self.findChildren(ToggleButton):
            # Generic button padding/min-height must not stretch painted switches.
            toggle.setStyleSheet('padding: 0; margin: 0; min-height: 0; border: 0; background: transparent;')
            toggle.setFixedSize(30, 15)
            toggle._bg_color = '#4c5159'; toggle._active_color = '#82bba7'
        for editor in self.tabWidget.findChildren(W.QLineEdit) + self.tabWidget.findChildren(W.QComboBox):
            editor.setFixedHeight(28)
            editor.setStyleSheet('padding: 2px 6px; min-height: 0;')
        for widget in self.parameter_widgets.values():
            caption = getattr(widget, 'label_widget', None)
            if caption:
                caption.setMinimumWidth(0)
                caption.setWordWrap(True)
                caption.setSizePolicy(W.QSizePolicy.Expanding, W.QSizePolicy.Preferred)
            if isinstance(widget, W.QComboBox):
                widget.setMinimumWidth(100); widget.setMaximumWidth(190)
                widget.setSizePolicy(W.QSizePolicy.Expanding, W.QSizePolicy.Fixed)
            if isinstance(widget, W.QSlider):
                widget.setFixedWidth(104)
            reset = getattr(widget, 'reset_default_button', None)
            if reset:
                reset.setFixedSize(24,24); reset.setIcon(icon('reset')); reset.setIconSize(C.QSize(14,14))
                reset.setStyleSheet('padding: 2px; min-height: 0;')
        from .labels import SECTIONS
        for section in self.parameter_sections.values():
            form = section.content_widget.layout()
            if isinstance(form, W.QFormLayout):
                form.setContentsMargins(6,4,6,6)
                form.setVerticalSpacing(2)
                for i in range(form.rowCount()):
                    field = form.itemAt(i, W.QFormLayout.SpanningRole) or form.itemAt(i,W.QFormLayout.FieldRole)
                    row = field.widget() if field else None
                    if row and row.layout():
                        row.setMinimumHeight(30)
                        row.layout().setContentsMargins(2,3,2,3)
                        row.layout().setSpacing(6)
            section.updateGeometry()
            header = section.header_button
            header._title = SECTIONS.get(header._title, header._title)
            header.setFixedHeight(28)
            header.update()

    def sync_presentation(self):
        if not hasattr(self, 'document_title'):
            return
        selected = self.selected_video_button
        media_type = self.video_processor.file_type
        key = (id(selected), media_type, len(self.target_videos), len(self.input_faces), len(self.target_faces))
        if key != self._presentation_key:
            self._presentation_key = key
            self.document_title.setText(Path(selected.media_path).name if selected else '预览')
            self.canvas_stack.setCurrentIndex(1 if selected else 0)
            self.video_strip.setVisible(media_type in ('video', 'webcam'))
            self.export_button.setEnabled(selected is not None and media_type != 'webcam')
            self.faceCompareCheckBox.setEnabled(selected is not None)
            self.faceMaskCheckBox.setEnabled(selected is not None)
            C.QTimer.singleShot(0, lambda: video.fit_view_to_current_image(self))
        for kind, view in [('media', self.targetVideosList), ('source', self.inputFacesList), ('target', self.targetFacesList)]:
            count = view.count()
            self.section_counts[kind].setText(str(count))
            if hasattr(view, 'placeholder_label'):
                view.placeholder_label.setVisible(count == 0)
            # Scale with contents, rather than giving a single face half the window.
            height = min(224, max(86, count * 62 + 8)) if kind == 'media' else min(168, max(86, ((count+1)//2)*84+4))
            view.setFixedHeight(height)
            for i in range(count):
                item = view.item(i); card = view.itemWidget(item)
                if card is not None and not card.property('studioCard'):
                    self.style_asset_card(card, item, kind, i)
        assigned = sum(bool(f.assigned_input_faces or f.assigned_merged_embeddings) for f in self.target_faces.values())
        self.mapping_label.setText(f'已匹配 {assigned} / {len(self.target_faces)} 个人脸' if self.target_faces else '识别素材中的人脸')

    def style_asset_card(self, card, item, kind, index):
        card.setProperty('studioCard', True)
        card.setFocusPolicy(C.Qt.StrongFocus)
        if kind == 'media':
            card.setObjectName('mediaRow'); card.setFixedSize(200, 58)
            item.setSizeHint(C.QSize(200,58))
            old = card.layout()
            while old.count(): old.takeAt(0)
            old.setContentsMargins(6,6,6,6); old.setSpacing(9)
            old.setDirection(W.QBoxLayout.LeftToRight)
            card.thumbnail_label.setFixedSize(48,42)
            card.thumbnail_label.setAlignment(C.Qt.AlignCenter)
            old.addWidget(card.thumbnail_label)
            card.text_label.hide()
            text = W.QWidget(); text.setStyleSheet('background: transparent;'); column = W.QVBoxLayout(text); column.setContentsMargins(0,0,0,0); column.setSpacing(3)
            name = ElidedLabel(Path(card.media_path).name)
            name.setAttribute(C.Qt.WA_TransparentForMouseEvents)
            column.addWidget(name)
            subtitle = label('视频' if card.file_type == 'video' else '摄像头' if card.file_type == 'webcam' else '图片', 'muted')
            column.addWidget(subtitle); old.addWidget(text,1)
            text.setAttribute(C.Qt.WA_TransparentForMouseEvents)
            card._update_thumbnail_pixmap()
        else:
            card.setObjectName('faceCard'); card.setFixedSize(76,76)
            card.setIconSize(C.QSize(68,68)); item.setSizeHint(C.QSize(82,80))
            if hasattr(card, 'display_label'):
                card.display_label.setText(f'人脸 {index+1}')
                card.display_label.setStyleSheet('background: rgba(20,22,25,190); color: #e0e5e2; font-size: 10px; padding: 2px 3px;')
                card.display_label.setFixedHeight(18)
            card.setAccessibleName(('替换对象' if kind == 'target' else '参考人脸') + f' {index+1}')
        card.style().unpolish(card); card.style().polish(card)

    def eventFilter(self, watched, event):
        if watched is getattr(self, 'graphicsViewFrame', None) and event.type() == C.QEvent.Resize and hasattr(self, '_fit_timer'):
            self._fit_timer.start(40)
        return super().eventFilter(watched, event)

    def toggle_settings(self):
        if self.drawer.isVisible():
            self.close_settings()
        else:
            self.open_settings(self.section_choice.currentText())

    def guide_inputs(self):
        if self._auto_busy or self._models_busy or self._exporting or self.video_processor.processing or (self.job_processor and self.job_processor.isRunning()):
            return
        if any(w and w.isRunning() for w in (self.video_loader_worker, self.input_faces_loader_worker)):
            return
        if not self.target_videos or not self.input_faces:
            return
        if getattr(self, '_pending_target_media_thumbnails', None) or getattr(self, '_pending_input_face_thumbnails', None):
            return
        self._auto_busy = True
        try:
            if self.selected_video_button is None:
                next(iter(self.target_videos.values())).click()
            key = (id(self.selected_video_button), tuple(self.input_faces))
            if key == self._auto_seen:
                return
            self._auto_seen = key
            if not self.target_faces:
                from app.ui.widgets.actions.card_actions import find_target_faces
                find_target_faces(self)
            if len(self.target_faces) == 1 and len(self.input_faces) == 1:
                target = next(iter(self.target_faces.values()))
                if not target.assigned_input_faces and not target.assigned_merged_embeddings:
                    target.click()
                    source = next(iter(self.input_faces.values()))
                    target.assigned_input_faces = {source.face_id: source.embedding_store}
                    target.calculate_assigned_input_embedding()
                    source.setChecked(True)
                    self.swapfacesButton.setChecked(True)
                    common.refresh_frame(self)
                self.notice('可调整效果或直接导出')
            elif self.target_faces:
                self.notice('先选替换对象，再选参考人脸')
            else:
                self.notice('未找到人脸，请换一帧或更换素材')
        except Exception as exc:
            self.notice(f'读取失败：{exc}')
        finally:
            self._auto_busy = False

    def _configure_faces_panel_button_column(self):
        pass

    def _build_drawer(self):
        self.drawer = W.QFrame(self.workspace_body)
        self.drawer.setObjectName('settingsDrawer')
        d = W.QVBoxLayout(self.drawer)
        d.setContentsMargins(12, 10, 12, 10)
        head = W.QHBoxLayout()
        self.section_choice = W.QComboBox()
        head.addWidget(self.section_choice, 1)
        head.addWidget(small_button('close', '关闭设置', self.close_settings))
        d.addLayout(head)
        self.drawer_stack = W.QStackedWidget()
        d.addWidget(self.drawer_stack, 1)
        self.pages = {}
        # Preserve QTabWidget indices used by upstream callbacks while replacing its
        # dense tab strip with one section selector.
        self.tabWidget.tabBar().hide()
        self.drawer_stack.addWidget(self.tabWidget)
        titles = ['换脸与遮罩', '表情与姿态', '画质修复', '降噪', '运行与导出', '预设']
        for i, title in enumerate(titles):
            self.pages[title] = (0, i)
            self.section_choice.addItem(title)
        for title, widget in [('模型与下载', self._model_page()),
                              ('批量任务', self.jobManagerDockWidget.widget()),
                              ('素材筛选与摄像头', self.input_Target_DockWidget.widget()),
                              ('参考脸文件夹', self.input_Faces_DockWidget.widget()),
                              ('人脸库与批量图片', self.facesPanelGroupBox)]:
            self.add_page(title, widget)
        self.section_choice.currentTextChanged.connect(self.select_section)
        self.editFacesButton.setText('启用人脸编辑')
        edit_row = W.QHBoxLayout()
        edit_row.addWidget(self.editFacesButton)
        self.faceEditorWidgetsLayout.insertLayout(0, edit_row)
        self.editFacesButton.show()
        tools = W.QWidget()
        tl = W.QVBoxLayout(tools)
        for w, title in [(self.addMarkerButton, '添加参数标记'), (self.removeMarkerButton, '删除参数标记'),
                         (self.previousMarkerButton, '上一个标记'), (self.nextMarkerButton, '下一个标记'),
                         (self.buttonMediaRecord, '从当前帧导出 / 停止'),
                         (self.viewFullScreenButton, '全屏'), (self.theatreModeButton, '专注预览'),
                         (self.scanToolsToggleButton, '问题帧检查')]:
            w.setText(title)
            w.setMaximumWidth(16777215)
            tl.addWidget(w)
        tl.addStretch()
        self.add_page('时间线与片段', tools)
        self.add_page('导出记录', self._history_page())
        for name in ('_media_controls_separator', '_media_controls_view_separator'):
            item = getattr(self, name, None)
            if item:
                item.hide()
        zoom_row = W.QHBoxLayout()
        zoom_row.addWidget(self.zoomLabel)
        zoom_row.addWidget(self.timelineZoomSlider)
        tl.insertLayout(0, zoom_row)
        self.body_layout.addWidget(self.drawer)
        self.drawer.hide()

    def restoreState(self, state, version=0):
        # Fusion dock geometry is not compatible with the Studio drawer.
        return False

    def _set_panel_visibility(self, panel_key, checked):
        self.panel_visibility_state[panel_key] = bool(checked)

    def _on_faces_panel_toggled(self, checked):
        pass

    def add_page(self, title, widget):
        scroll = W.QScrollArea()
        scroll.setWidgetResizable(True)
        widget.setMinimumWidth(0)
        scroll.setWidget(widget)
        index = self.drawer_stack.addWidget(scroll)
        self.pages[title] = (index, None)
        self.section_choice.addItem(title)
        widget.show()

    def select_section(self, title):
        index, tab = self.pages[title]
        self.drawer_stack.setCurrentIndex(index)
        if tab is not None:
            self.tabWidget.setCurrentIndex(tab)

    def open_settings(self, title):
        self.section_choice.setCurrentText(title)
        self.select_section(title)
        self.place_drawer()
        self.drawer.show()
        self.drawer.raise_()
        self.section_choice.setFocus()
        C.QTimer.singleShot(0, lambda: video.fit_view_to_current_image(self))

    def close_settings(self):
        if not getattr(self, '_models_busy', False):
            if not self.drawer.isVisible() and self.isFullScreen():
                self.showNormal()
            self.drawer.hide()
            C.QTimer.singleShot(0, lambda: video.fit_view_to_current_image(self))

    def focusNextPrevChild(self, forward):
        drawer = getattr(self, 'drawer', None)
        if drawer is None or not drawer.isVisible():
            return super().focusNextPrevChild(forward)
        candidate = self.focusWidget() or self.section_choice
        for _ in range(6000):
            candidate = candidate.nextInFocusChain() if forward else candidate.previousInFocusChain()
            if drawer.isAncestorOf(candidate) and candidate.isVisibleTo(drawer) and candidate.isEnabled() and candidate.focusPolicy() & C.Qt.TabFocus:
                candidate.setFocus(C.Qt.TabFocusReason if forward else C.Qt.BacktabFocusReason)
                return True
        return False

    def place_drawer(self):
        self.drawer.setFixedWidth(min(480, max(420, self.width() // 3)))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'drawer'):
            self.place_drawer()

    def _model_page(self):
        page = W.QWidget()
        layout = W.QVBoxLayout(page)
        search = W.QLineEdit()
        search.setPlaceholderText('搜索模型')
        layout.addWidget(search)
        self.model_list = W.QListWidget()
        self.model_list.setSelectionMode(W.QAbstractItemView.ExtendedSelection)
        for r in RESOURCES:
            item = W.QListWidgetItem(f'{r.name} · {r.size / 1024**2:.0f} MB')
            item.setData(C.Qt.UserRole, r.id)
            self.model_list.addItem(item)
        search.textChanged.connect(lambda text: [self.model_list.item(i).setHidden(text.casefold() not in self.model_list.item(i).text().casefold()) for i in range(self.model_list.count())])
        layout.addWidget(self.model_list, 1)
        row = W.QHBoxLayout()
        row.addWidget(button('下载 / 校验', self.prepare_selected))
        row.addWidget(button('导入已有模型', self.import_selected))
        layout.addLayout(row)
        layout.addWidget(button('打开模型文件夹', lambda: G.QDesktopServices.openUrl(C.QUrl.fromLocalFile(str(self.model_service.root)))))
        layout.addWidget(button('导入 DFM 模型', self.import_dfm))
        layout.addWidget(button('更改模型保存位置', self.change_model_directory))
        return page

    def _history_page(self):
        import json
        page = W.QWidget()
        layout = W.QVBoxLayout(page)
        self.history = W.QListWidget()
        layout.addWidget(self.history)
        self.history.itemDoubleClicked.connect(lambda item: G.QDesktopServices.openUrl(C.QUrl.fromLocalFile(item.data(C.Qt.UserRole))))
        try:
            records = json.loads((STATE / 'exports.json').read_text())
            self._records = [r for r in records if isinstance(r, dict) and isinstance(r.get('path'), str) and Path(r['path']).is_absolute()][-100:]
        except (OSError, ValueError, TypeError):
            self._records = []
        self.refresh_history()
        return page

    def refresh_history(self):
        self.history.clear()
        for record in reversed(self._records):
            item = W.QListWidgetItem(Path(record['path']).name)
            item.setData(C.Qt.UserRole, record['path'])
            self.history.addItem(item)

    def remember_output(self, path):
        import json
        self._records = [r for r in self._records if r['path'] != str(path)]
        self._records.append({'name': path.name, 'path': str(path)})
        self._records = self._records[-100:]
        try:
            temp = STATE / 'exports.json.tmp'
            temp.write_text(json.dumps(self._records, ensure_ascii=False))
            os.replace(temp, STATE / 'exports.json')
        except OSError:
            self.notice('文件已导出，记录保存失败')
        self.refresh_history()

    def processing_started(self):
        self.cancel_button.show()
        if self.video_processor.recording:
            folder = Path(video.resolve_output_folder(self, self.video_processor.media_path))
            before = {p: p.stat().st_mtime_ns for p in folder.glob('*') if p.is_file()}
            self._record_snapshot = (folder, before)

    def change_model_directory(self):
        selected = W.QFileDialog.getExistingDirectory(self, '模型保存位置', str(self.model_service.root))
        if selected:
            self.settings.model_dir = Path(selected)
            self.settings.output_dir = Path(self.control['OutputMediaFolder'])
            self.settings.save(STATE)
            self.notice('已保存，重启后使用新的模型位置')

    def studio_toggle_theatre(self):
        self.is_theatre_mode = not getattr(self, 'is_theatre_mode', False)
        self.assets_panel.setVisible(not self.is_theatre_mode)
        self.close_settings()
        if self.control.get('TheatreModeUsesFullscreenToggle'):
            self.showFullScreen() if self.is_theatre_mode else self.showNormal()
        video.fit_view_to_current_image(self)

    def prepare_selected(self, source=None):
        names = [i.data(C.Qt.UserRole) for i in self.model_list.selectedItems()]
        if not names:
            self.notice('请先选择模型')
            return
        self.model_service.cancelled.clear()
        try:
            self.model_service.prepare(names, source)
            self.notice('模型已就绪')
        except Exception as exc:
            self.notice(f'准备未完成：{exc}')

    def import_selected(self):
        source = W.QFileDialog.getExistingDirectory(self, '选择已有模型文件夹')
        if source:
            self.prepare_selected(source)

    def import_dfm(self):
        import shutil
        paths, _ = W.QFileDialog.getOpenFileNames(self, '导入 DFM 模型', '', 'DFM (*.dfm *.onnx)')
        for path in paths:
            dest = Path(self.dfm_model_manager.models_path) / Path(path).name
            if dest.exists():
                self.notice(f'{dest.name} 已存在，未覆盖')
                continue
            shutil.copyfile(path, dest)
        self.dfm_model_manager.refresh_models()
        widget = self.parameter_widgets['DFMModelSelection']
        widget.clear()
        widget.addItems(self.dfm_model_manager.get_selection_values())
        self.notice('DFM 模型列表已更新')

    def add_targets(self):
        self.model_service.cancelled.clear()
        lists.select_target_medias(self, 'files')

    def add_sources(self):
        self.model_service.cancelled.clear()
        lists.select_input_face_images(self, 'files')

    def open_embedding_editor(self):
        if self.embedding_editor_window is None:
            from app.ui.widgets.advanced_embedding_editor import EmbeddingGUI
            self.embedding_editor_window = EmbeddingGUI()
            self.embedding_editor_window.setWindowFlags(C.Qt.Widget)
            self.add_page('人脸特征编辑', self.embedding_editor_window)
        self.open_settings('人脸特征编辑')

    def notice(self, text):
        if hasattr(self, 'status_label'):
            self.status_label.setText(str(text))

    def show_build_dialog(self, title, text):
        self.notice(f'{title}：{text}')

    def hide_build_dialog(self):
        self.notice('就绪')

    def model_busy(self, busy):
        self._models_busy = busy
        locked = busy or getattr(self, '_exporting', False)
        self.workspace_body.setEnabled(not locked)
        self.toolbar.setEnabled(not locked)
        self.drawer.setEnabled(not locked)
        self.progress_bar.setVisible(busy)
        self.cancel_button.setVisible(busy or self.video_processor.processing)

    def model_progress(self, name, state, done, total):
        self.notice(f'{name} · {state} · {done / 1024**2:.0f} / {total / 1024**2:.0f} MB')
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(int(done * 100 / total) if total else 0)

    def export_current(self):
        if self._exporting or self.video_processor.processing:
            self.notice('请先停止播放或等待当前任务完成')
            return
        if self.video_processor.file_type == 'webcam':
            self.notice('摄像头输出请在设置中开启虚拟摄像头')
            return
        if self.video_processor.current_frame is None:
            self.notice('请先添加素材')
            return
        self.model_service.cancelled.clear()
        self._studio_processing_defaults()
        if self.video_processor.file_type == 'image':
            self._export_compare = (self.view_face_compare_enabled, self.view_face_mask_enabled)
            for widget in (self.faceCompareCheckBox, self.faceMaskCheckBox):
                with C.QSignalBlocker(widget):
                    widget.setChecked(False)
            self.view_face_compare_enabled = False
            self.view_face_mask_enabled = False
            self._image_export_pending = True
            self._exporting = True
            self.video_processor.last_processing_error = None
            self.video_processor._fatal_processing_error_latched = False
            self.set_export_busy(True)
            self.notice('正在导出图片…')
            self.video_processor.process_current_frame(synchronous=False)
        else:
            # Default export covers the whole clip. Explicit segment markers remain respected.
            if not self.job_marker_pairs:
                with C.QSignalBlocker(self.videoSeekSlider):
                    self.videoSeekSlider.setValue(0)
                self.video_processor.current_frame_number = 0
            self.video_processor.worker_pool_manager.cancel_single_frame_preview_state()
            self._exporting = True
            self.set_export_busy(True)
            self.buttonMediaRecord.setChecked(True)


    def set_export_busy(self, busy):
        self.workspace_body.setEnabled(not busy and not self._models_busy)
        self.drawer.setEnabled(not busy and not self._models_busy)
        self.toolbar.setEnabled(not busy and not self._models_busy)
        self.cancel_button.setVisible(busy or self._models_busy)

    def finish_image_export(self, generation, frame_number, frame, cache):
        if not self._image_export_pending:
            return
        pool = self.video_processor.worker_pool_manager
        if generation != pool.active_single_frame_request_generation:
            return
        self._image_export_pending = False
        try:
            if self.video_processor.last_processing_error:
                raise RuntimeError(self.video_processor.last_processing_error)
            from .outputs import snapshot, completed_output
            source = Path(self.video_processor.media_path)
            folder = Path(video.resolve_output_folder(self, str(source)))
            before = snapshot(folder, source)
            video.save_current_frame_to_file(self)
            result = completed_output(folder, source, before)
            if not result:
                raise RuntimeError('未生成有效图片，请检查导出位置')
            self.remember_output(result)
            self.notice('已导出：' + result.name)
        except Exception as exc:
            self.notice(f'导出失败：{exc}')
        finally:
            self._exporting = False
            self.restore_export_view()
            self.set_export_busy(False)

    def restore_export_view(self):
        previous = getattr(self, '_export_compare', None)
        if previous is None:
            return
        self._export_compare = None
        self.view_face_compare_enabled, self.view_face_mask_enabled = previous
        for widget, checked in zip((self.faceCompareCheckBox, self.faceMaskCheckBox), previous):
            with C.QSignalBlocker(widget):
                widget.setChecked(checked)
        if any(previous):
            C.QTimer.singleShot(0, lambda: common.refresh_frame(self))

    def cancel_active(self):
        self._record_snapshot = None
        if self.job_processor and self.job_processor.isRunning():
            self.job_processor.request_cancel('Cancelled in Studio')
        self._image_export_pending = False
        self._exporting = False
        self.restore_export_view()
        self.set_export_busy(False)
        self.model_service.cancelled.set()
        self.video_processor.stop_processing()
        self.notice('已取消')
        self.retry_button.show()

    def retry_processing(self):
        self.model_service.cancelled.clear()
        self.video_processor.last_processing_error = None
        self.video_processor._fatal_processing_error_latched = False
        self.retry_button.hide()
        self._auto_seen = None
        common.refresh_frame(self)

    def processing_error(self, text):
        self._record_snapshot = None
        self._image_export_pending = False
        self._exporting = False
        self.restore_export_view()
        self.set_export_busy(False)
        self.notice(f'处理失败：{text}')
        self.retry_button.show()

    def processing_progress(self, *args):
        if self._exporting:
            self.notice(f'正在导出 · {self.video_processor.current_frame_number + 1} / {self.video_processor.max_frame_number + 1}')

    def processing_stopped(self):
        recording = self._record_snapshot
        self._record_snapshot = None
        if recording and not self.video_processor.last_processing_error:
            folder, before = recording
            for path in folder.glob('*'):
                if path.suffix.lower() in ('.mp4', '.mkv', '.mov') and path.is_file() and path.stat().st_size > 0 and path.stat().st_mtime_ns != before.get(path):
                    self.remember_output(path)
        self.cancel_button.setVisible(self._models_busy)
        if self._exporting:
            self._exporting = False
            self.set_export_busy(False)
            self.notice('处理结束，请在结果文件夹查看输出')

    def closeEvent(self, event):
        for name in ('guide_timer', 'presentation_timer', '_fit_timer'):
            timer = getattr(self, name, None)
            if timer:
                timer.stop()
        track = getattr(self.timelineContainer, 'thumbnail_track', None)
        thumbnail_worker = getattr(track, 'worker', None)
        if track:
            track.resize_timer.stop()
        thumbnail_busy = thumbnail_worker and thumbnail_worker.isRunning()
        if thumbnail_busy:
            thumbnail_worker.cancel()
        worker = self.video_processor.worker_pool_manager.current_single_frame_worker
        pending = thumbnail_busy or getattr(self, '_models_busy', False) or (worker and worker.is_alive()) or (self.job_processor and self.job_processor.isRunning())
        if pending:
            self.model_service.cancelled.set()
            if worker:
                worker.stop_event.set()
            if self.job_processor and self.job_processor.isRunning():
                self.job_processor.request_cancel('Closing Studio')
            self.notice('正在停止处理…')
            event.ignore()
            if not getattr(self, '_close_scheduled', False):
                self._close_scheduled = True
                C.QTimer.singleShot(300, self.retry_close)
            return
        super().closeEvent(event)

    def retry_close(self):
        self._close_scheduled = False
        self.close()
