"""Offscreen Fusion worker. The Studio window owns all user interaction.

Only prefixed JSON lines are IPC. Upstream diagnostics go to stderr, and no
Fusion widget is ever shown. Each process is scoped to one media pair.
"""
import base64
import json
import os
import sys
import threading

PREFIX = 'STUDIO:'


def run_engine(args):
    if os.name != 'nt':
        os.setsid()  # Lets the owner cancel FFmpeg descendants as well as inference.
    from pathlib import Path
    work = Path(args.output) / 'work'
    work.mkdir(parents=True, exist_ok=True)
    os.chdir(work)
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    # NumPy's tiny embedding GEMV can deadlock in OpenBLAS exec_blas when
    # concurrent Fusion workers contend with the Torch/OpenMP pool (macOS).
    # Set before NumPy is imported; ONNX retains its own inference thread pool.
    os.environ['OPENBLAS_NUM_THREADS'] = '1'
    output = sys.stdout
    sys.stdout = sys.stderr

    def emit(kind, **fields):
        output.write(PREFIX + json.dumps({'type': kind, **fields}, ensure_ascii=False) + '\n')
        output.flush()

    emit('status', text='正在准备预览…')
    from PySide6 import QtCore as C, QtWidgets as W
    from .fusion_editor import editor_class
    from .outputs import completed_output
    from pathlib import Path
    import cv2

    def encode(frame):
        if frame is None:
            return ''
        h, w = frame.shape[:2]
        if max(h, w) > 1600:
            frame = cv2.resize(frame, (round(w * 1600/max(h,w)), round(h * 1600/max(h,w))))
        ok, data = cv2.imencode('.png', frame)
        return base64.b64encode(data).decode('ascii') if ok else ''

    class Inbox(C.QObject):
        received = C.Signal(dict)

    app = W.QApplication([])
    app.setQuitOnLastWindowClosed(False)
    Base = editor_class(args)

    class Engine(Base):
        def __init__(self):
            self.options = {'resolution': '128', 'edge': 5, 'similarity': 60}
            self.request = 0
            self.announced = False
            self.last_status = None
            self.preview_frames = 0
            super().__init__()
            self.video_processor.single_frame_processed_signal.connect(self.frame_completed)
            self.poll = C.QTimer(self)
            self.poll.timeout.connect(self.report)
            self.poll.start(150)
            # Modal dialogs in the inherited UI cannot be interacted with here.
            self.display_messagebox_signal.disconnect()
            self.display_messagebox_signal.connect(lambda *a: emit('error', text='处理失败，请重试或更换素材'))

        def report(self):
            text = self.simple_status.text()
            if text and text != self.last_status:
                self.last_status = text
                emit('status', text=text)
            if not self.announced and not self._load_timer.isActive() and self._poll_count:
                self.announced = True
                faces = [{'id': str(key), 'image': encode(face.cropped_face)} for key, face in self.target_faces.items()]
                emit('ready', faces=faces, selected=self.face_choice.currentIndex()-1,
                     sources=len(self.input_faces), source_image=encode(next(iter(self.input_faces.values())).cropped_face) if len(self.input_faces) == 1 else '', provider=self.models_processor.provider_name,
                     frames=self.video_processor.max_frame_number+1,
                     fps=float(self.video_processor.fps or 1))
                if not faces or len(self.input_faces) != 1:
                    emit('error', text=text or '未找到清晰人脸，请更换照片')

        def apply_options(self):
            face_id = self.face_choice.currentData()
            if not face_id:
                return
            parameters = self.parameters[face_id]
            parameters['SwapperResSelection'] = self.options['resolution']
            parameters['FinalBorderBlendEnableToggle'] = self.options['edge'] > 0
            parameters['FinalBorderBlendAmountSlider'] = max(1, self.options['edge'])
            parameters['SimilarityThresholdSlider'] = self.options['similarity']
            self.current_widget_parameters = parameters.copy()
            self.video_processor.ui_state_is_dirty = True

        def frame_completed(self, *args):
            self.preview_frames += 1

        def preview_frame(self, checked=False):
            if not self.announced:
                return
            self._failed = False
            self.preview_frames = 0
            self.apply_options()
            super().preview_frame(checked)
            if self.export_action.isEnabled() and not self._failed and self.preview_frames:
                vp = self.video_processor
                original = vp._cached_raw_image_bgr if vp.file_type == 'image' else vp._cached_raw_frame_bgr
                emit('preview', request=self.request, frame=vp.current_frame_number,
                     image=encode(vp.current_frame), original=encode(original))
            elif self.face_choice.currentData():
                emit('error', text=self.simple_status.text() or '预览失败，请重试')

        def export(self):
            emit('exporting', progress=0)
            super().export()
            if self.video_processor.file_type == 'image' or not self._exporting:
                self.report_output()

        def export_progress(self):
            super().export_progress()
            if self._exporting:
                total = max(1, self.video_processor.max_frame_number+1)
                emit('exporting', progress=min(99, round(self.video_processor.current_frame_number/total*100)))

        def processing_stopped(self):
            was_exporting = self._exporting
            super().processing_stopped()
            if was_exporting:
                self.report_output()

        def processing_error(self, error):
            super().processing_error(error)
            emit('error', text='处理失败，请重试或更换素材')

        def report_output(self):
            saved = completed_output(Path(args.output), Path(args.target), self._output_before,
                                     video=self.video_processor.file_type == 'video')
            if saved and not self._failed and not self._cancel_requested:
                emit('exported', path=str(saved))
            else:
                emit('error', text=self.simple_status.text() or '导出失败，请重试')

        @C.Slot(dict)
        def command(self, command):
            try:
                action = command.get('action')
                if action == 'close':
                    self.close()
                    app.quit()
                    return
                if action == 'preview':
                    self.request = int(command['request'])
                    opts = command['options']
                    resolution = str(opts['resolution'])
                    if resolution not in ('128', '256', '512'):
                        raise ValueError('resolution')
                    self.options = {'resolution': resolution, 'edge': max(0, min(50, int(opts['edge']))),
                                    'similarity': max(1, min(100, int(opts['similarity'])))}
                    with C.QSignalBlocker(self.videoSeekSlider):
                        self.videoSeekSlider.setValue(max(0, min(int(command['frame']), self.video_processor.max_frame_number)))
                    index = int(command['face']) + 1
                    if not 0 < index < self.face_choice.count():
                        raise ValueError('face')
                    if index != self.face_choice.currentIndex():
                        self.face_choice.setCurrentIndex(index)
                    else:
                        self.preview_frame()
                elif action == 'export':
                    self.export()
            except Exception:
                import traceback
                traceback.print_exc()
                emit('error', text='处理失败，请重试')

    window = Engine()  # Deliberately never call show().
    inbox = Inbox()
    inbox.received.connect(window.command)

    def receive():
        for line in sys.stdin:
            try:
                inbox.received.emit(json.loads(line))
            except (ValueError, TypeError):
                pass
        inbox.received.emit({'action': 'close'})

    threading.Thread(target=receive, daemon=True).start()
    return app.exec()
