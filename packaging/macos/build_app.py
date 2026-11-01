"""Build the Tauri desktop app (studio-ui) with its bundled Python backend.

Steps (on the Mac whose architecture is being built; VISOMASTER_ARCH=arm64|x64):
  backend   packaging/backend.py macos-<arch>: standalone Python with pinned
            requirements, backend source and static FFmpeg into
            studio-ui/src-tauri/generated/backend (no models, settings or media)
  app       `tauri build --bundles app`, then copy the result to ../releases/<version>/
  import    take an unsigned .app tar.gz from the Package workflow instead of app
  sign      sign every Mach-O inside out with hardened runtime, then the app
  dmg       signed drag-to-install DMG + manifest (no upload)
  notarize  submit the DMG to Apple, staple and validate (explicit, outward-facing)

Signing reuses the helpers of build.py (Qt 0.2.1). Output: ../releases/macos-<version>-<arch>/.
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build as qt  # noqa: E402  (shared helpers: run, capture, macho, dependencies, copy, remove, identity)

ROOT = Path(__file__).resolve().parents[2]
UI = ROOT / "studio-ui"
GEN = UI / "src-tauri/generated/backend"
CONF = json.loads((UI / "src-tauri/tauri.conf.json").read_text())
VERSION = CONF["version"]
MIN_MACOS = CONF["bundle"]["macOS"]["minimumSystemVersion"]
ARCH = os.environ.get("VISOMASTER_ARCH") or {"arm64": "arm64", "x86_64": "x64"}[os.uname().machine]
LABEL = {"arm64": "Apple Silicon arm64", "x64": "Intel x86_64"}[ARCH]
RELEASE = Path(os.environ.get("VISOMASTER_RELEASES", ROOT.parent / "releases")) / f"macos-{VERSION}-{ARCH}"
APP = RELEASE / "VisoMaster Studio.app"


def backend():
    sys.path.insert(0, str(ROOT / "packaging"))
    import backend as bundle

    bundle.build(f"macos-{ARCH}", smoke_test=True)


def import_app(archive):
    """Take an unsigned app built by the Package workflow (tar.gz) for local signing."""
    assert not APP.exists(), "existing artifact preserved; move it or bump the version"
    RELEASE.mkdir(parents=True, exist_ok=True)
    qt.run(["tar", "-xzf", archive, "-C", RELEASE])
    assert APP.is_dir(), f"{APP.name} not found in {archive}"
    qt.run(["xattr", "-cr", APP])
    print(json.dumps({"app": str(APP)}))


def app():
    assert GEN.is_dir(), "run the backend step first"
    assert not APP.exists(), "existing artifact preserved; move it or bump the version"
    env = dict(os.environ)
    env.pop("APPLE_SIGNING_IDENTITY", None)  # signed below, inside out
    qt.run(["pnpm", "tauri", "build", "--bundles", "app"], cwd=UI, env=env)
    built = UI / "src-tauri/target/release/bundle/macos/VisoMaster Studio.app"
    RELEASE.mkdir(parents=True, exist_ok=True)
    qt.run(["ditto", built, APP])
    # ditto keeps framework symlinks intact (the Tauri resource copier may not).
    qt.run(["ditto", GEN, APP / "Contents/Resources/backend"])
    # GPL: the desktop UI source ships too (backend source is under backend/app).
    ui_src = APP / "Contents/Resources/source/studio-ui"
    for rel in ["src", "src-tauri/src", "src-tauri/capabilities", "src-tauri/Cargo.toml", "src-tauri/Cargo.lock",
                "src-tauri/build.rs", "src-tauri/tauri.conf.json", "src-tauri/Info.plist", "package.json",
                "pnpm-lock.yaml", "index.html", "vite.config.ts", "tsconfig.json"]:
        qt.copy(UI / rel, ui_src / rel)
    qt.copy(ROOT / "LICENSE", APP / "Contents/Resources/source/LICENSE")
    print(json.dumps({"app": str(APP)}))


def sign():
    who = qt.identity()
    ent = ROOT / "packaging/macos/entitlements.plist"

    def one(p, entitlements=False):
        args = ["codesign", "--force", "--timestamp", "--options", "runtime", "--sign", who]
        if entitlements:
            args += ["--entitlements", str(ent)]
        result = subprocess.run([*args, str(p)], capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(f"{p}: {result.stderr}")

    files = sorted([p for p in APP.rglob("*") if qt.macho(p) and not p.is_symlink()], key=lambda p: len(p.parts), reverse=True)
    for i, p in enumerate(files):
        one(p, p.name.startswith("python3") or p.parent.name == "MacOS")
        if i % 50 == 0:
            print(f"signed {i + 1}/{len(files)}", flush=True)
    for p in sorted([p for p in APP.rglob("*") if p.is_dir() and not p.is_symlink() and p.suffix in {".framework", ".app"}],
                    key=lambda p: len(p.parts), reverse=True):
        if p != APP:
            one(p)
    one(APP, True)
    qt.run(["codesign", "--verify", "--deep", "--strict", APP])
    print(json.dumps({"signed": str(APP), "identity": who.split("(")[0].strip()}))


def dmg():
    out = RELEASE / f"VisoMaster-Studio-{VERSION}-macOS-{ARCH}.dmg"
    stage = RELEASE / "dmg-stage"
    stage.mkdir(exist_ok=False)
    qt.run(["ditto", APP, stage / APP.name])
    (stage / "Applications").symlink_to("/Applications")
    qt.run(["hdiutil", "create", "-volname", "VisoMaster Studio", "-srcfolder", stage, "-format", "UDZO", out])
    shutil.rmtree(stage)
    qt.run(["codesign", "--force", "--timestamp", "--sign", qt.identity(), out])
    digest = hashlib.file_digest(out.open("rb"), "sha256").hexdigest()
    manifest = {"version": VERSION, "file": out.name, "bytes": out.stat().st_size, "sha256": digest,
                "signed": True, "notarized": False, "platform": f"macOS {MIN_MACOS}+, {LABEL}", "models_bundled": False}
    (RELEASE / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest))


def notarize():
    out = RELEASE / f"VisoMaster-Studio-{VERSION}-macOS-{ARCH}.dmg"
    profile = os.environ.get("NOTARY_PROFILE", "visomaster-notary")
    result = qt.run(["xcrun", "notarytool", "submit", out, "--keychain-profile", profile, "--wait", "--output-format", "json"],
                    capture_output=True, text=True)
    (RELEASE / "notarization.json").write_text(result.stdout)
    if json.loads(result.stdout).get("status") != "Accepted":
        raise RuntimeError("notarization failed; see notarization.json")
    for p in (APP, out):
        qt.run(["xcrun", "stapler", "staple", p])
        qt.run(["xcrun", "stapler", "validate", p])
    manifest = json.loads((RELEASE / "manifest.json").read_text())
    manifest.update(notarized=True, sha256=hashlib.file_digest(out.open("rb"), "sha256").hexdigest(), bytes=out.stat().st_size)
    (RELEASE / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("step", choices=["backend", "app", "import", "sign", "dmg", "notarize"])
    parser.add_argument("archive", nargs="?", help="import: unsigned app .tar.gz from CI")
    args = parser.parse_args()
    if args.step == "import":
        import_app(args.archive)
    else:
        {"backend": backend, "app": app, "sign": sign, "dmg": dmg, "notarize": notarize}[args.step]()
