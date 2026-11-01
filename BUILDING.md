# Building VisoMaster Studio 0.3.0

Build on the target operating system and architecture. The source includes the interface, processing backend, dependency lists and packaging scripts. Downloading dependencies and models requires internet access; no Studio service credential or signing key is required for an unsigned build.

## Windows x64 CPU (recommended starting point)

Prerequisites:

- Windows x64 with Microsoft Edge WebView2 Runtime.
- Git, Python 3.12, Node.js 22 and pnpm 10, available on PATH.
- Rust stable using the MSVC toolchain.
- Visual Studio 2022 Build Tools with **Desktop development with C++** and a Windows SDK.
- For the MSI installer, enable the Windows **VBSCRIPT** optional feature if the WiX build requests it.
- A short writable checkout path (for example `C:\src\visomaster-studio`) and ample disk space for Python, Rust, dependencies and build outputs. CPU builds do not require CUDA or an NVIDIA GPU.

In PowerShell, from the repository root:

```powershell
python packaging/backend.py windows-cpu --smoke
if ($LASTEXITCODE -ne 0) { throw "Backend build failed" }
Set-Location studio-ui
pnpm install --frozen-lockfile
if ($LASTEXITCODE -ne 0) { throw "Dependency install failed" }
pnpm tauri build --bundles msi
if ($LASTEXITCODE -ne 0) { throw "Desktop build failed" }
```

The backend script downloads standalone CPython 3.12, installs the versions in `packaging/requirements/windows-cpu.txt`, copies application code and adds FFmpeg/FFprobe. `--smoke` checks backend startup/imports, parameter schema, execution providers and FFmpeg without downloading model weights.

The MSI is written to `studio-ui/src-tauri/target/release/bundle/msi/`. Tauri automatically merges `tauri.windows.conf.json`, which includes `generated/backend/` as application resources. The installer is unsigned; it does not carry the maintainer's signing identity. Models are obtained through the application's model setup after installation.

`packaging/backend.py` recreates `studio-ui/src-tauri/generated/backend/` on each run. Keep personal data out of that generated build directory. If a pinned upstream dependency/download becomes unavailable, keep the failure log and report it; do not silently replace versions and call the result an identical build.

## Windows NVIDIA CUDA (preview)

Use the same prerequisites, with an NVIDIA driver compatible with the CUDA libraries in the pinned requirements:

```powershell
python packaging/backend.py windows-cuda --smoke
if ($LASTEXITCODE -ne 0) { throw "Backend build failed" }
Set-Location studio-ui
pnpm install --frozen-lockfile
if ($LASTEXITCODE -ne 0) { throw "Dependency install failed" }
pnpm tauri build --no-bundle
if ($LASTEXITCODE -ne 0) { throw "Desktop build failed" }
```

For a portable folder, place `target/release/visomaster-studio.exe` beside a `backend/` directory copied from `src-tauri/generated/backend/` (both paths relative to `studio-ui/`), and include `LICENSE`. CUDA runtime files are large, so the packaging workflow uses split 7z archives instead of MSI. Optional upstream binary-only plugins are not shipped in this source snapshot; their absence does not affect the standard Windows CPU build. Specialized optional acceleration paths may require separate upstream components.

## macOS (Apple Silicon or Intel)

Use macOS 14+ on the matching architecture, Xcode Command Line Tools, Python 3.12, Node.js 22, pnpm 10 and Rust stable. From the repository root:

```sh
python3 packaging/backend.py macos-arm64 --smoke
cd studio-ui
pnpm install --frozen-lockfile
cd ..
python3 packaging/macos/build_app.py app
```

For Intel, use `macos-x64` in the first command and build on an Intel Mac. The assembled application is written outside the checkout under `../releases/macos-0.3.0-<arch>/VisoMaster Studio.app`. The scripts preserve an existing output rather than overwriting it. Local unsigned/ad-hoc builds do not have the notarization status of distributed signed installers.

Signing and notarization are optional distribution steps, not source-build prerequisites. To use them, supply your own Apple Developer signing identity through `APPLE_SIGNING_IDENTITY` and your own Keychain profile through `NOTARY_PROFILE`. No maintainer certificate or private key is supplied. `packaging/macos/build.py` and its original README describe the older Qt build; use `build_app.py` for 0.3.0.

## Automated checks

With the full Python dependencies installed in a development environment (Python 3.12) plus `pytest`:

```sh
python -m pytest -q studio_tests/test_backend_schema.py studio_tests/test_backend_server.py studio_tests/test_backend_export.py studio_tests/test_resources.py
cd studio-ui
pnpm install --frozen-lockfile
pnpm build
```

The first checks exercise parameter export, local backend authentication/lifecycle, export helpers and resource download validation. They do not require private media or model downloads. Real inference tests additionally need downloaded models and your own authorized media; some historical `smoke_*.py` scripts and `tests/ui-flow.mjs` still reference local development fixtures outside this repository.

The manual GitHub Actions packaging recipe is retained at `.github/workflows/package.yml`. It runs only when explicitly dispatched and creates draft installer releases using GitHub's job token. Cloning or pushing this source does not automatically build or publish installers.

## Reproducibility scope

The 0.3.0 runtime source matches the release-era desktop checkout; see `SOURCE.md` for its origin and publication-only differences. Dependency lists and lockfiles are included. Compilers, SDKs, signing timestamps and some build-tool versions are not fully pinned, so byte-for-byte reproduction of signed installers is not promised. A successful source check on macOS does not establish Windows hardware validation.
