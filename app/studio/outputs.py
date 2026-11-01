"""Check actual outputs before reporting export success."""
import json
from pathlib import Path
import subprocess


def snapshot(directory: Path, source: Path):
    result = {}
    if not directory.is_dir():
        return result
    for p in directory.iterdir():
        if p.is_file() and p.name.startswith(source.stem + '_') and p.suffix.lower() in {'.png', '.jpg', '.jpeg', '.mp4', '.mkv', '.mov'}:
            stat = p.stat()
            result[p] = (stat.st_mtime_ns, stat.st_size)
    return result


def completed_output(directory: Path, source: Path, before, video=False):
    changed = [p for p, stat in snapshot(directory, source).items() if stat != before.get(p) and stat[1] > 0]
    for p in sorted(changed, key=lambda p: p.stat().st_mtime_ns, reverse=True):
        if not video:
            from PySide6.QtGui import QImageReader
            if not QImageReader(str(p)).read().isNull():
                return p
            continue
        try:
            if validate_video_output(p, source):
                return p
        except (OSError, subprocess.SubprocessError, ValueError, TypeError):
            continue
    return None


def probe_media(path: Path):
    probe = subprocess.run(['ffprobe', '-v', 'error', '-count_frames', '-show_streams',
                            '-show_format', '-of', 'json', str(path)],
                           capture_output=True, text=True, timeout=60)
    if probe.returncode:
        raise ValueError('unreadable media')
    return json.loads(probe.stdout)


def validate_video_output(output: Path, source: Path) -> bool:
    """Studio exports the complete clip at source FPS, without frame dropping."""
    original, saved = probe_media(source), probe_media(output)
    def video(metadata):
        return next((s for s in metadata.get('streams', []) if s.get('codec_type') == 'video'), {})
    before, after = video(original), video(saved)
    expected = int(before.get('nb_read_frames', 0))
    actual = int(after.get('nb_read_frames', 0))
    if expected <= 0 or expected != actual:
        return False
    input_duration = float(before.get('duration') or original.get('format', {}).get('duration', 0))
    output_duration = float(after.get('duration') or saved.get('format', {}).get('duration', 0))
    if min(input_duration, output_duration) <= 0 or abs(input_duration-output_duration) > .1:
        return False
    original_audio = next((s for s in original.get('streams', []) if s.get('codec_type') == 'audio'), None)
    saved_audio = next((s for s in saved.get('streams', []) if s.get('codec_type') == 'audio'), None)
    if original_audio:
        if not saved_audio:
            return False
        # Some containers expose duration only at format level.
        before_duration = float(original_audio.get('duration') or original.get('format', {}).get('duration', 0))
        after_duration = float(saved_audio.get('duration') or saved.get('format', {}).get('duration', 0))
        if min(before_duration, after_duration) <= 0 or abs(before_duration-after_duration) > .1:
            return False
    return True
