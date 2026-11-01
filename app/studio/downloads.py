"""Cancellable, resumable downloads. Only verified files become installed."""
from contextlib import contextmanager
from pathlib import Path
import os
import re
import shutil
import threading

import requests
from .resources import Resource, verify


class DownloadError(Exception):
    pass


@contextmanager
def model_lock(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    path = root / ".studio-download.lock"
    with path.open("a+b") as lock:
        if os.name == "nt":
            import msvcrt
            if path.stat().st_size == 0:
                lock.write(b"0")
                lock.flush()
            lock.seek(0)
            try:
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise DownloadError("另一个窗口正在准备模型") from exc
        else:
            import fcntl
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise DownloadError("另一个窗口正在准备模型") from exc
        try:
            yield
        finally:
            if os.name == "nt":
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


class Downloader:
    def __init__(self, root: Path, cancelled: threading.Event, progress=lambda *args: None):
        self.root, self.cancelled, self.progress = root, cancelled, progress

    def check_cancelled(self):
        if self.cancelled.is_set():
            raise InterruptedError("cancelled")

    def prepare(self, resources):
        with model_lock(self.root):
            for resource in resources:
                self.check_cancelled()
                self.download(resource)

    def download(self, r: Resource):
        dest = r.path(self.root)
        dest.parent.mkdir(parents=True, exist_ok=True)
        self.progress(r.id, "校验中", 0, r.size)
        if verify(r, dest, self.cancelled.is_set):
            self.progress(r.id, "已就绪", r.size, r.size)
            return
        part = dest.with_name(dest.name + ".part")
        if part.is_symlink():
            raise DownloadError("请选择其他模型目录")
        # Each mirror must provide exactly the same pinned bytes/hash.
        last_error = "下载未完成，请检查网络后重试"
        for url in r.urls:
            for _ in range(2):
                self.check_cancelled()
                try:
                    self._transfer(r, url, part)
                    self.check_cancelled()
                    self.progress(r.id, "校验中", r.size, r.size)
                    if not verify(r, part, self.cancelled.is_set):
                        part.unlink(missing_ok=True)
                        raise DownloadError("文件校验失败，请重试")
                    self.check_cancelled()
                    os.replace(part, dest)
                    self.progress(r.id, "已就绪", r.size, r.size)
                    return
                except InterruptedError:
                    raise
                except requests.RequestException:
                    last_error = "下载未完成，请检查网络后重试"
                except DownloadError as exc:
                    last_error = str(exc)
                    if '空间不足' in last_error:
                        raise
                except OSError as exc:
                    raise DownloadError("无法写入文件，请检查保存位置") from exc
        raise DownloadError(last_error)

    def _transfer(self, r: Resource, url: str, part: Path):
        offset = part.stat().st_size if part.exists() else 0
        if offset > r.size:
            part.unlink()
            offset = 0
        if offset == r.size:
            return  # interrupted after last byte: verify before any network request
        if shutil.disk_usage(self.root).free < r.size - offset + 16 * 1024 * 1024:
            raise DownloadError("磁盘空间不足，请更换位置")
        headers = {"Accept-Encoding": "identity"}
        if offset:
            headers["Range"] = f"bytes={offset}-"
        # No ambient netrc credentials are sent to mirrors or redirects.
        with requests.Session() as session:
            session.trust_env = False
            with session.get(url, headers=headers, stream=True, timeout=(10, 15)) as response:
                response.raise_for_status()
                if any(h.url.lower().startswith('https:') and h.headers.get('Location', '').lower().startswith('http:') for h in response.history):
                    raise DownloadError("下载地址不可用")
                if response.headers.get("Content-Encoding", "identity").lower() != "identity":
                    raise DownloadError("下载数据异常")
                if response.status_code == 206:
                    match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", response.headers.get("Content-Range", ""))
                    if not match or tuple(map(int, match.groups())) != (offset, r.size - 1, r.size):
                        raise DownloadError("下载数据异常")
                    mode = "ab" if offset else "wb"
                elif response.status_code == 200:
                    offset, mode = 0, "wb"  # server ignored Range: truncate, never append
                else:
                    raise DownloadError("下载数据异常")
                length = response.headers.get("Content-Length")
                if length and (not length.isdigit() or int(length) != r.size - offset):
                    raise DownloadError("下载数据异常")
                if shutil.disk_usage(self.root).free < r.size - offset + 16 * 1024 * 1024:
                    raise DownloadError("磁盘空间不足，请更换位置")
                with part.open(mode) as output:
                    self.progress(r.id, "下载中", offset, r.size)
                    for chunk in response.iter_content(256 * 1024):
                        self.check_cancelled()
                        if not chunk:
                            continue
                        if offset + len(chunk) > r.size:
                            raise DownloadError("下载数据异常")
                        output.write(chunk)
                        offset += len(chunk)
                        self.progress(r.id, "下载中", offset, r.size)
                    output.flush()
                    os.fsync(output.fileno())
                if offset != r.size:
                    raise DownloadError("下载中断")

    def import_models(self, resources, source: Path):
        with model_lock(self.root):
            for r in resources:
                self.check_cancelled()
                src, dest = source / r.filename, r.path(self.root)
                dest.parent.mkdir(parents=True, exist_ok=True)
                self.progress(r.id, "校验中", 0, r.size)
                if not verify(r, src, self.cancelled.is_set):
                    raise DownloadError(f"未找到匹配的{r.name}文件")
                if src.resolve() == dest.resolve():
                    self.progress(r.id, "已就绪", r.size, r.size)
                    continue
                part = dest.with_name(dest.name + ".import")
                if part.is_symlink():
                    raise DownloadError("请选择其他模型目录")
                if shutil.disk_usage(self.root).free < r.size + 16 * 1024 * 1024:
                    raise DownloadError("磁盘空间不足，请更换位置")
                try:
                    with src.open("rb") as read, part.open("wb") as write:
                        while chunk := read.read(1024 * 1024):
                            self.check_cancelled()
                            write.write(chunk)
                    if not verify(r, part, self.cancelled.is_set):
                        raise DownloadError("文件校验失败，请重试")
                    os.replace(part, dest)
                finally:
                    part.unlink(missing_ok=True)
                self.progress(r.id, "已就绪", r.size, r.size)
