from PySide6.QtGui import QImage, QColor
from app.studio.outputs import snapshot, completed_output


def test_old_file_is_not_a_new_success(tmp_path):
    image = QImage(16, 16, QImage.Format_RGB32)
    image.fill(QColor('red'))
    path = tmp_path / 'source_old.png'
    image.save(str(path))
    source = tmp_path / 'source.png'
    before = snapshot(tmp_path, source)
    assert completed_output(tmp_path, source, before) is None


def test_empty_or_corrupt_image_not_success(tmp_path):
    source = tmp_path / 'source.png'
    (tmp_path / 'source_new.png').write_bytes(b'not an image')
    assert completed_output(tmp_path, source, {}) is None


def test_valid_new_image_is_success(tmp_path):
    image = QImage(16, 16, QImage.Format_RGB32)
    image.fill(QColor('red'))
    path = tmp_path / 'source_new.png'
    image.save(str(path))
    assert completed_output(tmp_path, tmp_path / 'source.png', {}) == path


def test_partial_or_muted_video_not_success(tmp_path):
    import subprocess
    from app.studio.outputs import validate_video_output
    source = tmp_path/'source.mp4'
    complete = tmp_path/'complete.mp4'
    partial = tmp_path/'partial.mp4'
    muted = tmp_path/'muted.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=teal:s=64x64:r=4:d=2',
                    '-f', 'lavfi', '-i', 'sine=frequency=440:duration=2', '-c:v', 'libx264',
                    '-c:a', 'aac', '-shortest', '-y', str(source)], check=True)
    import shutil
    shutil.copyfile(source, complete)
    subprocess.run(['ffmpeg','-v','error','-i',str(source),'-t','1','-c','copy','-y',str(partial)],check=True)
    subprocess.run(['ffmpeg','-v','error','-i',str(source),'-c:v','copy','-an','-y',str(muted)],check=True)
    assert validate_video_output(complete, source)
    assert not validate_video_output(partial, source)
    assert not validate_video_output(muted, source)
