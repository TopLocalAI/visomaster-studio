# Source provenance and publication notes

Published 2026-11-01 by TopLocalAI as VisoMaster Studio 0.3.0.

## Origins

- Original project: https://github.com/visomaster/VisoMaster
- Base: https://github.com/VisoMasterFusion/VisoMaster-Fusion
- Base version: v3.12.3
- Base commit: `9f9dd96dafc2c8a13469566bf6ef16ae09106627`
- Studio release-era source commit: `ac07ceca9cfe6cd0082ac382ef12dbee2ed8de5d`
- Successful Windows installer CI run used `1b6fce45eb218385a1aef0387002e18cb9b6b318`; the next commit only normalizes checksum-file line endings. Application runtime source is unchanged between that build and this snapshot.

The public repository starts with a fresh source snapshot. Private repository history, website code, local environments, signing material, runtime data and installer binaries are excluded. The public tag `v0.3.0` identifies this source publication, not a new binary build.

## Studio changes from Fusion

Studio adds a Tauri/React desktop shell, a local authenticated Python backend, platform packaging, on-demand resource management and download/hash validation. It includes processing compatibility fixes and the earlier Qt Studio workspace. Existing upstream author/copyright notices and component licenses are retained. `README.upstream.md` preserves the upstream project's description and credits; its installation/update instructions concern Fusion rather than this Studio build.

## Publication-only changes

- Added this file, a Studio README, current build instructions and defensive ignore rules.
- Kept the upstream README as `README.upstream.md` and marked legacy Studio notes as historical.
- Removed the upstream funding configuration and automatic version-bump workflow; retained the manually dispatched package recipe.
- Changed the example Apple Keychain profile name to `visomaster-notary`; use your own profile if signing.
- Omitted these model weights / precompiled upstream binaries from the source tree:

- `model_assets/grid_sample_3d_plugin.dll`
- `model_assets/libgrid_sample_3d_plugin.so`
- `model_assets/mouth_action_detector/model.pb`
- `model_assets/vgg_combo_relu3_3_relu3_1.onnx`
- `tools/_adain_build/adain_fp16_ext.pyd`

The two omitted model weights are already listed with download URLs and SHA-256 checksums in `app/studio/catalog.py`. Optional compiled plugins are not needed for the standard CPU build. Small upstream reference arrays, tokenizer data and synthetic test fixtures remain. These packaging exclusions do not remove application source code.

Model licenses and third-party runtime licenses remain separate from the desktop GPL license. No customer media or credentials are intentionally included; automated secret scanning and a targeted file/content review were performed before publication.
