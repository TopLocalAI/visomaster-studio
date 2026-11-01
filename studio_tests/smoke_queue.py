"""Two real queued exports, parameter snapshots and cancellation recovery."""
import os,json,time,sys,subprocess
from pathlib import Path
from PySide6 import QtWidgets as W,QtTest
ROOT=Path(__file__).resolve().parents[2];OUT=ROOT/'benchmarks/studio-complete-2026-10-06/queue'
OUT.mkdir(parents=True,exist_ok=True)
os.environ['VISOMASTER_STUDIO_HOME']=str(OUT/'session')
os.environ['VISOMASTER_MODELS_DIR']=str(Path.home()/'Library/Application Support/VisoMasterStudio/models')
subprocess.run(['ffmpeg','-v','error','-y','-i',str(ROOT/'benchmarks/studio-regression-2026-10-06/eight-seconds.mp4'),'-t','1','-c:v','libx264','-c:a','aac',str(OUT/'clip.mp4')],check=True)
app=W.QApplication([])
from app.studio.workspace import StudioWorkspace
from app.ui.widgets.actions import list_view_actions as lists,job_manager_actions as jobs
w=StudioWorkspace();w.show();errors=[]
sys.excepthook=lambda typ,value,tb:errors.append(str(value))
W.QMessageBox.information=lambda *a,**k: W.QMessageBox.Ok
W.QMessageBox.warning=lambda *a,**k: errors.append(str(a[2])) or W.QMessageBox.Ok
W.QMessageBox.critical=lambda *a,**k: errors.append(str(a[2])) or W.QMessageBox.Ok
w.control['OutputMediaFolder']=str(OUT/'exports-fixed');w.outputFolderLineEdit.setText(str(OUT/'exports-fixed'))
w.control['StudioSoftwareEncode']=True

def wait(predicate,timeout=240):
 end=time.monotonic()+timeout
 while not predicate():
  QtTest.QTest.qWait(50)
  if errors:raise AssertionError(errors)
  if time.monotonic()>end:raise AssertionError('timeout '+w.status_label.text())
result={'ok':False}
try:
 lists.select_target_medias(w,'studio',files_list=[str(OUT/'clip.mp4')])
 lists.select_input_face_images(w,'studio',files_list=[str(ROOT/'design/assets/synthetic-portrait.png')])
 wait(lambda:bool(w.target_faces) and w.swapfacesButton.isChecked())
 w.guide_timer.stop()
 w.video_processor.process_current_frame(synchronous=True)
 jobs.save_job(w,'studio-queue-a')
 w.parameter_widgets['FinalBorderBlendEnableToggle'].setChecked(True)
 w.parameter_widgets['FinalBorderBlendAmountSlider'].setValue(8)
 jobs.save_job(w,'studio-queue-b')
 jobs.refresh_job_list(w)
 assert w.jobQueueList.count()==2
 w.open_settings('批量任务');app.processEvents();w.grab().save(str(OUT/'queue.png'))
 jobs.start_job_processor(w,['studio-queue-a','studio-queue-b'])
 completed=[];failed=[]
 w.job_processor.job_completed_signal.connect(completed.append)
 w.job_processor.job_failed_signal.connect(lambda name,error:failed.append((name,error)))
 wait(lambda:w.job_processor is None,360)
 assert completed==['studio-queue-a','studio-queue-b'],completed
 assert not failed,failed
 outputs=list((OUT/'exports-fixed').glob('*.mp4'))
 assert len(outputs)==2,outputs
 from app.studio.outputs import validate_video_output
 assert all(validate_video_output(p,OUT/'clip.mp4') for p in outputs)
 result.update(ok=True,completed=completed,outputs=[p.name for p in outputs],frame_audio_checks=True)
except Exception:
 import traceback
 result['error']=traceback.format_exc()
finally:
 w.quit_without_saving=True;w.close()
 wait(lambda:not w.isVisible(),30)
 (OUT/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
 print(json.dumps(result,ensure_ascii=False),flush=True)
 sys.exit(0 if result['ok'] else 1)
