#!/bin/bash
# =============================================================================
# WhisperGo App Builder
# =============================================================================
# Erstellt die WhisperGo.app mit PyInstaller.
#
# Usage:
#   ./build_app.sh              # Standard-Build
#   ./build_app.sh --clean      # Cache löschen + Build
#   ./build_app.sh --dmg        # Build + DMG erstellen
#   ./build_app.sh --open       # Build + App starten
# =============================================================================

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

CLEAN="false"
BUILD_DMG="false"
OPEN_APP="false"

usage() {
    cat <<'EOF'
WhisperGo App Builder

Usage:
  ./build_app.sh [options]

Options:
  --clean       Cache löschen vor dem Build
  --dmg         Nach dem Build auch DMG erstellen
  --open        App nach dem Build starten
  -h, --help    Hilfe anzeigen

Beispiele:
  ./build_app.sh                    # Standard-Build
  ./build_app.sh --clean --dmg      # Frischer Build + DMG
  ./build_app.sh --open             # Build + starten
EOF
}

die() {
    echo -e "${RED}❌ Fehler: $*${NC}" >&2
    exit 1
}

# ---- Args ----
while [ "${1:-}" != "" ]; do
    case "$1" in
        -h|--help)
            usage
            exit 0
            ;;
        --clean)
            CLEAN="true"
            shift
            ;;
        --dmg)
            BUILD_DMG="true"
            shift
            ;;
        --open)
            OPEN_APP="true"
            shift
            ;;
        *)
            usage
            die "Unbekannte Option: $1"
            ;;
    esac
done

echo -e "${GREEN}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  WhisperGo App Builder${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════════════════════${NC}"
echo ""

# Prüfe PyInstaller
if ! command -v pyinstaller >/dev/null 2>&1; then
    die "PyInstaller nicht gefunden. Installiere mit: pip install pyinstaller"
fi

# Prüfe build_app.spec
if [ ! -f "build_app.spec" ]; then
    die "build_app.spec nicht gefunden. Bist du im richtigen Verzeichnis?"
fi

# Clean wenn gewünscht
if [ "$CLEAN" = "true" ]; then
    echo -e "${YELLOW}🧹 Lösche Build-Cache...${NC}"
    rm -rf build/ dist/WhisperGo.app dist/whisper_go/
    rm -rf ~/Library/Application\ Support/pyinstaller/
    echo -e "${GREEN}   ✓ Cache gelöscht${NC}"
fi

# Build
echo -e "${YELLOW}🔨 Starte PyInstaller Build...${NC}"
echo ""

if ! pyinstaller build_app.spec --noconfirm; then
    die "PyInstaller Build fehlgeschlagen"
fi

echo ""

# Prüfe Ergebnis
if [ ! -d "dist/WhisperGo.app" ]; then
    die "Build fehlgeschlagen: dist/WhisperGo.app nicht gefunden"
fi

# Signiere App (ad-hoc)
echo -e "${YELLOW}🔐 Signiere App (ad-hoc)...${NC}"
codesign --force --deep --sign - dist/WhisperGo.app
echo -e "${GREEN}   ✓ Signiert${NC}"

# Größe anzeigen
APP_SIZE=$(du -sh dist/WhisperGo.app | cut -f1)

echo ""
echo -e "${GREEN}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  ✅ Build erfolgreich!${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════════════════════${NC}"
echo ""
echo "   📁 App:   dist/WhisperGo.app"
echo "   📊 Größe: ${APP_SIZE}"
echo ""

# DMG erstellen wenn gewünscht
if [ "$BUILD_DMG" = "true" ]; then
    echo -e "${YELLOW}📦 Erstelle DMG...${NC}"
    echo ""
    ./build_dmg.sh
fi

# App öffnen wenn gewünscht
if [ "$OPEN_APP" = "true" ]; then
    echo -e "${YELLOW}🚀 Starte App...${NC}"
    open dist/WhisperGo.app
fi
