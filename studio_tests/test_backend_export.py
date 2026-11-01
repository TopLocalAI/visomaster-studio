"""Export rules without models: ordering, frame count, audio, failure and cancel cleanup."""
import subprocess
import threading

import numpy as np
import pytest

from app.backend import export as ex
from app.backend.host import ProcessingError, Toggle
from app.backend.media import FrameReader, probe


class FakeHost:
    def __init__(self, fail_at=None, cancel_at=None, cancel=None):
        self.schema = {"defaults": {"global": {"Mode": "default"}, "face": {}}}
        self.markers = {}
        self.parameters = {"f": {"Value": 1}}
        self.control = {"nThreadsSlider": 3, "StudioSoftwareEncode": True, "StudioStrictProcessing": True}
        self.swapfacesButton = Toggle(True)
        self.editFacesButton = Toggle(False)
        self.fail_at, self.cancel_at, self.cancel = fail_at, cancel_at, cancel
        self.seen = []

    def snapshot(self):
        return dict(self.parameters), dict(self.control)

    def new_worker(self):
        return object()

    def render(self, frame, index, options=None, worker=None, state=None, stop=None):
        state = state or self.snapshot()
        self.seen.append((index, state[0]["f"]["Value"], state[1].get("Mode")))
        if index == self.fail_at:
            raise ProcessingError("boom")
        if index == self.cancel_at and self.cancel is not None:
            self.cancel.set()
        return 255 - frame  # deterministic, visibly different from the source


@pytest.fixture(scope="module")
def clip(tmp_path_factory):
    path = tmp_path_factory.mktemp("media") / "clip.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=128x72:rate=10:duration=2",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-shortest", str(path)], check=True)
    return path


def outputs(folder):
    return sorted(p.name for p in folder.iterdir())


def test_full_clip_keeps_every_frame_and_audio(clip, tmp_path):
    info = probe(clip)
    host = FakeHost()
    path = ex.export_video(host, info, ex.ExportRequest(str(tmp_path)), threading.Event())
    assert ex._count_frames(path) == info.frames == 20
    streams = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(path)],
                             capture_output=True, text=True).stdout.split()
    assert streams == ["video", "audio"]
    assert sorted(i for i, *_ in host.seen) == list(range(20))
    assert outputs(tmp_path) == [path.name]


def test_segment_export(clip, tmp_path):
    info = probe(clip)
    path = ex.export_video(FakeHost(), info, ex.ExportRequest(str(tmp_path), start=5, end=9), threading.Event())
    assert ex._count_frames(path) == 5


def test_frame_failure_aborts_without_output(clip, tmp_path):
    info = probe(clip)
    with pytest.raises(ex.ExportFailed):
        ex.export_video(FakeHost(fail_at=7), info, ex.ExportRequest(str(tmp_path)), threading.Event())
    assert outputs(tmp_path) == []


def test_cancel_removes_partial_files(clip, tmp_path):
    info = probe(clip)
    cancel = threading.Event()
    with pytest.raises(ex.ExportCancelled):
        ex.export_video(FakeHost(cancel_at=4, cancel=cancel), info, ex.ExportRequest(str(tmp_path)), cancel)
    assert outputs(tmp_path) == []


def test_markers_switch_state_at_their_frame(clip, tmp_path):
    info = probe(clip)
    host = FakeHost()
    host.markers = {10: {"parameters": {"f": {"Value": 2}}, "control": {}}}
    ex.export_video(host, info, ex.ExportRequest(str(tmp_path)), threading.Event())
    values = dict((i, (v, mode)) for i, v, mode in host.seen)
    assert values[9] == (1, None)
    # From the marker on: marker parameters, control rebuilt from defaults.
    assert values[10] == (2, "default") and values[19] == (2, "default")


def test_image_export_is_rendered_not_copied(tmp_path):
    import cv2

    src = tmp_path / "in.png"
    cv2.imwrite(str(src), np.full((40, 60, 3), 30, np.uint8))
    out_dir = tmp_path / "out"
    host = FakeHost()
    path = ex.export_image(host, FrameReader(probe(src)), ex.ExportRequest(str(out_dir)))
    assert int(cv2.imread(str(path)).mean()) == 225
    host = FakeHost(fail_at=0)
    with pytest.raises(ProcessingError):
        ex.export_image(host, FrameReader(probe(src)), ex.ExportRequest(str(out_dir)))
    assert outputs(out_dir) == [path.name]


def test_new_faces_inherit_parameters_like_fusion():
    from app.backend.host import HeadlessHost
    from app.helpers.miscellaneous import ParametersDict

    host = HeadlessHost.__new__(HeadlessHost)  # parameter bookkeeping only, no models
    host.default_parameters = ParametersDict({"Restore": False}, {})
    host.default_parameters._default_parameters = host.default_parameters.data
    host.parameters, host.target_faces, host.selected_target_face_id, host.current_widget_parameters = {}, {}, None, {}
    import threading
    host.lock = threading.RLock()
    host.face_parameters("a")["Restore"] = True
    host.select_face("a")
    assert host.face_parameters("b")["Restore"] is True  # inherits selected face
    host.clear_targets()
    assert host.face_parameters("c")["Restore"] is True  # carries to the next media


def test_several_ranges_join_into_one_output(clip, tmp_path):
    info = probe(clip)
    host = FakeHost()
    request = ex.ExportRequest(str(tmp_path), ranges=[(10, 14), (2, 4), (4, 5)])
    path = ex.export_video(host, info, request, threading.Event())
    # (2,4) and (4,5) merge; frames are written in timeline order.
    assert [i for i, *_ in sorted(host.seen)] == [2, 3, 4, 5, 10, 11, 12, 13, 14]
    assert ex._count_frames(path) == 9
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=duration",
                          "-of", "csv=p=0", str(path)], capture_output=True, text=True).stdout.strip()
    assert abs(float(out) - 0.9) < 0.1  # audio cut to the same ranges (10 fps)


def test_output_fps_cap_samples_frames_and_keeps_duration(clip, tmp_path):
    info = probe(clip)  # 20 frames at 10 fps
    host = FakeHost()
    host.control.update(OutputFpsCapEnableToggle=True, OutputMaxFpsSlider=5)
    path = ex.export_video(host, info, ex.ExportRequest(str(tmp_path)), threading.Event())
    assert ex._count_frames(path) == 10
    assert sorted(i for i, *_ in host.seen) == list(range(0, 20, 2))
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=duration",
                          "-of", "csv=p=0", str(path)], capture_output=True, text=True).stdout.strip()
    assert abs(float(out) - 2.0) < 0.15


def test_input_resize_applies_before_processing(clip, tmp_path):
    info = probe(clip)  # 128x72
    host = FakeHost()
    host.control.update(GlobalInputResizeToggle=True, GlobalInputResizeSizeSelection="144p")
    path = ex.export_video(host, info, ex.ExportRequest(str(tmp_path), start=0, end=3), threading.Event())
    size = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                           "-of", "csv=p=0", str(path)], capture_output=True, text=True).stdout.strip()
    assert size == "256,144"
