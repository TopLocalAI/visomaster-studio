"""Queued single-frame previews must never become extra encoded frames."""
from types import SimpleNamespace
from app.processors.video_processor import VideoProcessor


def test_recording_rejects_previews_but_segment_bootstrap_is_retained():
    stored=[]
    vp=SimpleNamespace(main_window=SimpleNamespace(control={'StudioStrictProcessing':True}),
                       processing=True,is_processing_segments=False,
                       worker_pool_manager=SimpleNamespace(active_single_frame_request_generation=7),
                       store_frame_to_display=lambda *args:stored.append(args))
    VideoProcessor.store_single_frame_to_display(vp,7,0,'preview')
    VideoProcessor.store_single_frame_to_display(vp,0,0,'synchronous-preview')
    assert stored==[]
    vp.is_processing_segments=True
    VideoProcessor.store_single_frame_to_display(vp,0,10,'segment-start')
    assert stored==[(10,'segment-start')]
    vp.processing=False;vp.is_processing_segments=False
    VideoProcessor.store_single_frame_to_display(vp,6,0,'stale')
    VideoProcessor.store_single_frame_to_display(vp,7,1,'latest')
    assert stored[-1]==(1,'latest') and len(stored)==2
