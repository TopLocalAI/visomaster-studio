# VisoMaster Studio

An independent desktop application for local face swapping and image/video processing, based on [VisoMaster](https://github.com/visomaster/VisoMaster) and [VisoMaster Fusion](https://github.com/VisoMasterFusion/VisoMaster-Fusion).

**Source release: Studio 0.3.0.** The current interface uses Tauri 2, React and TypeScript with a local Python processing backend. The older Qt workspace is retained for reference. Studio is not affiliated with or endorsed by the upstream maintainers.

- [Build from source — Windows CPU, Windows NVIDIA and macOS](BUILDING.md)
- [Source provenance and release contents](SOURCE.md)
- [GPL-3.0 license](LICENSE)
- [Upstream README, credits and acknowledgements](README.upstream.md)
- [Website](https://visomaster.studio/)

## Get the source

```sh
git clone https://github.com/TopLocalAI/visomaster-studio.git
cd visomaster-studio
git checkout v0.3.0
```

You can also download the source archive from the [0.3.0 release](https://github.com/TopLocalAI/visomaster-studio/releases/tag/v0.3.0). No purchase, product account or API key is needed to obtain or build this source.

## Layout

| Directory | Contents |
| --- | --- |
| `studio-ui/` | Current React interface and Rust/Tauri desktop shell |
| `app/backend/` | Local Python service used by the desktop shell |
| `app/processors/` | Processing code derived from Fusion |
| `app/studio/` | Resource management, shared services and older Qt interface |
| `packaging/` | Backend packaging, platform dependency lists and macOS scripts |
| `studio_tests/`, `tests/` | Automated tests and upstream synthetic fixtures |

## Models and limitations

Model weights are downloaded separately from their upstream sources when needed; URLs and SHA-256 hashes are recorded in `app/studio/catalog.py`. Small upstream reference tables and tokenizer data remain in the source tree. Model licenses are separate from this application's GPL license; check their terms before use.

Windows CPU, Windows NVIDIA and macOS Intel builds remain preview targets: prior CI packaging and smoke checks are not a substitute for testing your hardware. macOS Apple Silicon has been exercised locally. No claim is made that every advanced model, camera or GPU combination has been tested.

Some older smoke/UI scripts refer to synthetic media from the maintainer's development workspace. Those media files are not included here; see `BUILDING.md` for checks that do not require them.

## License and attribution

The desktop application is distributed under GPL-3.0; see `LICENSE`, the retained upstream notices and component licenses. Studio's Rust/JavaScript package metadata specifies GPL-3.0-only. Buying a prebuilt installer pays for packaging and delivery and does not restrict rights granted by the license.

Upstream base: **VisoMaster Fusion v3.12.3**, commit `9f9dd96dafc2c8a13469566bf6ef16ae09106627`. Copyright and contributor credits are preserved in the source and `README.upstream.md`. This repository is a source snapshot, not the private development history. The website, payment systems, signing credentials and customer data are not part of this repository.

Only process media you are authorized to use, with the consent of the people depicted.
