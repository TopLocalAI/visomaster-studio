"""Exercise the redesigned workspace against real controller/model state."""
import json, os, sys, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'benchmarks/studio-ui-2026-10-06'; OUT.mkdir(exist_ok=True)
os.environ['VISOMASTER_STUDIO_HOME']=str(OUT/'session')
os.environ['VISOMASTER_MODELS_DIR']=str(Path.home()/'Library/Application Support/VisoMasterStudio/models')
sys.path.insert(0, str(ROOT/'desktop'))
from PySide6 import QtWidgets as W, QtCore as C, QtTest
from app.studio.runtime import configure_runtime
configure_runtime()
app=W.QApplication([])
from app.studio.workspace import StudioWorkspace
from app.ui.widgets.actions import list_view_actions as lists, save_load_actions as projects
w=StudioWorkspace();w.show(); errors=[]
def exception(typ,value,tb):
 import traceback
 traceback.print_exception(typ,value,tb);errors.append(str(value))
sys.excepthook=exception

def wait(test, timeout=100):
 end=time.monotonic()+timeout
 while not test():
  QtTest.QTest.qWait(50)
  if errors: raise AssertionError(errors)
  if time.monotonic()>end: raise AssertionError('timeout: '+w.status_label.full_text)

result={'ok':False}
try:
 QtTest.QTest.qWait(300)
 w.grab().save(str(OUT/'empty.png'))
 portrait=ROOT/'design/assets/synthetic-portrait.png'
 lists.select_target_medias(w,'studio',files_list=[str(portrait)])
 lists.select_input_face_images(w,'studio',files_list=[str(portrait)])
 wait(lambda: w.target_faces and w.swapfacesButton.isChecked() and not w.video_processor.processing)
 w.video_processor.process_current_frame(synchronous=True)
 w.sync_presentation(); QtTest.QTest.qWait(200)
 assert not w.video_strip.isVisible(), 'image should not show video tools'
 assert not w.inputFacesList.placeholder_label.isVisible(), 'loaded list must not show empty text'
 assert len(w.parameter_widgets)==427
 assert next(iter(w.target_faces.values())).assigned_input_faces
 w.grab().save(str(OUT/'image.png'))
 w.open_settings('画质修复'); QtTest.QTest.qWait(200)
 w.grab().save(str(OUT/'inspector.png'))
 assert w.drawer.x() >= w.canvas_panel.geometry().right(), 'inspector must not cover preview'
 for title in w.pages:
  w.open_settings(title);app.processEvents()
  assert w.drawer.isVisible()
 w.open_embedding_editor();app.processEvents()
 assert w.embedding_editor_window.window() is w
 assert len([x for x in app.topLevelWidgets() if x.isVisible()])==1
 w.close_settings()
 w.resize(980,640); QtTest.QTest.qWait(200)
 w.grab().save(str(OUT/'compact.png'))
 assert w.assets_panel.geometry().bottom() <= w.workspace_body.height()
 w.resize(1280,820)
 # Export validates new widget parenting doesn't alter processing state.
 w.control['OutputMediaFolder']=str(OUT/'exports'); w.outputFolderLineEdit.setText(str(OUT/'exports'))
 w.export_current(); wait(lambda:not w._exporting)
 assert w.status_label.full_text.startswith('已导出：'), w.status_label.full_text
 clip=ROOT/'benchmarks/studio-complete-2026-10-06/queue/clip.mp4'
 lists.select_target_medias(w,'studio',files_list=[str(clip)])
 wait(lambda: bool(w.target_videos) and not (w.video_loader_worker and w.video_loader_worker.isRunning()))
 next(iter(w.target_videos.values())).click()
 w.sync_presentation(); QtTest.QTest.qWait(300)
 assert w.video_strip.isVisible(), 'video must have transport'
 assert w.timelineScrollArea.isVisible()
 w.grab().save(str(OUT/'video.png'))
 assert w.graphicsViewFrame.horizontalScrollBar().maximum() == 0, 'video should fit canvas'
 assert w.graphicsViewFrame.verticalScrollBar().maximum() == 0, 'video should fit canvas'
 result.update(ok=True,parameters=len(w.parameter_widgets),one_window=True,source_mapping=True,image_export=True,image_controls_hidden=True,video_controls_visible=True,pages=list(w.pages),errors=errors)
finally:
 w.quit_without_saving=True;w.close()
 wait(lambda: not w.isVisible(),30)
 result['clean_close']=True
 (OUT/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps(result,ensure_ascii=False),flush=True)
 sys.exit(0 if result['ok'] else 1)
