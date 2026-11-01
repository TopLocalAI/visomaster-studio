"""Internal adapter over Fusion's media and processing widgets.

Instantiated exclusively by the offscreen engine; never shown to the user.
No replacement inference implementation and no model downloads in this process.
"""
import os
from pathlib import Path


def editor_class(args):
    os.environ.setdefault('PYTORCH_CUDA_ALLOC_CONF', 'garbage_collection_threshold:0.8')
    import torch
    torch.set_grad_enabled(False)
    from PySide6 import QtCore as C, QtGui as G, QtWidgets as W
    from app.ui.main_ui import MainWindow
    from app.ui.widgets.actions import list_view_actions as lists
    from app.ui.widgets.actions import card_actions as cards
    from app.ui.widgets.actions import video_control_actions as video
    from app.ui.widgets.actions import control_actions as controls
    from app.studio.outputs import snapshot, completed_output
    from app.studio.config import data_root
    from app.studio.theme import STYLE
    from app.studio.window import button, label, panel

    class SimpleEditor(MainWindow):
        def initialize_variables(self):
            super().initialize_variables()
            # Upstream presets/jobs are writable state, never bundle resources.
            self.project_root_path = data_root() / "runtime"
            self.project_root_path.mkdir(parents=True, exist_ok=True)

        def load_last_workspace(self):
            # Fresh simple-mode task: never restore unrelated upstream workspace,
            # old optional models, or ask novices to choose CUDA/TensorRT.
            self.quit_without_saving = True
            self.last_workspace_path = data_root() / 'studio-workspace.json'
            provider = 'CUDA' if torch.cuda.is_available() else 'CPU'
            self.control.update({
                'ProvidersPrioritySelection': provider,
                'RecognitionModelSelection': 'Inswapper128ArcFace',
                'DetectorModelSelection': 'RetinaFace',
                'LandmarkDetectToggle': False, 'KeepInputToggle': False,
                'AutoSwapToggle': False, 'OutputMediaFolder': args.output,
                'VirtualCameraToggle': False, 'StudioSoftwareEncode': True,
                'StudioStrictProcessing': True, 'StudioTempDir': str(Path(args.output) / 'work'),
                'HDREncodeToggle': False, 'FFQualitySlider': 18,
            })
            widget = self.parameter_widgets.get('ProvidersPrioritySelection')
            if widget:
                with C.QSignalBlocker(widget):
                    widget.setCurrentText(provider)
            controls.change_execution_provider(self)
            # Constrain the first Studio slice to the three prepared resources.
            for key in list(self.default_parameters):
                if isinstance(self.default_parameters[key], bool):
                    self.default_parameters[key] = False
            self.default_parameters['SwapModelSelection'] = 'Inswapper128'
            self.default_parameters['SwapperResSelection'] = '128'
            self.current_widget_parameters = self.default_parameters.copy()
            self.outputFolderLineEdit.setText(args.output)

        def __init__(self):
            super().__init__()
            self.setWindowTitle('VisoMaster Studio')
            self.setStyleSheet(STYLE)
            self.resize(1280, 820)
            self._original_central = self.takeCentralWidget()
            self._original_central.hide()
            self._original_central.setParent(self)
            for dock in self.findChildren(W.QDockWidget):
                dock.hide()
            self.menuBar().hide()
            root = W.QWidget()
            layout = W.QVBoxLayout(root)
            layout.setContentsMargins(24, 24, 24, 24)
            layout.setSpacing(18)
            heading = W.QHBoxLayout()
            heading.addWidget(label(Path(args.target).name, 'title'), 1)
            self.results_action = button('打开结果', lambda: G.QDesktopServices.openUrl(C.QUrl.fromLocalFile(str(Path(args.output).resolve()))))
            heading.addWidget(self.results_action)
            self.export_action = button('导出', self.export, True)
            self.export_action.setEnabled(False)
            heading.addWidget(self.export_action)
            layout.addLayout(heading)
            columns = W.QHBoxLayout()
            assets, a = panel()
            assets.setFixedWidth(244)
            a.addWidget(label('参考人脸'))
            a.addWidget(self.inputFacesList, 1)
            self.inputFacesList.show()
            self.inputFacesList.placeholder_label.setText('正在读取…')
            a.addWidget(label('替换对象'))
            self.face_choice = W.QComboBox()
            self.face_choice.currentIndexChanged.connect(self.choose_face)
            a.addWidget(self.face_choice)
            a.addWidget(self.targetFacesList)
            self.targetFacesList.show()
            # Cards are display-only here: combo selection changes the one target.
            self.targetFacesList.setAttribute(C.Qt.WA_TransparentForMouseEvents)
            self.targetFacesList.setFocusPolicy(C.Qt.NoFocus)
            columns.addWidget(assets)
            frame, f = panel()
            self.graphicsViewFrame.setParent(frame)
            f.addWidget(self.graphicsViewFrame, 1)
            self.graphicsViewFrame.show()
            f.addWidget(self.timelineScrollArea)
            self.timelineScrollArea.show()
            actions = W.QHBoxLayout()
            self.original = W.QCheckBox('查看原图')
            self.original.toggled.connect(self.preview_frame)
            actions.addWidget(self.original)
            actions.addStretch()
            self.preview_action = button('预览', self.preview_frame, True)
            self.preview_action.setEnabled(False)
            actions.addWidget(self.preview_action)
            f.addLayout(actions)
            columns.addWidget(frame, 1)
            layout.addLayout(columns, 1)
            self.simple_status = label('正在读取素材…', 'muted')
            layout.addWidget(self.simple_status)
            self.setCentralWidget(root)
            self.inputFacesList.setAttribute(C.Qt.WA_TransparentForMouseEvents)
            self.inputFacesList.setFocusPolicy(C.Qt.NoFocus)
            self.video_processor.processing_heartbeat_signal.connect(self.export_progress)
            self.video_processor.processing_started_signal.connect(self.processing_started)
            self.video_processor.processing_stopped_signal.connect(self.processing_stopped)
            self.video_processor.fatal_processing_error_signal.connect(self.processing_error)
            self._exporting = False
            self._failed = False
            self._cancel_requested = False
            self._output_before = {}
            self._poll_count = 0
            self._load_timer = C.QTimer(self)
            self._load_timer.timeout.connect(self.finish_loading)
            C.QTimer.singleShot(0, self.load_inputs)

        def load_inputs(self):
            # Explicit-file path avoids upstream folder dialogs and webcam scans.
            with C.QSignalBlocker(self.targetVideosFilterWebcamsCheckBox):
                self.targetVideosFilterWebcamsCheckBox.setChecked(False)
            lists.select_target_medias(self, source_type='studio', files_list=[args.target])
            lists.select_input_face_images(self, source_type='studio', files_list=[args.source])
            self._load_timer.start(100)

        def finish_loading(self):
            self._poll_count += 1
            if self._poll_count > 1800:
                self._load_timer.stop()
                self.simple_status.setText('读取时间较长，请重新打开素材')
                return
            if any(worker and worker.isRunning() for worker in (self.video_loader_worker, self.input_faces_loader_worker)):
                return
            if getattr(self, '_pending_target_media_thumbnails', None) or getattr(self, '_pending_input_face_thumbnails', None):
                return
            # Batch thumbnail callbacks may finish on the following event turn.
            if not self.target_videos or not self.input_faces:
                if self._poll_count < 30:
                    return
                self._load_timer.stop()
                self.simple_status.setText('未找到清晰人脸，请换一张照片')
                return
            self._load_timer.stop()
            self.inputFacesList.placeholder_label.hide()
            for source in self.input_faces.values():
                source.setFocusPolicy(C.Qt.NoFocus)
            try:
                next(iter(self.target_videos.values())).click()
                if self.video_processor.file_type == 'video' and getattr(args, 'frame', 0):
                    with C.QSignalBlocker(self.videoSeekSlider):
                        self.videoSeekSlider.setValue(max(0, min(args.frame, self.video_processor.max_frame_number)))
                    self.video_processor.process_current_frame(synchronous=True)
                cards.find_target_faces(self)
                with C.QSignalBlocker(self.face_choice):
                    self.face_choice.clear()
                    self.face_choice.addItem('选择要替换的人脸', None)
                    for i, face_id in enumerate(self.target_faces):
                        self.target_faces[face_id].setFocusPolicy(C.Qt.NoFocus)
                        self.face_choice.addItem(f'人脸 {i + 1}', face_id)
                if not self.target_faces:
                    self.simple_status.setText('素材中未找到人脸，请更换素材')
                elif len(self.input_faces) != 1:
                    self.simple_status.setText('参考照片请只保留一个人脸')
                elif len(self.target_faces) == 1:
                    self.face_choice.setCurrentIndex(1)
                else:
                    self.simple_status.setText('选择要替换的人脸')
            except Exception:
                self.simple_status.setText('素材读取失败，请更换素材重试')

        def choose_face(self, index):
            face_id = self.face_choice.itemData(index)
            if not face_id or len(self.input_faces) != 1:
                self.preview_action.setEnabled(False)
                self.export_action.setEnabled(False)
                return
            for target in self.target_faces.values():
                target.assigned_input_faces.clear()
                target.assigned_merged_embeddings.clear()
                target.calculate_assigned_input_embedding()
            target = self.target_faces[face_id]
            target.click()
            source = next(iter(self.input_faces.values()))
            target.assigned_input_faces = {source.face_id: source.embedding_store}
            target.calculate_assigned_input_embedding()
            source.setChecked(True)
            self.preview_action.setEnabled(True)
            self.preview_frame()

        def preview_frame(self, checked=False):
            if not self.face_choice.currentData() or len(self.input_faces) != 1 or self._exporting:
                return
            self.export_action.setEnabled(False)
            self.simple_status.setText('正在预览…')
            try:
                with C.QSignalBlocker(self.swapfacesButton):
                    self.swapfacesButton.setChecked(not self.original.isChecked())
                self.video_processor.process_current_frame(synchronous=True)
                self.export_action.setEnabled(not self.original.isChecked())
                self.simple_status.setText('')
            except Exception:
                self.simple_status.setText('预览失败，请换一帧重试')

        def export(self):
            import shutil
            if self._exporting:
                self._cancel_requested = True
                self.video_processor.stop_processing()
                self._exporting = False
                self.simple_status.setText('已停止')
                return
            if not self.face_choice.currentData() or self.original.isChecked():
                return
            if self.video_processor.file_type == 'video' and not shutil.which('ffmpeg'):
                self.simple_status.setText('视频导出组件未就绪，请使用完整环境包')
                return
            self._failed = False
            self._cancel_requested = False
            self._output_before = snapshot(Path(args.output), Path(args.target))
            try:
                if self.video_processor.file_type == 'image':
                    video.save_current_frame_to_file(self)
                    saved = completed_output(Path(args.output), Path(args.target), self._output_before)
                    self.simple_status.setText('已保存' if saved else '保存失败，请检查导出位置')
                else:
                    # Always export the full clip, not just the suffix after preview.
                    self.video_processor.worker_pool_manager.cancel_single_frame_preview_state()
                    # Resetting the UI slider must not schedule a competing seek
                    # preview while the export feeder is reading the same capture.
                    with C.QSignalBlocker(self.videoSeekSlider):
                        self.videoSeekSlider.setValue(0)
                    self.video_processor.current_frame_number = 0
                    self._exporting = True
                    self.buttonMediaRecord.setChecked(True)
                    if not self.video_processor.processing:
                        self._exporting = False
                        self.simple_status.setText('未能开始导出，请检查保存位置')
            except Exception:
                self._exporting = False
                self.simple_status.setText('导出失败，请检查保存位置')

        def processing_started(self):
            if self._exporting:
                self.export_action.setText('停止导出')
                self.preview_action.setEnabled(False)
                self.original.setEnabled(False)
                self.face_choice.setEnabled(False)
                self.simple_status.setText('正在导出…')

        def export_progress(self):
            if self._exporting:
                total = max(1, self.video_processor.max_frame_number + 1)
                done = self.video_processor.current_frame_number
                self.simple_status.setText(f'正在导出 {min(99, round(done / total * 100))}%')

        def processing_stopped(self):
            self.export_action.setText('导出')
            self.preview_action.setEnabled(bool(self.face_choice.currentData()))
            self.original.setEnabled(True)
            self.face_choice.setEnabled(True)
            if self._exporting:
                saved = completed_output(Path(args.output), Path(args.target), self._output_before, video=True)
                self.simple_status.setText('已停止' if self._cancel_requested else '已导出' if saved and not self._failed else '导出失败，请重试')
            self._exporting = False

        def processing_error(self, error):
            self._failed = True
            self.simple_status.setText('处理失败，请换一帧或重试')

        def keyPressEvent(self, event):
            # Do not expose upstream hotkeys that bypass simple-mode validation.
            if event.key() == C.Qt.Key_Space:
                self.preview_frame()
            elif event.key() == C.Qt.Key_S and event.modifiers() & C.Qt.ControlModifier:
                if self.export_action.isEnabled():
                    self.export()
            else:
                W.QMainWindow.keyPressEvent(self, event)

        def closeEvent(self, event):
            if self._exporting:
                self.simple_status.setText('请先停止导出')
                event.ignore()
                return
            self._load_timer.stop()
            super().closeEvent(event)

    return SimpleEditor

