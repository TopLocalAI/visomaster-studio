"""Regression for Studio video export on machines without NVENC."""
import json
import shutil
import subprocess

import pytest

np = pytest.importorskip('numpy')
from app.processors.video_utils.video_encoding import FFmpegEncoder


def test_portable_encoder_writes_all_frames(tmp_path):
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        pytest.skip('FFmpeg required')
    output = tmp_path / 'out.mp4'
    encoder = FFmpegEncoder()
    assert encoder.start_process(str(output), 64, 48, 4, {'StudioSoftwareEncode': True, 'FFQualitySlider': 18})
    try:
        for i in range(8):
            frame = np.full((48, 64, 3), i * 30, dtype=np.uint8)
            assert encoder.write_frame(frame)
    finally:
        encoder.close_process()
    info = json.loads(subprocess.check_output([
        'ffprobe', '-v', 'error', '-count_frames', '-show_streams', '-of', 'json', str(output)
    ]))['streams'][0]
    assert info['codec_name'] == 'h264'
    assert info['nb_read_frames'] == '8'
    assert float(info['duration']) == 2.0


def test_upstream_encoder_default_remains_unchanged(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr('app.processors.video_utils.video_encoding.subprocess.Popen',
                        lambda args, **kwargs: calls.append(args) or object())
    encoder = FFmpegEncoder()
    assert encoder.start_process(str(tmp_path / 'out.mp4'), 64, 48, 4, {})
    assert calls[0][calls[0].index('-c:v') + 1] == 'hevc_nvenc'
