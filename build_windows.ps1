<#
.SYNOPSIS
    Build script for PulseScribe on Windows.

.DESCRIPTION
    Builds PulseScribe EXE and optionally creates an installer.
    Two variants available: API-only (fast, small) or Local (with CUDA Whisper).

.PARAMETER Clean
    Remove build artifacts before building.

.PARAMETER Installer
    Create Inno Setup installer after building EXE.

.PARAMETER SkipExe
    Skip EXE build (only create installer from existing build).

.PARAMETER Local
    Include local Whisper with CUDA support. Adds ~4GB, much slower build.
    Without this flag: API-only build (~30MB, fast).

.EXAMPLE
    .\build_windows.ps1 -Clean -Installer
    # API-only build with installer (recommended, ~30MB)

.EXAMPLE
    .\build_windows.ps1 -Clean -Installer -Local
    # Full build with local CUDA Whisper (~4GB, slow)

.EXAMPLE
    .\build_windows.ps1 -Installer -SkipExe
    # Create installer from existing EXE build
#>

param(
    [switch]$Clean,
    [switch]$Installer,
    [switch]$SkipExe,
    [switch]$Local
)

$ErrorActionPreference = "Stop"

# Colors for output (using unique names to avoid shadowing built-in cmdlets)
function Write-Step { param($msg) Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-BuildSuccess { param($msg) Write-Host $msg -ForegroundColor Green }
function Write-BuildWarning { param($msg) Write-Host $msg -ForegroundColor Yellow }
function Write-BuildError { param($msg) Write-Host $msg -ForegroundColor Red }

# Get version from pyproject.toml
function Get-AppVersion {
    if (-not (Test-Path "pyproject.toml")) {
        Write-BuildWarning "  pyproject.toml not found - using default version 1.0.0"
        return "1.0.0"
    }
    $pyproject = Get-Content "pyproject.toml" -Raw
    if ($pyproject -match 'version\s*=\s*"([^"]+)"') {
        return $matches[1]
    }
    Write-BuildWarning "  Version not found in pyproject.toml - using default 1.0.0"
    return "1.0.0"
}

$Version = Get-AppVersion
$BuildVariant = if ($Local) { "Local (CUDA)" } else { "API-only" }
$VersionSuffix = if ($Local) { "-Local" } else { "" }

Write-Host "`nPulseScribe Build Script v$Version" -ForegroundColor Magenta
Write-Host "=================================" -ForegroundColor Magenta
Write-Host "  Build variant: $BuildVariant" -ForegroundColor $(if ($Local) { "Yellow" } else { "Green" })

# Detect and use venv if available
$VenvPython = ".\venv\Scripts\python.exe"
if (Test-Path $VenvPython) {
    $Python = $VenvPython
    Write-Host "  Using venv: $Python" -ForegroundColor Gray
} else {
    $Python = "python"
}

# Check prerequisites
Write-Step "Checking prerequisites..."

# Python
if (-not (Test-Path $Python) -and -not (Get-Command $Python -ErrorAction SilentlyContinue)) {
    Write-BuildError "Python not found. Please install Python 3.10+."
    exit 1
}
Write-BuildSuccess "  Python: $(& $Python --version)"

# PyInstaller
$pyinstallerCheck = & $Python -c "import PyInstaller; print(PyInstaller.__version__)" 2>$null
if (-not $pyinstallerCheck) {
    Write-BuildWarning "  PyInstaller not found. Installing..."
    & $Python -m pip install pyinstaller
    if ($LASTEXITCODE -ne 0) {
        Write-BuildError "  Failed to install PyInstaller!"
        exit 1
    }
    # Verify installation
    $pyinstallerCheck = & $Python -c "import PyInstaller; print(PyInstaller.__version__)" 2>$null
    if (-not $pyinstallerCheck) {
        Write-BuildError "  PyInstaller installation failed!"
        exit 1
    }
}
Write-BuildSuccess "  PyInstaller: $pyinstallerCheck"

# Inno Setup (only if -Installer)
if ($Installer) {
    $iscc = Get-Command iscc -ErrorAction SilentlyContinue
    if (-not $iscc) {
        # Try common install locations
        $isccPaths = @(
            "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
            "${env:ProgramFiles}\Inno Setup 6\ISCC.exe",
            "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
        )
        foreach ($path in $isccPaths) {
            if (Test-Path $path) {
                $iscc = $path
                break
            }
        }
    }
    if (-not $iscc) {
        Write-BuildError "Inno Setup not found. Please install from https://jrsoftware.org/isinfo.php"
        Write-Host "  Or run without -Installer flag to build EXE only."
        exit 1
    }
    Write-BuildSuccess "  Inno Setup: OK"
}

# Clean build artifacts
if ($Clean) {
    Write-Step "Cleaning build artifacts..."
    if (Test-Path "build") { Remove-Item -Recurse -Force "build" }
    if (Test-Path "dist") { Remove-Item -Recurse -Force "dist" }
    Write-BuildSuccess "  Cleaned build/ and dist/"
}

# Build EXE
if (-not $SkipExe) {
    Write-Step "Building PulseScribe.exe..."

    # Set build environment variables
    $env:PULSESCRIBE_VERSION = $Version
    $env:PULSESCRIBE_BUILD_LOCAL = if ($Local) { "1" } else { "0" }

    # Run PyInstaller
    & $Python -m PyInstaller build_windows.spec --clean --noconfirm

    if ($LASTEXITCODE -ne 0) {
        Write-BuildError "PyInstaller build failed!"
        exit 1
    }

    # Verify output
    if (-not (Test-Path "dist\PulseScribe\PulseScribe.exe")) {
        Write-BuildError "Build output not found: dist\PulseScribe\PulseScribe.exe"
        exit 1
    }

    $exeSize = (Get-Item "dist\PulseScribe\PulseScribe.exe").Length / 1MB
    Write-BuildSuccess "  Built: dist\PulseScribe\PulseScribe.exe ($([math]::Round($exeSize, 1)) MB)"
}

# Create installer
if ($Installer) {
    Write-Step "Creating installer..."

    # Verify EXE exists
    if (-not (Test-Path "dist\PulseScribe\PulseScribe.exe")) {
        Write-BuildError "EXE not found. Run without -SkipExe first."
        exit 1
    }

    # Check for icon
    if (Test-Path "assets\icon.ico") {
        Write-BuildSuccess "  Icon: assets\icon.ico"
    } else {
        Write-BuildWarning "  assets\icon.ico not found - using default icon"
    }

    # Run Inno Setup with version and variant parameters
    $isccArgs = @("/DAppVersion=$Version", "/DVersionSuffix=$VersionSuffix", "installer_windows.iss")
    if ($iscc -is [string]) {
        & $iscc @isccArgs
    } else {
        iscc @isccArgs
    }

    if ($LASTEXITCODE -ne 0) {
        Write-BuildError "Inno Setup build failed!"
        exit 1
    }

    $installerPath = "dist\PulseScribe-Setup-$Version$VersionSuffix.exe"
    if (Test-Path $installerPath) {
        $installerSize = (Get-Item $installerPath).Length / 1MB
        Write-BuildSuccess "  Built: $installerPath ($([math]::Round($installerSize, 1)) MB)"
    }
}

# Summary
Write-Host "`n" -NoNewline
Write-Host "Build complete!" -ForegroundColor Green
Write-Host "===============" -ForegroundColor Green

Write-Host "`nOutput files ($BuildVariant):"
if (Test-Path "dist\PulseScribe\PulseScribe.exe") {
    Write-Host "  - dist\PulseScribe\PulseScribe.exe (portable)"
}
$installerPath = "dist\PulseScribe-Setup-$Version$VersionSuffix.exe"
if (Test-Path $installerPath) {
    Write-Host "  - $installerPath (installer)"
}

Write-Host "`nNext steps:"
Write-Host "  - Test: .\dist\PulseScribe\PulseScribe.exe"
if ($Installer) {
    Write-Host "  - Install: .\$installerPath"
}
Write-Host ""
