# Building & Notarizing WhisperGo on macOS

WhisperGo ships as a `.app` bundle and a drag‑and‑drop `.dmg`. For a good user experience (“download → open → works”), the DMG should be **Developer‑ID signed + notarized**.

## Prerequisites

- macOS with **Xcode Command Line Tools** (`xcrun`, `notarytool`, `stapler`)
  - Install: `xcode-select --install`
- Python + `pyinstaller`
- (For notarization) an Apple Developer Program membership with a **Developer ID Application** certificate installed in your keychain

## Build the `.app`

```bash
pyinstaller build_app.spec --clean
```

Output: `dist/WhisperGo.app`

## Build the `.dmg` (dev / ad‑hoc signed)

```bash
./build_dmg.sh
```

This produces an ad‑hoc signed DMG (no notarization). It’s fine for local testing but Gatekeeper may block it on other machines.

## Build the `.dmg` (release / notarized)

### 1) Store notary credentials (once)

```bash
xcrun notarytool store-credentials "whispergo-notary" \
  --apple-id "you@example.com" \
  --team-id "TEAMID" \
  --password "app-specific-password"
```

### 2) Build + notarize

```bash
export CODESIGN_IDENTITY="Developer ID Application: Your Name (TEAMID)"
export NOTARY_PROFILE="whispergo-notary"

./build_dmg.sh 1.0.0 --notarize
```

Output: `dist/WhisperGo-1.0.0.dmg`

## Notes

- `build_dmg.sh` notarizes both the `.app` (stapled before packaging) and the `.dmg` (Gatekeeper‑friendly).
- Entitlements are read from `macos/entitlements.plist` (override via `ENTITLEMENTS_PATH` if needed).
