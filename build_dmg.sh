#!/bin/bash
# =============================================================================
# WhisperGo DMG Builder
# =============================================================================
# Erstellt eine signierte DMG-Datei für die Distribution
#
# Voraussetzungen:
#   - PyInstaller Build muss existieren: dist/WhisperGo.app
#   - create-dmg (optional, für schöneres DMG): brew install create-dmg
#
# Usage:
#   ./build_dmg.sh [version]
#   ./build_dmg.sh 1.0.0
# =============================================================================

set -e  # Exit on error

# === Konfiguration ===
APP_NAME="WhisperGo"
APP_PATH="dist/${APP_NAME}.app"
VERSION="${1:-1.0.0}"
DMG_NAME="${APP_NAME}-${VERSION}"
DMG_PATH="dist/${DMG_NAME}.dmg"
VOLUME_NAME="${APP_NAME} ${VERSION}"

# Farben für Output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  WhisperGo DMG Builder - Version ${VERSION}${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════════════════════${NC}"
echo ""

# === Prüfungen ===
if [ ! -d "$APP_PATH" ]; then
    echo -e "${RED}❌ Fehler: ${APP_PATH} nicht gefunden!${NC}"
    echo "   Führe zuerst aus: pyinstaller build_app.spec --clean"
    exit 1
fi

# === Ad-hoc Code Signing ===
echo -e "${YELLOW}🔐 Signiere App (ad-hoc)...${NC}"
codesign --force --deep --sign - "$APP_PATH"
echo -e "${GREEN}   ✓ App signiert${NC}"

# Signatur verifizieren
echo -e "${YELLOW}🔍 Verifiziere Signatur...${NC}"
if codesign --verify --deep --strict "$APP_PATH" 2>/dev/null; then
    echo -e "${GREEN}   ✓ Signatur gültig${NC}"
else
    echo -e "${YELLOW}   ⚠ Ad-hoc Signatur (keine Apple Developer ID)${NC}"
fi

# === Alte DMG entfernen ===
if [ -f "$DMG_PATH" ]; then
    echo -e "${YELLOW}🗑  Entferne alte DMG...${NC}"
    rm "$DMG_PATH"
fi

# === DMG erstellen ===
echo ""
echo -e "${YELLOW}📦 Erstelle DMG...${NC}"

# Prüfe ob create-dmg installiert ist (schönere DMGs)
if command -v create-dmg &> /dev/null; then
    echo "   Nutze create-dmg für professionelles Layout..."

    # Temporäres Verzeichnis für DMG-Inhalt
    DMG_TEMP="dist/dmg_temp"
    rm -rf "$DMG_TEMP"
    mkdir -p "$DMG_TEMP"
    cp -R "$APP_PATH" "$DMG_TEMP/"

    create-dmg \
        --volname "$VOLUME_NAME" \
        --volicon "assets/icon.icns" \
        --window-pos 200 120 \
        --window-size 600 400 \
        --icon-size 100 \
        --icon "${APP_NAME}.app" 150 185 \
        --app-drop-link 450 185 \
        --hide-extension "${APP_NAME}.app" \
        "$DMG_PATH" \
        "$DMG_TEMP"

    rm -rf "$DMG_TEMP"
else
    echo "   Nutze hdiutil (Standard)..."
    echo "   Tipp: 'brew install create-dmg' für schönere DMGs"

    # Einfache DMG mit hdiutil
    hdiutil create -volname "$VOLUME_NAME" \
        -srcfolder "$APP_PATH" \
        -ov -format UDZO \
        "$DMG_PATH"
fi

# === Ergebnis ===
echo ""
echo -e "${GREEN}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  ✅ DMG erfolgreich erstellt!${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════════════════════${NC}"
echo ""
echo "   📁 Datei: ${DMG_PATH}"
echo "   📊 Größe: $(du -h "$DMG_PATH" | cut -f1)"
echo ""
echo "   Nächste Schritte:"
echo "   1. DMG testen: open ${DMG_PATH}"
echo "   2. GitHub Release erstellen:"
echo "      gh release create v${VERSION} ${DMG_PATH} --title \"v${VERSION}\" --generate-notes"
echo ""
