# macOS packaging

Build on Apple Silicon from the verified `.venv-studio` (Python 3.12.13). This
creates a self-contained `.app` and a drag-to-install DMG. Models, media, local
settings, credentials, the website and development environment are excluded.

```
.venv-studio/bin/python packaging/macos/build.py build
.venv-studio/bin/python packaging/macos/build.py sign
.venv-studio/bin/python packaging/macos/build.py package --notarize
```

Artifacts: `../releases/macos-0.1.0/`. An existing app is never overwritten by the
build step. Signing uses the installed Developer ID Application identity (or
`APPLE_SIGNING_IDENTITY`). Notarization uses `NOTARY_PROFILE`, defaulting to the
your own `visomaster-notary` Keychain profile. No key or password is exported.
The package step without `--notarize` produces a signed local DMG only. Neither
step uploads to a website, publishes source or creates a GitHub release.

The native launcher embeds the bundled Python runtime. Qt frameworks are trimmed
by transitive dependencies and retain canonical framework symlinks. Runtime
libraries are signed inside out with secure timestamps and hardened runtime.
FFmpeg and FFprobe are bundled together with their dependent libraries; no
Homebrew, terminal setup or system Python is needed by the installed app.

This build requires **macOS 26+ on Apple Silicon** because the current local
FFmpeg/Homebrew binaries declare macOS 26 as their minimum. Supporting older
macOS requires rebuilding those tools and their dependencies for that target,
then repeating package tests; lowering Info.plist alone is insufficient.

App data lives in `~/Library/Application Support/VisoMasterStudio`. Model and
output paths remain configurable. Upstream jobs/presets, thumbnails and other
runtime caches are redirected to writable user/session directories. Bytecode
writes inside the signed app are disabled.

Package checks use the bundled interpreter with `-I -B` and
`packaging/macos/check_bundle.py` to run the existing smoke checks against the
bundled source. Always verify a signed app from a relocated path and a read-only
DMG; a successful development run is not sufficient. Verify `codesign --deep
--strict`, notarization acceptance, stapled tickets and Gatekeeper before
claiming the package is notarized.

The app includes upstream GPL attribution and dependency license metadata. A
local corresponding-source archive should accompany distribution. Commercial
model licensing and clean-device/long-video testing remain separate release
work; packaging does not establish those approvals or results.
