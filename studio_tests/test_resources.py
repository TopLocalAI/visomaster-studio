import hashlib
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import requests

from app.studio.config import Settings
from app.studio.resources import Resource, verify
from app.studio.downloads import Downloader, DownloadError, model_lock

DATA = b'studio-resource\x00' * 70000


@pytest.fixture
def resource():
    return Resource('test', '测试模型', 'test.onnx', len(DATA), hashlib.sha256(DATA).hexdigest(),
                    ('https://models.example/file',))


@pytest.fixture
def http(monkeypatch):
    state = {'mode': 'normal', 'ranges': [], 'paths': []}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_GET(self):
            state['ranges'].append(self.headers.get('Range'))
            state['paths'].append(self.path)
            if self.path == '/fail':
                self.send_error(503)
                return
            offset = int(self.headers.get('Range', 'bytes=0-')[6:-1])
            partial = bool(self.headers.get('Range')) and state['mode'] != 'ignore'
            body = DATA[offset:] if partial else DATA
            if state['mode'] == 'corrupt':
                body = b'X' * len(body)
            self.send_response(206 if partial else 200)
            if partial:
                start = offset + 1 if state['mode'] == 'bad-range' else offset
                self.send_header('Content-Range', f'bytes {start}-{len(DATA)-1}/{len(DATA)}')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    original = requests.Session.get
    def get(session, url, **kwargs):
        return original(session, f'http://127.0.0.1:{server.server_port}/{url.rsplit("/",1)[-1]}', **kwargs)
    monkeypatch.setattr(requests.Session, 'get', get)
    yield state
    server.shutdown()
    server.server_close()
    thread.join()


def test_valid_existing_file_never_uses_network(tmp_path, resource, monkeypatch):
    dest = resource.path(tmp_path)
    dest.write_bytes(DATA)
    monkeypatch.setattr(requests.Session, 'get', lambda *a, **kw: pytest.fail('network used'))
    Downloader(tmp_path, threading.Event()).prepare([resource])
    assert dest.read_bytes() == DATA


@pytest.mark.parametrize('mode', ['normal', 'ignore'])
def test_range_resume_and_ignored_range_truncate(tmp_path, resource, http, mode):
    http['mode'] = mode
    (tmp_path / 'test.onnx.part').write_bytes(DATA[:999])
    Downloader(tmp_path, threading.Event()).prepare([resource])
    assert http['ranges'][0] == 'bytes=999-'
    assert verify(resource, tmp_path / 'test.onnx')
    assert not (tmp_path / 'test.onnx.part').exists()


def test_invalid_range_never_publishes(tmp_path, resource, http):
    http['mode'] = 'bad-range'
    (tmp_path / 'test.onnx.part').write_bytes(DATA[:999])
    with pytest.raises(DownloadError):
        Downloader(tmp_path, threading.Event()).prepare([resource])
    assert not (tmp_path / 'test.onnx').exists()
    assert (tmp_path / 'test.onnx.part').read_bytes() == DATA[:999]


def test_hash_mismatch_preserves_previous_file(tmp_path, resource, http):
    http['mode'] = 'corrupt'
    (tmp_path / 'test.onnx').write_bytes(b'previous file')
    with pytest.raises(DownloadError):
        Downloader(tmp_path, threading.Event()).prepare([resource])
    assert (tmp_path / 'test.onnx').read_bytes() == b'previous file'
    assert not (tmp_path / 'test.onnx.part').exists()


def test_cancel_then_resume(tmp_path, resource, http):
    cancelled = threading.Event()
    def progress(key, state, done, total):
        if state == '下载中' and done > 0:
            cancelled.set()
    with pytest.raises(InterruptedError):
        Downloader(tmp_path, cancelled, progress).prepare([resource])
    assert not (tmp_path / 'test.onnx').exists()
    assert (tmp_path / 'test.onnx.part').stat().st_size > 0
    Downloader(tmp_path, threading.Event()).prepare([resource])
    assert verify(resource, tmp_path / 'test.onnx')


def test_switches_source_after_failure(tmp_path, resource, http):
    r = Resource(resource.id, resource.name, resource.filename, resource.size, resource.sha256,
                 ('https://models.example/fail', 'https://models.example/file'))
    Downloader(tmp_path, threading.Event()).prepare([r])
    assert http['paths'] == ['/fail', '/fail', '/file']
    assert verify(r, r.path(tmp_path))


def test_import_verifies_without_network(tmp_path, resource, monkeypatch):
    source, dest = tmp_path / '旧 模型', tmp_path / '新 模型'
    source.mkdir()
    (source / resource.filename).write_bytes(DATA)
    monkeypatch.setattr(requests.Session, 'get', lambda *a, **kw: pytest.fail('network used'))
    Downloader(dest, threading.Event()).import_models([resource], source)
    assert verify(resource, dest / resource.filename)
    assert (source / resource.filename).read_bytes() == DATA
    (source / resource.filename).write_bytes(b'bad')
    with pytest.raises(DownloadError):
        Downloader(dest, threading.Event()).import_models([resource], source)
    assert verify(resource, dest / resource.filename)


def test_lock_rejects_concurrent_download(tmp_path):
    with model_lock(tmp_path):
        with pytest.raises(DownloadError):
            with model_lock(tmp_path):
                pytest.fail('lock accepted')


def test_rejects_path_escape_and_symlink(tmp_path, resource):
    with pytest.raises(ValueError):
        Resource('bad', 'bad', '../outside', 1, 'a' * 64, ('https://example.com/file',))
    outside = tmp_path / 'outside'
    outside.write_bytes(b'keep')
    (tmp_path / resource.filename).symlink_to(outside)
    with pytest.raises(ValueError):
        resource.path(tmp_path)
    assert outside.read_bytes() == b'keep'


def test_config_recovers_from_corrupt_file_and_saves_unicode_paths(tmp_path):
    (tmp_path / 'settings.json').write_text('{broken')
    settings = Settings.load(tmp_path)
    assert settings.model_dir == tmp_path / 'models'
    settings.model_dir = tmp_path / '模型 空格'
    settings.save(tmp_path)
    assert Settings.load(tmp_path).model_dir == settings.model_dir
    (tmp_path / 'settings.json').write_text('{"model_dir": "../bad", "output_dir": 123}')
    assert Settings.load(tmp_path).model_dir == tmp_path / 'models'


def test_no_space_has_actionable_error(tmp_path, resource, monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr('app.studio.downloads.shutil.disk_usage', lambda p: SimpleNamespace(free=0))
    with pytest.raises(DownloadError, match='空间不足'):
        Downloader(tmp_path, threading.Event()).prepare([resource])
    assert not resource.path(tmp_path).exists()


def test_partial_symlink_is_not_written(tmp_path, resource):
    outside = tmp_path / 'outside'
    outside.write_bytes(b'keep')
    (tmp_path / 'test.onnx.part').symlink_to(outside)
    with pytest.raises(DownloadError):
        Downloader(tmp_path, threading.Event()).prepare([resource])
    assert outside.read_bytes() == b'keep'


def test_pinned_basic_resources_match_fusion_registry(tmp_path, monkeypatch):
    import importlib
    pytest.importorskip("numpy")
    monkeypatch.setenv('VISOMASTER_MODELS_DIR', str(tmp_path / '模型 目录'))
    from app.processors import models_data
    from app.studio.resources import BASIC_RESOURCES
    data = importlib.reload(models_data)
    for r in BASIC_RESOURCES:
        upstream = next(m for m in data.models_list if m['model_name'] == r.id)
        assert upstream['hash'] == r.sha256
        assert upstream['url'] in r.urls
        assert Path(upstream['local_path']) == tmp_path / '模型 目录' / r.filename


def test_nested_model_download_and_symlink_parent_rejected(tmp_path, resource, monkeypatch):
    from dataclasses import replace
    nested = replace(resource, filename='liveportrait_onnx/test.onnx')
    downloader = Downloader(tmp_path, threading.Event())
    content = b'test model bytes'
    import hashlib
    nested = replace(nested, size=len(content), sha256=hashlib.sha256(content).hexdigest())
    monkeypatch.setattr(downloader, '_transfer', lambda r,u,p: p.write_bytes(content))
    downloader.prepare([nested])
    assert nested.path(tmp_path).read_bytes() == content
    for name in ['../escape', 'a/../../escape', '/absolute', 'a/./b', 'a\\b']:
        with pytest.raises(ValueError):
            replace(nested, filename=name)
    outside = tmp_path / 'outside'; outside.mkdir()
    (tmp_path / 'redirect').symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError):
        replace(nested, filename='redirect/test.onnx').path(tmp_path)


def test_complete_catalog_matches_pinned_fusion_registry():
    from app.studio.catalog import BY_ID
    from app.processors.models_data import models_list
    from pathlib import Path
    for model in models_list:
        resource = BY_ID[model['model_name']]
        assert resource.sha256 == model['hash']
        assert Path(resource.filename).name == Path(model['local_path']).name
        assert model['url'] in resource.urls
