"""Real-model Studio feature integration, using synthetic test assets only."""
import json, os, sys, time
from pathlib import Path
from PySide6 import QtCore as C, QtWidgets as W, QtTest
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'benchmarks/studio-complete-2026-10-06'
OUT.mkdir(parents=True, exist_ok=True)
os.environ['VISOMASTER_STUDIO_HOME']=str(OUT/'session')
os.environ['VISOMASTER_MODELS_DIR']=str(Path.home()/'Library/Application Support/VisoMasterStudio/models')
app=W.QApplication([])
from app.studio.workspace import StudioWorkspace
from app.ui.widgets.actions import list_view_actions as lists, save_load_actions as projects
w=StudioWorkspace();w.show()
w.control['OutputMediaFolder']=str(OUT/'exports');w.outputFolderLineEdit.setText(str(OUT/'exports'))
w.control['StudioSoftwareEncode']=True
errors=[]
sys.excepthook=lambda typ,val,tb: errors.append(str(val))
def wait(test, timeout=150):
 end=time.monotonic()+timeout
 while not test():
  QtTest.QTest.qWait(50)
  if errors: raise AssertionError(errors)
  if time.monotonic()>end: raise AssertionError('timeout '+w.status_label.text())
result={'ok':False}
try:
 portrait=ROOT/'design/assets/synthetic-portrait.png'
 lists.select_target_medias(w,'studio',files_list=[str(portrait)])
 lists.select_input_face_images(w,'studio',files_list=[str(portrait)])
 wait(lambda: w.target_faces and w.swapfacesButton.isChecked() and not w.video_processor.processing)
 w.video_processor.process_current_frame(synchronous=True)
 assert not errors, errors
 assert next(iter(w.target_faces.values())).assigned_input_faces
 w.grab().save(str(OUT/'workspace.png'))
 # Exercise the actual native callbacks; advanced values persist when drawer closes.
 w.open_settings('画质修复');app.processEvents()
 w.grab().save(str(OUT/'restoration.png'))
 w.parameter_widgets['FaceRestorerEnableToggle'].setChecked(True)
 w.video_processor.process_current_frame(synchronous=True)
 assert w.parameters[w.selected_target_face_id]['FaceRestorerEnableToggle']
 assert w.models_processor.models.get('GFPGANv1.4') or w.models_processor.models.get('GFPGAN-v1.4')
 w.close_settings()
 w.export_current()
 wait(lambda: not w._exporting)
 assert w.status_label.text().startswith('已导出：'), w.status_label.text()
 assert list((OUT/'exports').rglob('*.png'))
 projects.save_current_workspace(w,str(OUT/'project.json'))
 saved=json.loads((OUT/'project.json').read_text())
 result.update(parameters=len(w.parameter_widgets), sources=len(w.input_faces), faces=len(w.target_faces), saved_project=True)
 for title in list(w.pages):
  w.open_settings(title);app.processEvents()
  assert w.drawer.isVisible()
  assert not any(d.isVisible() for d in w.findChildren(W.QDockWidget))
 w.open_embedding_editor();app.processEvents()
 assert w.embedding_editor_window.window() is w
 assert len([x for x in app.topLevelWidgets() if x.isVisible()])==1
 w.close_settings()

 # Restore the project including per-face advanced state, without old docks reappearing.
 w.guide_timer.stop()
 projects.load_saved_workspace(w,str(OUT/'project.json'))
 wait(lambda: bool(w.target_faces) and not (w.input_faces_loader_worker and w.input_faces_loader_worker.isRunning()))
 assert any(p.get('FaceRestorerEnableToggle') for p in w.parameters.values())
 assert not any(d.isVisible() for d in w.findChildren(W.QDockWidget))
 result['project_roundtrip']=True
 # Multiple references are retained and can be assigned independently.
 import shutil
 second=OUT/'second-reference.png';shutil.copy2(portrait,second)
 lists.select_input_face_images(w,'studio',files_list=[str(portrait),str(second)])
 wait(lambda: len(w.input_faces)==2)
 target=next(iter(w.target_faces.values()));target.click()
 sources=list(w.input_faces.values());sources[0].click()
 assert sources[0].face_id in target.assigned_input_faces
 sources[1].click()
 assert sources[1].face_id in target.assigned_input_faces
 result['multiple_references']=True
 # A real full-length video export (32 frames and audio), using the same controller.
 for p in w.parameters.values(): p['FaceRestorerEnableToggle']=False
 w.parameter_widgets['FaceRestorerEnableToggle'].setChecked(False)
 video_path=ROOT/'benchmarks/studio-regression-2026-10-06/fixtures/eight-seconds.mp4'
 if not video_path.exists():
  video_path=ROOT/'benchmarks/macos-package-2026-10-06/assets/eight-seconds.mp4'
 if not video_path.exists():
  video_path=next(ROOT.glob('benchmarks/**/eight-seconds.mp4'))
 lists.select_target_medias(w,'studio',files_list=[str(video_path)])
 wait(lambda: bool(w.target_videos) and not (w.video_loader_worker and w.video_loader_worker.isRunning()))
 next(iter(w.target_videos.values())).click()
 from app.ui.widgets.actions import card_actions as cards
 cards.find_target_faces(w)
 target=next(iter(w.target_faces.values()));target.click()
 source=next(iter(w.input_faces.values()))
 target.assigned_input_faces={source.face_id:source.embedding_store};target.calculate_assigned_input_embedding()
 w.swapfacesButton.setChecked(True)
 w.video_processor.process_current_frame(synchronous=True)
 w.export_current();wait(lambda: not w._exporting,240)
 assert not w.video_processor.last_processing_error,w.video_processor.last_processing_error
 from app.studio.outputs import validate_video_output
 output=max((OUT/'exports').glob('*.mp4'),key=lambda p:p.stat().st_mtime_ns)
 assert validate_video_output(output,video_path)
 result['video_frames_audio_verified']=True
 w.grab().save(str(OUT/'final-workspace.png'))
 result.update(ok=True, pages=list(w.pages), loaded_models=[k for k,v in w.models_processor.models.items() if v])
except Exception:
 import traceback
 result['error']=traceback.format_exc()
finally:
 w.quit_without_saving=True;w.close()
 (OUT/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
 print(json.dumps(result,ensure_ascii=False),flush=True)
 sys.exit(0 if result['ok'] else 1)
