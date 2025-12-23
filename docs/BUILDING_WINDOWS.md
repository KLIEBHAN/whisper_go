# Building PulseScribe on Windows

PulseScribe ships as a standalone `.exe` (onedir mode). For distribution, the EXE can optionally be code-signed.

## Prerequisites

- **Python 3.10+** with pip
- **PyInstaller** (`pip install pyinstaller`)
- **PySide6** (optional, recommended for GPU-accelerated overlay)

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Optional: GPU-accelerated overlay (recommended)
pip install PySide6

# Build the EXE
pyinstaller build_windows.spec --clean

# Output: dist/PulseScribe/PulseScribe.exe
```

## Build Output

The build produces a **onedir** bundle:

```
dist/
└── PulseScribe/
    ├── PulseScribe.exe      # Main executable
    ├── *.dll                # Python + dependency DLLs
    └── ...                  # Supporting files
```

## Build Options

### Environment Variables

| Variable | Description |
|----------|-------------|
| `PULSESCRIBE_VERSION` or `VERSION` | Override version number (default: reads from `pyproject.toml`) |

### Build Variants

| Variant | Command | Overlay |
|---------|---------|---------|
| **Full** (recommended) | `pip install PySide6 && pyinstaller build_windows.spec` | GPU-accelerated (PySide6) |
| **Minimal** | `pyinstaller build_windows.spec` | CPU-only (Tkinter) |

> **Note:** Without PySide6, the overlay falls back to Tkinter automatically. PySide6 provides smoother animations.

## Included Dependencies

The spec file bundles:

### Core
- `sounddevice`, `soundfile`, `numpy` (audio)
- `deepgram-sdk`, `groq`, `openai` (transcription)
- `python-dotenv` (configuration)

### Windows-specific
- `pystray`, `Pillow` (system tray icon)
- `pynput` (global hotkeys + Ctrl+V simulation)
- `pywin32`, `psutil` (app detection)
- `pyperclip` (clipboard)

### UI/Overlay
- `PySide6` (GPU-accelerated overlay, optional)
- `tkinter` (fallback, built-in)

## Excluded Modules

The spec excludes unnecessary modules to reduce size:

- macOS frameworks (`objc`, `AppKit`, `Quartz`, etc.)
- Unused GUI frameworks (`PyQt5`, `PyQt6`, `wx`)
- Data science (`matplotlib`, `pandas`, `sklearn`)
- Testing (`pytest`, `unittest`)

## Custom Icon

Place an icon at `assets/icon.ico` and it will be automatically included:

```
pulsescribe/
└── assets/
    └── icon.ico    # Windows icon (256x256 recommended)
```

## Autostart Setup

To run PulseScribe on Windows startup:

1. Press `Win+R`, type `shell:startup`
2. Create a shortcut to `dist/PulseScribe/PulseScribe.exe` in the opened folder

Or use the included batch file:

```bash
# Create shortcut to start_daemon.bat in the startup folder
```

## Code Signing (Optional)

For distribution without SmartScreen warnings:

```powershell
# Sign with a code signing certificate
signtool sign /f certificate.pfx /p password /t http://timestamp.digicert.com dist\PulseScribe\PulseScribe.exe
```

> **Note:** Without signing, Windows SmartScreen may warn users on first launch. Users can click "More info" → "Run anyway".

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `ModuleNotFoundError: No module named 'pystray'` | `pip install pystray pillow` |
| `ModuleNotFoundError: No module named 'win32gui'` | `pip install pywin32` |
| Overlay not showing | Check `PULSESCRIBE_OVERLAY=true` in `.env` |
| Hotkeys not working | Run as Administrator (some apps require elevated privileges) |
| Antivirus blocks EXE | Add exception or code-sign the executable |

## Configuration

The EXE uses the same configuration as the Python version:

- `~/.pulsescribe/.env` (recommended)
- Or project root `.env` (for development)

See `README.md` for all configuration options.

## Development Build

For faster iteration during development:

```bash
# Run directly without building
python pulsescribe_windows.py --debug

# Quick test build (no UPX compression)
pyinstaller build_windows.spec --clean --noconfirm
```
