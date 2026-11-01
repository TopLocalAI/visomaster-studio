"""Pinned resources. No imports from the inference runtime at UI startup."""
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
import hashlib
import re


@dataclass(frozen=True)
class Resource:
    id: str
    name: str
    filename: str
    size: int
    sha256: str
    urls: tuple[str, ...]

    def __post_init__(self):
        p = Path(self.filename)
        if p.is_absolute() or not p.parts or any(part in (".", "..") for part in self.filename.split("/")) or self.filename in ("", ".", "..") or "\\" in self.filename:
            raise ValueError("Invalid resource path")
        if self.size <= 0 or not re.fullmatch(r"[a-f0-9]{64}", self.sha256):
            raise ValueError("Invalid resource integrity data")
        if not self.urls or any(urlparse(u).scheme != "https" for u in self.urls):
            raise ValueError("Resources require HTTPS")

    def path(self, root: Path) -> Path:
        candidate = root / self.filename
        if any(p.is_symlink() for p in (candidate, *candidate.parents) if p != root and root in p.parents) or not candidate.resolve().is_relative_to(root.resolve()):
            raise ValueError("Resource path escapes model directory")
        return candidate


def verify(resource: Resource, path: Path, cancelled=lambda: False) -> bool:
    if not path.is_file() or path.stat().st_size != resource.size:
        return False
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            if cancelled():
                raise InterruptedError("cancelled")
            digest.update(chunk)
    return digest.hexdigest() == resource.sha256


# Full upstream identity and distribution review are recorded in STUDIO.md.
# These are the three resources for Studio's deliberately constrained base mode.
BASIC_RESOURCES = (
    Resource('Inswapper128', '基础换脸', 'inswapper_128.fp16.onnx', 277680638,
             '6d51a9278a1f650cffefc18ba53f38bf2769bf4bbff89267822cf72945f8a38b',
             ('https://github.com/visomaster/visomaster-assets/releases/download/v0.1.0/inswapper_128.fp16.onnx',)),
    Resource('RetinaFace', '人脸检测', 'det_10g.onnx', 16923827,
             '5838f7fe053675b1c7a08b633df49e7af5495cee0493c7dcf6697200b85b5b91',
             ('https://github.com/visomaster/visomaster-assets/releases/download/v0.1.0/det_10g.onnx',)),
    Resource('Inswapper128ArcFace', '人脸识别', 'w600k_r50.onnx', 174383860,
             '4c06341c33c2ca1f86781dab0e829f88ad5b64be9fba56e56bc9ebdefc619e43',
             ('https://github.com/visomaster/visomaster-assets/releases/download/v0.1.0/w600k_r50.onnx',)),
)
