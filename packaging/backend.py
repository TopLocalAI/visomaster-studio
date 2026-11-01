"""Build the bundled Python backend for one platform variant.

Usage: python packaging/backend.py <variant> [--smoke]

Variants: macos-arm64, macos-x64, windows-cpu, windows-cuda. Run on the matching
OS/architecture (CI runners or a local machine). The result goes to
studio-ui/src-tauri/generated/backend:

  python/   standalone CPython 3.12 (python-build-standalone) with the variant's
            pinned requirements from packaging/requirements/
  app/      backend source (GPL: corresponding source ships with the binary)
  bin/      static FFmpeg + FFprobe (ffmpeg-static b6.1.1)
  notices/  FFmpeg build licence and readme

No models, settings or media are included. --smoke starts the bundled backend
afterwards and checks imports, providers, the parameter schema and FFmpeg.
"""
import argparse
import gzip
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GEN = ROOT / "studio-ui/src-tauri/generated/backend"
CACHE = ROOT / "build/packaging-cache"
PBS = "20261009"
PY = "3.12.15"
FFMPEG = "b6.1.1"
VARIANTS = {
    "macos-arm64": ("darwin", "aarch64-apple-darwin", "darwin-arm64"),
    "macos-x64": ("darwin", "x86_64-apple-darwin", "darwin-x64"),
    "windows-cpu": ("win32", "x86_64-pc-windows-msvc", "win32-x64"),
    "windows-cuda": ("win32", "x86_64-pc-windows-msvc", "win32-x64"),
}
LATE = {"pyqtdarktheme"}
# Qt modules imported by Fusion's processing code; no windows are created.
QT_KEEP = {"QtCore", "QtGui", "QtWidgets", "QtNetwork", "QtSvg", "QtSvgWidgets", "QtMultimedia",
           "QtMultimediaWidgets", "QtOpenGL", "QtOpenGLWidgets", "QtXml"}


def run(args, **kw):
    print("+", " ".join(str(a) for a in args), flush=True)
    return subprocess.run([str(a) for a in args], check=True, **kw)


def remove(p: Path):
    if p.is_symlink() or p.is_file():
        p.unlink()
    elif p.is_dir():
        shutil.rmtree(p)


def fetch(url: str, name: str) -> Path:
    CACHE.mkdir(parents=True, exist_ok=True)
    dest = CACHE / name
    if not dest.exists():
        print("download", url, flush=True)
        tmp = dest.with_suffix(dest.suffix + ".part")
        with urllib.request.urlopen(url) as r, tmp.open("wb") as f:
            shutil.copyfileobj(r, f)
        tmp.replace(dest)
    return dest


def site_packages(python: Path, windows: bool) -> Path:
    return python / "Lib/site-packages" if windows else python / "lib/python3.12/site-packages"


def interpreter(python: Path, windows: bool) -> Path:
    return python / "python.exe" if windows else python / "bin/python3"


def install_python(variant: str) -> Path:
    _, triple, _ = VARIANTS[variant]
    windows = variant.startswith("windows")
    archive = fetch(f"https://github.com/astral-sh/python-build-standalone/releases/download/{PBS}/"
                    f"cpython-{PY}+{PBS}-{triple}-install_only.tar.gz", f"cpython-{PY}-{triple}.tar.gz")
    with tarfile.open(archive) as tar:
        tar.extractall(GEN, filter="tar")  # -> GEN/python
    python = GEN / "python"
    exe = interpreter(python, windows)
    lines = (ROOT / f"packaging/requirements/{variant}.txt").read_text().splitlines()
    # pyqtdarktheme 2.1.0 declares Python <3.12 but is pure Python and works on 3.12
    # (Fusion installs it with uv the same way); install it without that check.
    late = [l for l in lines if l.split("==")[0].strip().lower() in LATE]
    req = GEN.parent / f"requirements-{variant}.txt"
    req.write_text("\n".join(l for l in lines if l not in late) + "\n")
    pip = [exe, "-m", "pip", "install", "--no-cache-dir", "--disable-pip-version-check", "--no-warn-script-location"]
    env = {**os.environ, "PIP_NO_INPUT": "1"}
    run([*pip, "-r", req], env=env)
    if late:
        run([*pip, "--no-deps", "--ignore-requires-python", *late], env=env)
    req.unlink()
    return python


def trim(python: Path, variant: str):
    windows = variant.startswith("windows")
    sp = site_packages(python, windows)
    stdlib = python / "Lib" if windows else python / "lib/python3.12"
    for name in ["pip", "setuptools", "wheel", "_distutils_hack", "pytest", "_pytest", "pluggy", "iniconfig"]:
        for p in [sp / name, sp / (name + ".py"), *sp.glob(name + "-*.dist-info")]:
            remove(p)
    for p in list(sp.glob("distutils-precedence.pth")) + list(sp.rglob("direct_url.json")) + list(sp.rglob("RECORD")):
        remove(p)
    for base in [stdlib, sp]:
        for p in list(base.rglob("tests")) + list(base.rglob("__pycache__")):
            if p.is_dir():
                remove(p)
    for n in ["test", "idlelib", "tkinter", "turtledemo", "ensurepip"]:
        remove(stdlib / n)
    # Headers, import libraries and debug symbols are not used at run time.
    for pkg in ["torch", "tensorflow", "torchvision", "torchaudio"]:
        for n in ["include", "share/cmake"]:
            remove(sp / pkg / n)
    for pattern in ["*.lib", "*.pdb", "*.a"]:
        for p in sp.rglob(pattern):
            if p.is_file():
                p.unlink()
    if windows:
        for n in ["include", "libs", "tcl", "Scripts"]:
            remove(python / n)
        for p in python.glob("DLLs/_tkinter*"):
            remove(p)
        for p in python.glob("DLLs/t*86t.dll"):
            remove(p)
    else:
        for p in (stdlib / "lib-dynload").glob("_tkinter*"):
            remove(p)
        for p in list((python / "lib").iterdir()):
            if any(s in p.name for s in ["tcl", "tk8", "tk9", "itcl", "thread", "pkgconfig"]):
                remove(p)
        for n in ["include", "share"]:
            remove(python / n)
        for p in (python / "bin").iterdir():
            if not p.name.startswith("python3") or p.name.endswith("-config"):
                remove(p)
    trim_qt(sp / "PySide6", windows)


def trim_qt(pyside: Path, windows: bool):
    if not pyside.is_dir():
        return
    ext = ".pyd" if windows else ".so"
    for p in pyside.glob(f"Qt*{ext}"):
        if p.name.split(".")[0] not in QT_KEEP:
            remove(p)
    qt = pyside if windows else pyside / "Qt"
    for n in ["qml", "libexec", "metatypes", "translations", "resources", "include", "typesystems", "glue",
              "scripts", "examples"]:
        remove(qt / n)
        remove(pyside / n)
    plugins = qt / "plugins"
    if plugins.is_dir():
        for p in plugins.iterdir():
            if p.name not in {"platforms", "imageformats", "multimedia"}:
                remove(p)
    if windows:
        for p in pyside.glob("*.exe"):
            remove(p)
        # Qt libraries that none of the kept modules link against (large web/QML/3D stacks).
        heavy = re.compile(r"Qt6(WebEngine|WebView|Quick|Qml|3D|Pdf|Designer|Charts|DataVisualization|Graphs|"
                           r"Location|Positioning|Bluetooth|Nfc|Sensors|SerialPort|SerialBus|RemoteObjects|Scxml|"
                           r"StateMachine|TextToSpeech|VirtualKeyboard|ShaderTools|Spatial|HttpServer|WebSockets|"
                           r"WebChannel|Test|Help|UiTools|Sql|Concurrent|Designer)")
        for p in pyside.glob("*.dll"):
            if heavy.match(p.name):
                remove(p)
        return
    # macOS: keep only the Qt frameworks reachable from the kept modules (otool).
    for p in list((plugins / "platforms").iterdir()) if (plugins / "platforms").is_dir() else []:
        if p.name not in {"libqoffscreen.dylib", "libqminimal.dylib"}:
            remove(p)
    needed, visited = set(), set()
    pending = list(pyside.glob("*.so")) + [p for p in plugins.rglob("*.dylib")]
    while pending:
        p = pending.pop()
        if p in visited:
            continue
        visited.add(p)
        out = subprocess.run(["otool", "-L", str(p)], capture_output=True, text=True).stdout
        for m in re.finditer(r"(Qt[A-Za-z0-9]+)\.framework/", out):
            if m[1] not in needed:
                needed.add(m[1])
                fw = qt / "lib" / f"{m[1]}.framework"
                binary = next(fw.glob("Versions/*/" + m[1]), fw / m[1])
                if binary.exists():
                    pending.append(binary)
    for p in (qt / "lib").glob("*.framework"):
        if p.stem not in needed:
            remove(p)


def add_source():
    code = GEN / "app"
    code.mkdir()
    shutil.copytree(ROOT / "app", code / "app", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for n in ["studio_backend.py", "LICENSE", "STUDIO.md", "version.json"]:
        if (ROOT / n).exists():
            shutil.copy2(ROOT / n, code / n)
    shutil.copytree(ROOT / "packaging/requirements", code / "requirements")


def add_ffmpeg(variant: str):
    _, _, target = VARIANTS[variant]
    bins, notices = GEN / "bin", GEN / "notices"
    bins.mkdir()
    notices.mkdir()
    suffix = ".exe" if target.startswith("win32") else ""
    base = f"https://github.com/eugeneware/ffmpeg-static/releases/download/{FFMPEG}/"
    for tool in ["ffmpeg", "ffprobe"]:
        packed = fetch(base + f"{tool}-{target}.gz", f"{tool}-{FFMPEG}-{target}.gz")
        dest = bins / (tool + suffix)
        with gzip.open(packed) as src, dest.open("wb") as out:
            shutil.copyfileobj(src, out)
        dest.chmod(0o755)
    for n in ["LICENSE", "README"]:
        shutil.copy2(fetch(base + f"{target}.{n}", f"ffmpeg-{FFMPEG}-{target}.{n}"), notices / f"ffmpeg-{n}.txt")


def notices(variant: str):
    (GEN / "ThirdPartyNotices.txt").write_text(
        "VisoMaster Studio backend\n"
        "Based on VisoMaster and VisoMaster Fusion v3.12.3 (GPL-3.0); see app/LICENSE.\n"
        f"Python {PY} from python-build-standalone {PBS}; Python package licences are under python's site-packages.\n"
        f"FFmpeg and FFprobe from ffmpeg-static {FFMPEG} (GPL build); see notices/.\n"
        "Models are not bundled.\n", encoding="utf-8")
    (GEN / "variant.json").write_text(json.dumps({"variant": variant, "python": PY, "pbs": PBS, "ffmpeg": FFMPEG}) + "\n")


def smoke(variant: str) -> dict:
    windows = variant.startswith("windows")
    exe = interpreter(GEN / "python", windows)
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
    env["PATH"] = str(GEN / "bin") + os.pathsep + env.get("PATH", "")
    code = (
        "import json, sys, tempfile, pathlib, shutil\n"
        "from app.backend.service import Workspace\n"
        "ws = Workspace(lambda e, d: None, root=pathlib.Path(tempfile.mkdtemp()))\n"
        "info = ws.hello()\n"
        "schema = ws.schema()\n"
        "import torch, onnxruntime, cv2\n"
        "info.update(torch=torch.__version__, onnxruntime=onnxruntime.__version__, opencv=cv2.__version__,\n"
        "            ort_providers=onnxruntime.get_available_providers(),\n"
        "            fields=sum(len(s['fields']) for s in schema['sections']), ffmpeg_path=shutil.which('ffmpeg'))\n"
        "print('SMOKE ' + json.dumps(info))\n"
    )
    with tempfile.TemporaryDirectory() as cwd:
        out = subprocess.run([str(exe), "-E", "-s", "-B", "-c", f"import os, sys; sys.path.insert(0, {str(GEN / 'app')!r}); "
                              f"os.chdir({cwd!r}); exec({code!r})"],
                             capture_output=True, text=True, env=env, timeout=600)
    line = next((l for l in out.stdout.splitlines() if l.startswith("SMOKE ")), None)
    if out.returncode or not line:
        print(out.stdout[-4000:], out.stderr[-4000:], sep="\n")
        raise SystemExit("smoke test failed")
    info = json.loads(line[6:])
    assert info["ffmpeg"] and info["fields"] > 400, info
    return info


def build(variant: str, smoke_test: bool = False) -> dict:
    system = VARIANTS[variant][0]
    assert sys.platform == system, f"{variant} must be built on {system}"
    if GEN.exists():
        shutil.rmtree(GEN)
    GEN.mkdir(parents=True)
    python = install_python(variant)
    trim(python, variant)
    add_source()
    add_ffmpeg(variant)
    notices(variant)
    files = [p for p in GEN.rglob("*") if p.is_file() and not p.is_symlink()]
    longest = max((len(str(p.relative_to(GEN))) for p in files), default=0)
    result = {"backend": str(GEN), "variant": variant, "files": len(files),
              "bytes": sum(p.stat().st_size for p in files), "longest_relative_path": longest}
    if smoke_test:
        result["smoke"] = smoke(variant)
    print(json.dumps(result))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("variant", choices=sorted(VARIANTS))
    parser.add_argument("--smoke", action="store_true", help="check the bundled backend after building")
    args = parser.parse_args()
    build(args.variant, args.smoke)
